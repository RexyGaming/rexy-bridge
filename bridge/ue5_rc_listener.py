#!/usr/bin/env python3
"""
ue5_rc_listener.py  —  Generic OSC -> Unreal Engine 5 Remote Control bridge
===========================================================================

This is a clean, mappings-driven rebuild of the bridge that rexy_osc.py
optionally imports. Its job: take an OSC address + normalised value and push
it to a property on a UE5 object via the **Remote Control WebSocket API**
(ws://<host>:30020). Because Remote Control writes properties *live in the
editor* (not just in Play/PIE), this is what lets the wheels move the camera
without pressing Play.

DESIGN PRINCIPLES (see project memory "rexy-product-vision" / "rexy-hardware-roadmap"):
  * NOTHING here is pan/tilt-specific. Every route lives in mappings.json.
    Adding Grip (crane pitch/yaw/scope) or Focus (zoom/focus) later = new
    lines in mappings.json, no code changes.
  * The OSC layer is the stable contract. Today OSC comes from rexy_osc.py
    (HID -> pygame -> OSC); tomorrow it may come straight from a Pi Pico 2W
    over Ethernet/WiFi. This bridge doesn't care where OSC originates.
  * Never break the working UDP-OSC path. By default this bridge does its
    Remote Control work as a *side effect* and reports "not handled" so the
    existing plain-UDP OSC send still fires too (good for a Blueprint OSC
    receiver in Play mode). Flip "suppress_udp_when_handled" in mappings.json
    if you ever want RC to take over exclusively.

INTERFACE (exactly what rexy_osc.py calls — do not rename without updating it):
    load_mappings(script_dir)                    -> dict           (sync, at startup)
    get_rc_fields()                              -> list[str]      (sync, for app picker)
    async apply_osc_to_ue5(path, value, verbose) -> bool           (True = "handled", suppresses UDP)
    async listener_loop(broadcast, ue5_host=, verbose=)            (maintains the WS connection)

SAFETY: every public entry point swallows its own errors. If UE / Remote
Control isn't running, the bridge just retries quietly in the background and
apply_osc_to_ue5 returns False, so rexy_osc.py keeps working exactly as it
does today.

⚠ TO CONFIRM AGAINST UE 5.7 DURING TESTING (marked inline with CONFIRM:):
    1. The exact propertyValue nesting in the PUT body.
    2. WRITE_ACCESS vs WRITE_TRANSACTION_ACCESS behaviour at streaming rates.
    3. Whether RelativeRotation can be set per-component or must be sent whole
       (this file assumes "send whole struct, merge components locally").
"""

import asyncio
import json
import os
import time

try:
    import websockets
except ImportError:  # pragma: no cover - rexy_osc.py already checks this
    websockets = None


# ---------------------------------------------------------------------------
# Module state (populated by load_mappings, used by the async coroutines)
# ---------------------------------------------------------------------------

_config = {
    "host": "127.0.0.1",
    "ws_port": 30020,                 # UE Remote Control WebSocket default
    "access": "WRITE_ACCESS",         # low-latency; avoids per-change undo txns
    "suppress_udp_when_handled": False,
    "reconnect_seconds": 3.0,
}
_mappings = {}          # osc_address -> mapping dict
_struct_cache = {}      # (objectPath, propertyName) -> last full struct dict
_loop = None            # the asyncio loop the bridge runs on (set in listener_loop)
_send_queue = None      # asyncio.Queue of ready-to-send JSON strings
_connected = False
_request_id = 0
_pending = {}           # RequestId -> asyncio.Future, for request/response calls (read/call/describe)


# ---------------------------------------------------------------------------
# Startup: load mappings.json
# ---------------------------------------------------------------------------

def load_mappings(script_dir):
    """Load mappings.json from the script directory. Returns the osc->mapping
    dict (also stored in module state). Safe: returns {} on any problem."""
    global _mappings, _config
    path = os.path.join(script_dir, "mappings.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"  RC bridge: no mappings.json found at {path} — bridge idle.")
        return {}
    except Exception as e:
        print(f"  RC bridge: failed to read mappings.json — {e}")
        return {}

    # Merge any provided ue5 config over the defaults
    ue5 = data.get("ue5", {})
    for k in ("host", "ws_port", "access", "suppress_udp_when_handled", "reconnect_seconds",
              "crane_rerun_construction"):
        if k in ue5:
            _config[k] = ue5[k]

    _mappings = {}
    for m in data.get("mappings", []):
        osc = m.get("osc")
        if osc:
            _mappings[osc] = m

    print(f"  RC bridge: loaded {len(_mappings)} mapping(s) -> "
          f"ws://{_config['host']}:{_config['ws_port']} (access={_config['access']})")
    return _mappings


def save_mappings_with_backup(script_dir):
    """Snapshot the current in-memory _mappings (with objectPaths as they were
    resolved by the most recent set_camera() + retarget_crane_for_camera() runs)
    back to mappings.json. The existing mappings.json is renamed with a
    timestamp suffix first, so the user always has a safety net.

    Returns the absolute path to the saved file on success."""
    import datetime
    path = os.path.join(script_dir, "mappings.json")
    # Read the existing file so we preserve the top-level "ue5" config and any
    # comment fields the user has added — we only replace the "mappings" array.
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = path.replace(".json", f".bak-{stamp}.json")
            os.replace(path, backup)
            print(f"  save_mappings: backup written → {os.path.basename(backup)}")
        except Exception as e:
            print(f"  save_mappings: backup failed — {e}")
    # Compose the new payload. Keep existing top-level keys; replace the
    # mappings list with the live _mappings (sorted by osc path so diffs are
    # readable). Drop runtime-only fields if any have crept in.
    payload = dict(existing)
    payload["mappings"] = [
        {k: v for k, v in _mappings[osc].items() if not k.startswith("_")}
        for osc in sorted(_mappings.keys())
    ]
    # Make sure the ue5 block exists even on a never-saved fresh install.
    payload.setdefault("ue5", dict(_config))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"  save_mappings: wrote {len(payload['mappings'])} mapping(s) → mappings.json")
    return path


def get_rc_fields():
    """Field list for the app's picker — the friendly labels we can drive."""
    out = []
    for osc, m in _mappings.items():
        out.append(m.get("label", osc))
    return out


# ---------------------------------------------------------------------------
# Value scaling
# ---------------------------------------------------------------------------

def _curve(t, m):
    """Apply an optional response curve to a normalised 0..1 value.

    "curve" is an exponent (gamma): 1.0 = linear (default), >1 = finer control
    near one end, <1 = coarser. With "bipolar": true the curve is applied
    symmetrically around the centre (0.5) — so e.g. curve 2.0 gives slow, fine
    movement near neutral and faster movement toward the extremes, which is the
    feel camera operators usually want for pan/tilt.
    """
    g = float(m.get("curve", 1.0))
    if g == 1.0:
        return t
    if m.get("bipolar", False):
        d = (t - 0.5) * 2.0                       # -1..+1 about centre
        s = (abs(d) ** g) * (1.0 if d >= 0 else -1.0)
        return 0.5 + s * 0.5
    return t ** g


def _scale(value, m):
    """Map a normalised input through range / curve / invert / calibrated_offset.
    Bipolar params (rotations/positions) use offset model: output = offset + delta,
    where delta = (t-0.5) * (out_max - out_min). Default offset=0 (=== old behaviour).
    Unipolar params (zoom/focus/aperture/scope) keep absolute scaling."""
    in_min = float(m.get("in_min", 0.0))
    in_max = float(m.get("in_max", 1.0))
    out_min = float(m.get("out_min", 0.0))
    out_max = float(m.get("out_max", 1.0))

    span = (in_max - in_min) or 1.0
    t = (float(value) - in_min) / span
    t = max(0.0, min(1.0, t))
    if m.get("invert", False):
        t = 1.0 - t
    if m.get("bipolar", False):
        offset = float(m.get("calibrated_offset", 0.0))
        sens   = float(m.get("sensitivity", 1.0))
        # NO slider-position deadband in absolute mode: the GUI filters D on the
        # RAW INPUT before accumulation, which kills wheel drift cleanly without
        # creating a dead zone in the middle of the slider's response. Velocity
        # modes (continuous wheels / drone / base) still use D via _velocity_delta.
        t = _curve(t, m)
        delta = (t - 0.5) * sens * (out_max - out_min)
        return offset + delta
    t = _curve(t, m)
    # Unipolar — optional log scale. Useful for params like focus distance that
    # span many orders of magnitude (30cm to ∞). The slider stays 0..1 on the
    # wire; the mapping decides whether to interpolate linearly or in log space.
    if m.get("scale_type") == "log" and out_min > 0 and out_max > 0:
        import math
        log_min = math.log(out_min)
        log_max = math.log(out_max)
        return math.exp(log_min + t * (log_max - log_min))
    return out_min + t * (out_max - out_min)


# ---------------------------------------------------------------------------
# Build the Remote Control PUT message
# ---------------------------------------------------------------------------

def _build_property_value(m, scaled):
    """Produce the propertyValue payload for one mapping.

    Two shapes:
      * Scalar property (e.g. CurrentFocalLength, CraneArmLength):
            propertyValue = { <propertyName>: <float> }
      * Struct component (e.g. RelativeRotation.Yaw): we keep a cache of the
        last full struct for (objectPath, propertyName), update just the named
        component, and send the whole struct back. This is because RC replaces
        the whole struct on write.   ← CONFIRM: per-component write support in 5.7.
    """
    prop = m["propertyName"]
    component = m.get("component")

    if component:
        key = (m["objectPath"], prop)
        struct = _struct_cache.get(key)
        if struct is None:
            # Initialise from mapping's "struct_init" or sensible rotator default
            struct = dict(m.get("struct_init", {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0}))
        struct[component] = scaled
        _struct_cache[key] = struct
        return {prop: dict(struct)}

    return {prop: scaled}


def _build_message(m, scaled):
    """Full UE Remote Control WebSocket 'http passthrough' envelope.

    CONFIRM against UE 5.7: the documented HTTP body uses
        { objectPath, access, propertyName, propertyValue }
    and the WS transport wraps it as { MessageName:'http', Parameters:{...} }.
    If 5.7 expects propertyValue flat (not keyed by propertyName), adjust
    _build_property_value above — that's the single point of change.
    """
    global _request_id
    _request_id += 1
    return json.dumps({
        "MessageName": "http",
        "Parameters": {
            "RequestId": _request_id,
            "Url": "/remote/object/property",
            "Verb": "PUT",
            "Body": {
                "objectPath": m["objectPath"],
                # Per-mapping access override (defaults to global). Some properties
                # need WRITE_TRANSACTION_ACCESS to fire PostEditChangeProperty —
                # e.g. CameraRig_Crane params, whose editor preview meshes only
                # rebuild correctly through the transactional path.
                "access": m.get("access", _config["access"]),
                "propertyName": m["propertyName"],
                "propertyValue": _build_property_value(m, scaled),
            },
        },
    })


# ---------------------------------------------------------------------------
# Discovery state — gates pre-UE-ready noise and feeds the app's status UI.
# Lifecycle: booting → waiting → ready ⇄ lost. set_discovery_state() invokes
# the registered broadcaster (rexy_osc.py registers one that pushes to all
# connected WebSocket clients), and silently no-ops if none registered.
# ---------------------------------------------------------------------------
_discovery_state = "booting"            # set to "ready" after first camera resolves
_discovery_broadcaster = None           # optional callable: (state_dict) -> None
_discovery_camera_count = 0

def get_discovery_state():
    return _discovery_state

def is_discovery_ready():
    return _discovery_state == "ready"

def register_discovery_broadcaster(cb):
    """Called by rexy_osc.py at startup. cb receives a dict and should push it
    to all connected app WebSocket clients."""
    global _discovery_broadcaster
    _discovery_broadcaster = cb

def set_discovery_state(state, *, camera_count=None, note=None):
    """Transition the discovery state machine. Suppresses no-op transitions so
    we don't spam the app with repeated identical updates."""
    global _discovery_state, _discovery_camera_count
    changed = False
    if state != _discovery_state:
        _discovery_state = state
        changed = True
    if camera_count is not None and camera_count != _discovery_camera_count:
        _discovery_camera_count = camera_count
        changed = True
    if not changed:
        return
    payload = {"type": "discovery_status", "state": _discovery_state,
               "cameras": _discovery_camera_count}
    if note is not None:
        payload["note"] = note
    if _discovery_broadcaster is not None:
        try: _discovery_broadcaster(payload)
        except Exception as e:
            print(f"  discovery broadcaster failed — {e}")


# ---------------------------------------------------------------------------
# Request / response helpers — for reads, function calls, and describe.
# Unlike the fire-and-forget property writes above, these await UE's reply,
# correlated by RequestId. Used by the equipment-profiles layer (lens preset
# calls, reading back LensSettings, discovering functions via describe).
# All run on the bridge's asyncio loop.
# ---------------------------------------------------------------------------

def _next_request_id():
    global _request_id
    _request_id += 1
    return _request_id


async def _request(verb, url, body, timeout=5.0, verbose=False):
    """Send an http-passthrough request and await UE's response (by RequestId).
    Returns the parsed response dict, or None on timeout / not-connected."""
    if _send_queue is None or _loop is None:
        return None
    rid = _next_request_id()
    msg = json.dumps({
        "MessageName": "http",
        "Parameters": {"RequestId": rid, "Url": url, "Verb": verb, "Body": body},
    })
    fut = _loop.create_future()
    _pending[rid] = fut
    _send_queue.put_nowait(msg)
    try:
        resp = await asyncio.wait_for(fut, timeout)
        if verbose:
            print(f"  RC resp[{rid}] {str(resp)[:200]}")
        return resp
    except asyncio.TimeoutError:
        _pending.pop(rid, None)
        if verbose:
            print(f"  RC request {verb} {url} timed out after {timeout}s")
        return None


async def call_function(object_path, function_name, parameters=None, verbose=False):
    """Call a UE function via /remote/object/call (e.g. SetLensPresetByName).
    Returns the response dict (may contain return values)."""
    body = {
        "objectPath": object_path,
        "functionName": function_name,
        "parameters": parameters or {},
        "generateTransaction": False,
    }
    return await _request("PUT", "/remote/object/call", body, verbose=verbose)


async def read_property(object_path, property_name, verbose=False):
    """Read a property via /remote/object/property with READ_ACCESS.
    Returns the raw value if it can be located in the response, else the full
    response dict (shape varies — log in verbose to inspect)."""
    body = {
        "objectPath": object_path,
        "propertyName": property_name,
        "access": "READ_ACCESS",
    }
    resp = await _request("PUT", "/remote/object/property", body, verbose=verbose)
    if not isinstance(resp, dict):
        return resp
    # Response value commonly lives under ResponseBody, keyed by propertyName.
    body_out = resp.get("ResponseBody", resp.get("responseBody", {}))
    if isinstance(body_out, dict) and property_name in body_out:
        return body_out[property_name]
    return resp


async def describe_object(object_path, verbose=False):
    """Describe an object via /remote/object/describe — lists its properties
    AND callable functions (use this to confirm exact UE 5.7 function names like
    SetLensPresetByName before wiring the profile layer)."""
    body = {"objectPath": object_path}
    return await _request("PUT", "/remote/object/describe", body, verbose=verbose)


# ---------------------------------------------------------------------------
# Calibration: read current UE value, store as the param's neutral (offset).
# Slider 0.5 then = "no change from where the camera is". Reset = re-calibrate.
# ---------------------------------------------------------------------------

async def calibrate_param(osc_path, verbose=False):
    """Read the current value of a param's UE property and store as its calibrated
    offset. For struct properties (e.g. RelativeRotation), reads the full struct,
    refreshes the cache (so other components don't get zeroed on next write), and
    calibrates ALL bipolar params that share that (objectPath, propertyName).
    Logs unconditionally (we need to be able to diagnose without --verbose)."""
    m = _mappings.get(osc_path)
    if not m:
        # Pre-discovery the mappings are still placeholder paths and missing
        # entries are expected — only warn once we've actually got a camera.
        if is_discovery_ready():
            print(f"  Calibrate {osc_path}: no mapping found")
        return None
    obj = m["objectPath"]; prop = m["propertyName"]
    print(f"  Calibrating {osc_path}  ({prop} on …{obj[-50:]})")
    val = await read_property(obj, prop, verbose=True)
    if val is None:
        print(f"  Calibrate {osc_path}: read returned None — UE didn't respond"); return None
    print(f"  Calibrate {osc_path}: read value = {str(val)[:160]}")
    if isinstance(val, dict):
        _struct_cache[(obj, prop)] = dict(val)
        for p, mm in _mappings.items():
            if mm.get("objectPath") == obj and mm.get("propertyName") == prop and mm.get("bipolar"):
                comp = mm.get("component")
                if comp and comp in val:
                    mm["calibrated_offset"] = float(val[comp])
                    print(f"  Calibrated {p} ({comp}) → offset {float(val[comp]):+.3f}")
                else:
                    print(f"  Calibrate {p}: component '{comp}' not in read value")
        return val
    if m.get("bipolar"):
        m["calibrated_offset"] = float(val)
        print(f"  Calibrated {osc_path} → offset {float(val):+.3f}")
    return val


async def force_write(osc_path, slider_value):
    """Write a property regardless of wheel/grip mode intercepts. Slider-space:
    value is run through _scale to produce the property write. Used by Autolevel
    in absolute mode."""
    m = _mappings.get(osc_path)
    if not m:
        return
    # Park related velocity state so the next tick doesn't reapply rotation
    axis = osc_path.rsplit("/", 1)[-1]
    if axis in _wheel_state:    _wheel_state[axis] = 0.5
    if axis in _drone_state:    _drone_state[axis.upper() if len(axis)==1 else axis] = 0.5
    if axis in _base_state:     _base_state[axis.upper() if len(axis)==1 else axis] = 0.5
    try:
        msg = _build_message(m, _scale(float(slider_value), m))
        if _send_queue is not None:
            _send_queue.put_nowait(msg)
    except Exception:
        pass


async def force_write_value(osc_path, absolute_value):
    """Like force_write but the second argument is the ABSOLUTE property value
    (not a slider value). Bypasses _scale entirely. Used by Autolevel in continuous
    wheel mode where the slider represents velocity, not angle — we need to write
    the target rotation directly."""
    m = _mappings.get(osc_path)
    if not m:
        return
    axis = osc_path.rsplit("/", 1)[-1]
    if axis in _wheel_state:    _wheel_state[axis] = 0.5
    if axis in _drone_state:    _drone_state[axis.upper() if len(axis)==1 else axis] = 0.5
    if axis in _base_state:     _base_state[axis.upper() if len(axis)==1 else axis] = 0.5
    try:
        global _request_id
        _request_id += 1
        msg = json.dumps({
            "MessageName": "http",
            "Parameters": {
                "RequestId": _request_id,
                "Url": "/remote/object/property",
                "Verb": "PUT",
                "Body": {
                    "objectPath": m["objectPath"],
                    "access": m.get("access", _config["access"]),
                    "propertyName": m["propertyName"],
                    "propertyValue": _build_property_value(m, float(absolute_value)),
                },
            },
        })
        if _send_queue is not None:
            _send_queue.put_nowait(msg)
    except Exception:
        pass


def clear_offset(osc_path):
    """Reset calibrated_offset to 0 for a bipolar param. Used by the GUI's Reset
    button — combined with sending slider=0.5, this makes the camera snap to
    absolute 0 (offset gone, no delta from centre). Sync, no UE round-trip."""
    m = _mappings.get(osc_path)
    if not m:
        print(f"  Clear offset: no mapping for {osc_path}"); return
    if not m.get("bipolar"):
        return                                          # unipolar params have no offset
    m["calibrated_offset"] = 0.0
    # Invalidate the cached struct so the next write doesn't carry stale components
    obj  = m.get("objectPath"); prop = m.get("propertyName")
    if obj and prop:
        _struct_cache.pop((obj, prop), None)
    print(f"  Cleared offset for {osc_path}")


async def auto_calibrate_camera(verbose=False):
    """After a camera change (set_camera) or entering Dolly, calibrate every
    bipolar mapping that's relevant so the sliders read 'no change from here'."""
    seen = set()
    for path in ("/rexy/pan", "/rexy/tilt", "/rexy/roll", "/rexy/craneYaw", "/rexy/scope", "/rexy/cranePitch"):
        m = _mappings.get(path)
        if not m or not m.get("bipolar"):
            continue
        key = (m.get("objectPath"), m.get("propertyName"))
        if key in seen:
            continue
        seen.add(key)
        await calibrate_param(path, verbose=verbose)


async def is_camera_on_crane(actor_path, verbose=False):
    """Best-effort: ask UE if this camera's SceneComponent has an attach parent
    that looks like a CameraRig_Crane. Returns False if unknown / detached."""
    try:
        scene = actor_path + ".SceneComponent"
        resp = await call_function(scene, "GetAttachParent", {}, verbose=verbose)
        if not isinstance(resp, dict):
            return False
        body = resp.get("ResponseBody", {})
        # ReturnValue may be the parent's object path string, or null
        rv = None
        if isinstance(body, dict):
            rv = body.get("ReturnValue") or body.get("returnValue")
        if not rv:
            return False
        return "CameraRig_Crane" in str(rv)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pedestal mode — camera-local velocity via K2_AddLocalOffset (a tick loop).
# ---------------------------------------------------------------------------

_drone_state = {"X": 0.5, "Y": 0.5, "Z": 0.5}      # last slider value per axis
_drone_task = None                                  # asyncio.Task while active
_base_state = {"X": 0.5, "Y": 0.5, "Z": 0.5}       # base-translate slider values (always velocity)
_base_task = None                                   # base velocity task (lazy-started)
_tuning = {"sensitivity": 1.0, "deadband": 0.08}    # shared velocity tuning (drone + base)
                                                    # default 0.08 to absorb sticky-stick drift
                                                    # (per-param tuning overrides this)


def set_tuning(sensitivity=None, deadband=None):
    """Update the global velocity tuning defaults (used when per-param tuning isn't set)."""
    if sensitivity is not None:
        try: _tuning["sensitivity"] = max(0.01, float(sensitivity))
        except Exception: pass
    if deadband is not None:
        try: _tuning["deadband"] = max(0.0, min(0.49, float(deadband)))
        except Exception: pass
    print(f"  Velocity tuning (global): sens={_tuning['sensitivity']:.2f}  dead={_tuning['deadband']:.3f}")


def set_param_range(osc_path, out_min=None, out_max=None):
    """Per-parameter output range — stored on the mapping. Applied wherever the
    param is scaled. Mirrors out_min/out_max in mappings.json but lets the GUI
    override at runtime via each card's Min/Max inputs."""
    m = _mappings.get(osc_path)
    if not m:
        # Same as calibrate: pre-discovery these warnings are noise.
        if is_discovery_ready():
            print(f"  Param range: no mapping for {osc_path}")
        return
    if out_min is not None:
        try: m["out_min"] = float(out_min)
        except Exception: pass
    if out_max is not None:
        try: m["out_max"] = float(out_max)
        except Exception: pass
    print(f"  Param range: {osc_path}  min={m.get('out_min')}  max={m.get('out_max')}")


def set_param_tuning(osc_path, sensitivity=None, deadband=None):
    """Per-parameter sens/dead — stored on the mapping, applied wherever the param
    is used (absolute bipolar scaling, drone, or base velocity)."""
    m = _mappings.get(osc_path)
    if not m:
        print(f"  Param tuning: no mapping for {osc_path}"); return
    if sensitivity is not None:
        try: m["sensitivity"] = max(0.01, float(sensitivity))
        except Exception: pass
    if deadband is not None:
        try: m["deadband"] = max(0.0, min(0.49, float(deadband)))
        except Exception: pass
    print(f"  Param tuning: {osc_path}  sens={m.get('sensitivity',1.0):.2f}  dead={m.get('deadband',0.0):.3f}")


DT_TICK = 0.033          # ~30Hz tick rate for velocity loops
BASE_VEL_CMS = 200.0     # base translation max speed (cm/s) at sensitivity 1.0
DRONE_VEL_CMS = 120.0    # drone (camera-local) max speed (cm/s) at sensitivity 1.0
WHEEL_VEL_DEGSEC = 90.0  # continuous-wheels max rotation speed (deg/s) at sens 1.0

# ---- Continuous Wheels (pan/tilt/roll velocity) ---------------------------
_wheel_state = {"pan": 0.5, "tilt": 0.5, "roll": 0.5}   # last slider value per wheel
_wheel_task  = None                                      # asyncio.Task while continuous
_wheel_mode  = "absolute"                                # "absolute" | "continuous"


def _velocity_delta(slider_value, max_cms, sensitivity=None, deadband=None):
    """Common velocity shaper. slider 0.5 = 0; quadratic curve from deadband;
    sensitivity multiplies the max speed. Returns delta in UE units for one tick.
    If sensitivity / deadband args are None, falls back to the global _tuning."""
    sens = float(sensitivity) if sensitivity is not None else _tuning["sensitivity"]
    dead = float(deadband)    if deadband    is not None else _tuning["deadband"]
    t = (slider_value - 0.5) * 2.0
    if abs(t) <= dead:
        return 0.0
    sign = 1.0 if t > 0 else -1.0
    norm = (abs(t) - dead) / max(1e-6, 1.0 - dead)
    shaped = sign * (norm ** 2.0)
    return shaped * max_cms * sens * DT_TICK


async def _drone_tick(verbose=False):
    """Run while grip mode is 'drone'. Each tick, integrate slider deviations
    into a camera-LOCAL delta and call K2_AddLocalOffset on the camera."""
    cam_scene = _mappings.get("/rexy/pan", {}).get("objectPath")
    if not cam_scene:
        return
    GRIP_PARAM = {"X": "/rexy/craneYaw", "Y": "/rexy/scope", "Z": "/rexy/cranePitch"}
    while _grip_mode == "drone":
        # Per-axis sens/dead come from each axis's mapping (per-param tuning).
        per = {}
        for grip_axis in ("X", "Y", "Z"):
            m = _mappings.get(GRIP_PARAM[grip_axis], {})
            per[grip_axis] = _velocity_delta(_drone_state.get(grip_axis, 0.5),
                                             DRONE_VEL_CMS, m.get("sensitivity"), m.get("deadband"))
        # Grip X = left/right, Grip Y = forward/back, but UE camera-local +X is
        # forward and +Y is right. So swap them when building the local delta.
        delta = {"X": per["Y"], "Y": per["X"], "Z": per["Z"]}
        if any(delta.values()):
            body = {"DeltaLocation": delta, "bSweep": False, "bTeleport": True}
            try:
                await call_function(cam_scene, "K2_AddLocalOffset", body, verbose=False)
            except Exception:
                pass
        await asyncio.sleep(DT_TICK)


async def _base_tick(verbose=False):
    """Always-running once started. Translate base X/Y/Z slider deviations into
    WORLD-space deltas and call K2_AddWorldOffset on the crane TransformComponent.
    Velocity-based — slider centre = no movement, deviation = rate (uses tuning)."""
    crane_xform = _mappings.get("/rexy/baseX", {}).get("objectPath")
    if not crane_xform:
        return
    BASE_PARAM = {"X": "/rexy/baseX", "Y": "/rexy/baseY", "Z": "/rexy/baseZ"}
    while True:
        delta = {}
        for a in ("X", "Y", "Z"):
            m = _mappings.get(BASE_PARAM[a], {})
            delta[a] = _velocity_delta(_base_state.get(a, 0.5), BASE_VEL_CMS,
                                       m.get("sensitivity"), m.get("deadband"))
        if any(delta.values()):
            body = {"DeltaLocation": delta, "bSweep": False, "bTeleport": True}
            try:
                await call_function(crane_xform, "K2_AddWorldOffset", body, verbose=False)
            except Exception:
                pass
        await asyncio.sleep(DT_TICK)


async def _wheel_tick(verbose=False):
    """CONTINUOUS WHEELS mode: pan/tilt/roll become VELOCITY controls instead of
    absolute positions. Each tick, integrate slider deviations into a camera-LOCAL
    rotation delta and call K2_AddLocalRotation on the camera SceneComponent.
    Slider 0.5 = no movement; ±0.5 = max ±WHEEL_VEL_DEGSEC × sens. Per-axis sens/dead
    from each wheel's mapping (same per-param tuning as drone)."""
    cam_scene = _mappings.get("/rexy/pan", {}).get("objectPath")
    if not cam_scene:
        return
    WHEEL_COMP = {"pan": "Yaw", "tilt": "Pitch", "roll": "Roll"}
    while _wheel_mode == "continuous":
        delta_rot = {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0}
        for axis, comp in WHEEL_COMP.items():
            m = _mappings.get("/rexy/" + axis, {})
            delta_rot[comp] = _velocity_delta(_wheel_state.get(axis, 0.5),
                                              WHEEL_VEL_DEGSEC,
                                              m.get("sensitivity"), m.get("deadband"))
        if any(delta_rot.values()):
            body = {"DeltaRotation": delta_rot, "bSweep": False, "bTeleport": True}
            try:
                await call_function(cam_scene, "K2_AddLocalRotation", body, verbose=False)
            except Exception:
                pass
        await asyncio.sleep(DT_TICK)


async def set_wheel_mode(mode, verbose=False):
    """Swap the camera head between ABSOLUTE (today) and CONTINUOUS (velocity).
      absolute   -> slider position = exact rotation (calibrated_offset + delta)
      continuous -> slider position = rate of rotation (K2_AddLocalRotation tick).
                    Slider centre = no movement. Range effectively infinite."""
    global _wheel_mode, _wheel_task
    if _wheel_task and not _wheel_task.done():
        _wheel_task.cancel()
    _wheel_task = None
    new_mode = mode if mode in ("absolute", "continuous") else "absolute"
    _wheel_state.update({"pan": 0.5, "tilt": 0.5, "roll": 0.5})
    _wheel_mode = new_mode
    if new_mode == "continuous":
        cam = _mappings.get("/rexy/pan", {}).get("objectPath")
        if cam:
            _wheel_task = asyncio.ensure_future(_wheel_tick(verbose))
            print("  Wheel mode: CONTINUOUS (camera-local velocity, K2_AddLocalRotation)")
            return
        print("  Wheel mode: CONTINUOUS requested but no camera mapping yet — staying absolute")
        _wheel_mode = "absolute"
        return
    print("  Wheel mode: ABSOLUTE (calibrated_offset + slider)")


def _camera_object_path():
    """Best-effort CineCameraComponent path, taken from a camera mapping."""
    for osc in ("/rexy/zoom", "/rexy/aperture", "/rexy/focus"):
        m = _mappings.get(osc)
        if m:
            return m["objectPath"]
    return None


async def apply_lens_preset(name, verbose=True):
    """Equipment-profiles STEP 2: select a built-in UE lens preset by name,
    read back the resulting LensSettings, and re-scope the zoom/aperture/focus
    mappings to that lens's real range. Returns the LensSettings dict (or None)."""
    cam = _camera_object_path()
    if not cam:
        print("  apply_lens_preset: no camera objectPath (need a /rexy/zoom mapping)")
        return None

    # 1) Apply the preset by name.
    await call_function(cam, "SetLensPresetByName", {"InPresetName": name}, verbose=verbose)

    # 2) Read back the actual lens settings UE applied.
    ls = await read_property(cam, "LensSettings", verbose=verbose)
    if verbose:
        print(f"  LensSettings now: {ls}")
    if not isinstance(ls, dict):
        print("  apply_lens_preset: couldn't read LensSettings back — preset applied, ranges unchanged.")
        return ls

    # 3) Re-scope the continuous mappings to the lens (live, in-memory).
    minF = ls.get("MinFocalLength"); maxF = ls.get("MaxFocalLength")
    minS = ls.get("MinFStop");       maxS = ls.get("MaxFStop")
    minFocus = ls.get("MinimumFocusDistance")
    if minF is not None and maxF is not None and "/rexy/zoom" in _mappings:
        _mappings["/rexy/zoom"]["out_min"] = float(minF)
        _mappings["/rexy/zoom"]["out_max"] = float(maxF)
    if minS is not None and "/rexy/aperture" in _mappings:
        _mappings["/rexy/aperture"]["out_min"] = float(minS)
        if maxS is not None:
            _mappings["/rexy/aperture"]["out_max"] = float(maxS)
    if minFocus is not None and "/rexy/focus" in _mappings:
        _mappings["/rexy/focus"]["out_min"] = float(minFocus)
    print(f"  Lens '{name}' applied + re-scoped: "
          f"zoom {minF}-{maxF}mm | aperture f/{minS}-{maxS} | focus min {minFocus}cm")
    return ls


async def apply_custom_lens(name, min_focal, max_focal,
                            min_aperture, max_aperture, min_focus, max_focus=100000,
                            verbose=True):
    """User-defined lens (not in UE's built-in preset list). Writes a LensSettings
    struct directly on the camera AND re-scopes the zoom/aperture/focus mappings
    so the sliders span the new lens range. max_focus defaults to 100000cm (1km)
    which is effectively infinity for any cinema use. Returns the LensSettings."""
    cam = _camera_object_path()
    if not cam:
        print("  apply_custom_lens: no camera objectPath")
        return None
    try:
        minF = float(min_focal);    maxF = float(max_focal)
        minS = float(min_aperture); maxS = float(max_aperture)
        minD = float(min_focus);    maxD = float(max_focus) if max_focus is not None else 100000.0
    except (TypeError, ValueError) as e:
        print(f"  apply_custom_lens: bad numeric params — {e}")
        return None

    ls = {
        "MinFocalLength": minF, "MaxFocalLength": maxF,
        "MinFStop": minS,       "MaxFStop": maxS,
        "MinimumFocusDistance": minD,
        "DiaphragmBladeCount": 6,                       # sensible default
    }
    await _request("PUT", "/remote/object/property",
                   {"objectPath": cam, "access": _config["access"],
                    "propertyName": "LensSettings",
                    "propertyValue": {"LensSettings": ls}},
                   verbose=verbose)

    # Re-scope continuous mappings (slider span follows the lens)
    if "/rexy/zoom" in _mappings:
        _mappings["/rexy/zoom"]["out_min"] = minF
        _mappings["/rexy/zoom"]["out_max"] = maxF
    if "/rexy/aperture" in _mappings:
        _mappings["/rexy/aperture"]["out_min"] = minS
        _mappings["/rexy/aperture"]["out_max"] = maxS
    if "/rexy/focus" in _mappings:
        _mappings["/rexy/focus"]["out_min"] = minD
        _mappings["/rexy/focus"]["out_max"] = maxD
    print(f"  Custom lens '{name}' applied: zoom {minF}-{maxF}mm | f/{minS}-{maxS} | focus {minD}cm-{maxD}cm")
    return ls


async def apply_filmback_preset(name, verbose=True):
    """Select a built-in UE filmback (sensor/body) preset by name — e.g.
    'Super 35mm', 'IMAX 70mm', 'Full Frame DSLR'. Changes the sensor size, which
    drives the camera's field of view / framing. Returns the FilmbackSettings."""
    cam = _camera_object_path()
    if not cam:
        print("  apply_filmback_preset: no camera objectPath (need a /rexy/zoom mapping)")
        return None

    await call_function(cam, "SetFilmbackPresetByName", {"InPresetName": name}, verbose=verbose)
    fb = await read_property(cam, "FilmbackSettings", verbose=verbose)
    if verbose:
        print(f"  FilmbackSettings now: {fb}")
    if isinstance(fb, dict):
        w = fb.get("SensorWidth")
        h = fb.get("SensorHeight")
        print(f"  Filmback '{name}' applied: sensor {w} x {h} mm")
    return fb


# ---------------------------------------------------------------------------
# Grip modes — Crane vs Free-fly (Dolly). Swaps where the 3 grip axes write.
# ---------------------------------------------------------------------------

_GRIP_PARAMS = ["/rexy/craneYaw", "/rexy/scope", "/rexy/cranePitch"]
_grip_crane_targets = {}     # saved crane mappings for the grip params
_grip_mode = "crane"


async def set_grip_mode(mode, verbose=False):
    """Swap what the 3 grip axes (X / Y / Z) drive — NO crane deletion.
      crane    -> the CameraRig_Crane (CraneYaw / CraneArmLength / CranePitch).
      dolly    -> the camera's own RelativeLocation (free X/Y/Z move; crane parked).
                  Auto-calibrates so the slider centre = camera's current position.
      drone -> camera-LOCAL velocity via K2_AddLocalOffset (tick loop)."""
    global _grip_mode, _grip_crane_targets, _drone_task
    if not _grip_crane_targets:
        for p in _GRIP_PARAMS:
            if p in _mappings:
                _grip_crane_targets[p] = dict(_mappings[p])

    cam = _mappings.get("/rexy/pan", {}).get("objectPath")   # camera SceneComponent

    # stop any running drone tick first (mode change)
    if _drone_task and not _drone_task.done():
        _drone_task.cancel()
    _drone_task = None

    if mode == "drone" and cam:
        # reset sliders' last-known to centre — no inadvertent drift on entry
        _drone_state.update({"X": 0.5, "Y": 0.5, "Z": 0.5})
        _grip_mode = "drone"
        _drone_task = asyncio.ensure_future(_drone_tick(verbose))
        print("  Grip mode: DRONE (camera-local velocity, K2_AddLocalOffset)")
        return

    if mode == "dolly" and cam:
        # User axis convention: X = left/right, Y = fwd/back, Z = up/down.
        # UE camera-local axes: +X is forward, +Y is right, +Z is up.
        # So slider craneYaw (user-X, sideways) → UE Y; slider scope (user-Y, fwd/back) → UE X;
        # cranePitch (user-Z, up/down) → UE Z.
        comp = {"/rexy/craneYaw": "Y", "/rexy/scope": "X", "/rexy/cranePitch": "Z"}
        for p, c in comp.items():
            _mappings[p] = {"objectPath": cam, "propertyName": "RelativeLocation",
                            "component": c, "struct_init": {"X": 0.0, "Y": 0.0, "Z": 0.0},
                            "in_min": 0.0, "in_max": 1.0, "out_min": -500.0, "out_max": 500.0,
                            "bipolar": True, "invert": False}
        _struct_cache.pop((cam, "RelativeLocation"), None)
        _grip_mode = "dolly"
        print("  Grip mode: DOLLY (camera free-move; crane parked)")
        # auto-calibrate so the slider centre means 'no change from here'
        await calibrate_param("/rexy/craneYaw", verbose=verbose)
        return

    # mode == 'crane'
    for p, t in _grip_crane_targets.items():
        _mappings[p] = dict(t)
    if cam:   # re-seat the camera onto the mount
        await _request("PUT", "/remote/object/property",
                       {"objectPath": cam, "access": _config["access"],
                        "propertyName": "RelativeLocation",
                        "propertyValue": {"RelativeLocation": {"X": 0.0, "Y": 0.0, "Z": 0.0}}},
                       verbose=verbose)
        _struct_cache.pop((cam, "RelativeLocation"), None)
    _grip_mode = "crane"
    print("  Grip mode: CRANE")
    await calibrate_param("/rexy/craneYaw", verbose=verbose)


# ---------------------------------------------------------------------------
# Multiple cameras — discover via Remote Control's actor-search API (no
# RexyControl preset needed) and fall back to preset-based discovery if the
# search fails. Re-target controls to a chosen camera. Walk the attach chain
# to find a parent CameraRig_Crane (handled by retarget_crane_for_camera).
# ---------------------------------------------------------------------------

# Cache the full level-actor list for ~2 seconds so back-to-back calls (one
# for cameras, one for cranes) don't fire two separate UE round-trips. Reset
# whenever a new auto-scan is requested.
_actor_cache = {"paths": [], "expires_at": 0.0}

async def _try_get_all_level_actors(object_path, verbose=False, timeout=2.0):
    """Single attempt at /remote/object/call -> GetAllLevelActors on the given
    object path. Returns (paths, error_message). paths is empty on failure
    and error_message describes why so the caller can log it cleanly."""
    body = {
        "objectPath": object_path,
        "functionName": "GetAllLevelActors",
        "parameters": {},
        "generateTransaction": False,
    }
    resp = await _request("PUT", "/remote/object/call", body,
                          timeout=timeout, verbose=verbose)
    if not isinstance(resp, dict):
        return [], "no response"
    code = resp.get("ResponseCode")
    payload = resp.get("ResponseBody", resp)
    if code is not None and code >= 400:
        err = payload.get("errorMessage", f"HTTP {code}") if isinstance(payload, dict) else f"HTTP {code}"
        return [], err
    if not isinstance(payload, dict):
        return [], "non-dict response body"
    raw = payload.get("ReturnValue") or []
    paths = []
    for entry in raw:
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict):
            p = entry.get("Path") or entry.get("ObjectPath") or entry.get("ObjectName")
            if p: paths.append(p)
    return paths, None


async def _get_all_level_actors(verbose=False, timeout=2.0):
    """Pull every actor object path in the active level. UE Remote Control has
    no dedicated level-enumeration route, so we call GetAllLevelActors via
    /remote/object/call. Tries the modern EditorActorSubsystem first
    (UE 5.5+), falls back to legacy EditorLevelLibrary (UE 5.0-5.4). Cached
    for 2s so paired discover calls share a single round-trip."""
    import time
    now = time.time()
    if now < _actor_cache["expires_at"] and _actor_cache["paths"]:
        if verbose:
            print(f"  GetAllLevelActors: cache hit ({len(_actor_cache['paths'])} actors)")
        return _actor_cache["paths"]

    candidates = [
        "/Script/UnrealEd.Default__EditorActorSubsystem",
        "/Engine/Transient.UnrealEdEngine_0:EditorActorSubsystem_0",
        "/Script/EditorScriptingUtilities.Default__EditorLevelLibrary",
    ]

    paths = []
    last_err = None
    for cand in candidates:
        attempt, err = await _try_get_all_level_actors(cand, verbose=verbose, timeout=timeout)
        if attempt:
            paths = attempt
            if verbose:
                short = cand.rsplit(".", 1)[-1]
                print(f"  GetAllLevelActors via {short}: {len(paths)} actor(s) in level")
            break
        else:
            last_err = err
            if verbose:
                short = cand.rsplit(".", 1)[-1]
                print(f"  GetAllLevelActors via {short}: {err}")

    if not paths and verbose and last_err:
        print(f"  GetAllLevelActors: all candidates failed (last error: {last_err})")

    _actor_cache["paths"] = paths
    _actor_cache["expires_at"] = now + 2.0
    return paths


def _matches_class(actor_path, class_name):
    """Heuristic class match by actor name — UE actor paths embed the class
    in the actor's name (e.g. CineCameraActor_3). For auto-mapping we only
    care about CineCameraActor and CameraRig_Crane and both have unique
    distinguishing strings in their names, so a substring match is reliable.

    A stricter match would require a per-actor /remote/object/describe round
    trip which would be 10x more network traffic for no real benefit."""
    if not actor_path:
        return False
    # Pull the actor name (last segment after the final '.')
    name = actor_path.rsplit(".", 1)[-1]
    # CineCameraActor vs CineCameraActor_2 vs CineCameraActor3 etc.
    return class_name in name


async def discover_actors_by_class(class_path, verbose=False, timeout=2.0):
    """Discover all actors of a given class in the active level. Returns a
    list of actor object paths.

    Uses /remote/object/call → EditorLevelLibrary.GetAllLevelActors (works
    on every UE 5.x) and filters by class name on the bridge side. The full
    actor list is cached for 2s so paired discover calls (one for cameras,
    one for cranes during auto_scan_level) share a single UE round-trip.

    class_path can be either a full UE class path like
    '/Script/CinematicCamera.CineCameraActor' (we extract the short class
    name) or just the short name like 'CineCameraActor'."""
    all_paths = await _get_all_level_actors(verbose=verbose, timeout=timeout)
    # Extract the short class name from a full path if needed.
    class_name = class_path.rsplit(".", 1)[-1]
    matches = [p for p in all_paths if _matches_class(p, class_name)]
    if verbose:
        print(f"  class '{class_name}': {len(matches)} of {len(all_paths)} actor(s)")
    return matches


def _reset_actor_cache():
    """Forces the next discovery to re-query UE. Called when the user clicks
    Scan UE so they always see the latest level state."""
    _actor_cache["expires_at"] = 0.0
    _actor_cache["paths"] = []


def _name_from_path(actor_path):
    """Pull the actor's name out of a full UE object path. Path looks like
    '/Game/Maps/Main.Main:PersistentLevel.CineCameraActor_1' — the part after
    the last '.' is the actor name."""
    if "PersistentLevel." in actor_path:
        after = actor_path.split("PersistentLevel.", 1)[1]
        return after.split(".", 1)[0]
    return actor_path.rsplit(".", 1)[-1]


async def list_cameras(preset="RexyControl", verbose=False, timeout=1.5):
    """Discover CineCameras in the active level. Tries actor-search first (no
    per-project preset required) and falls back to preset-based discovery for
    backwards compatibility with users who still keep a RexyControl preset.
    Returns [{path, name}]."""
    # Path 1: actor-search. Works on any UE 5.x with Remote Control enabled,
    # no exposure required. This is the auto-mapping happy path.
    actor_paths = await discover_actors_by_class(
        "/Script/CinematicCamera.CineCameraActor",
        verbose=verbose, timeout=timeout)
    via_search = bool(actor_paths)
    cams = {p: _name_from_path(p) for p in actor_paths}

    # Path 2: fall back to preset-based discovery if search returned nothing.
    # Either UE is still booting, or the search endpoint isn't available on
    # this UE version, or there genuinely are no cameras in the level.
    fallback_resp = None
    if not cams:
        fallback_resp = await _request("GET", "/remote/preset/" + preset, {},
                                       timeout=timeout, verbose=verbose)
        try:
            body = fallback_resp.get("ResponseBody", fallback_resp) if isinstance(fallback_resp, dict) else {}
            for g in body.get("Preset", {}).get("Groups", []):
                for ep in g.get("ExposedProperties", []):
                    for owner in ep.get("OwnerObjects", []):
                        path = owner.get("Path", "")
                        if "CineCamera" in path and "PersistentLevel." in path:
                            head, after = path.split("PersistentLevel.", 1)
                            actor_name = after.split(".", 1)[0]
                            if "CineCamera" in actor_name:
                                cams[head + "PersistentLevel." + actor_name] = actor_name
        except Exception as e:
            if verbose:
                print(f"  list_cameras preset-fallback parse error — {e}")

    out = [{"path": p, "name": n} for p, n in cams.items()]

    # Discovery-state machine — drive the app's status UI.
    if not actor_paths and fallback_resp is None:
        # No reply from either path = UE not responding yet.
        if _discovery_state != "ready":
            set_discovery_state("waiting", camera_count=0)
    elif out:
        method = "actor-search" if via_search else "RexyControl preset"
        set_discovery_state("ready", camera_count=len(out),
                            note=f"Discovered via {method}.")
    else:
        # UE replied but found nothing — probably an empty level.
        set_discovery_state("waiting", camera_count=0,
                            note="UE responded but no CineCameraActors in the level yet.")

    if verbose or out:
        method = "search" if via_search else ("preset" if out else "none")
        print(f"  Cameras found ({method}): {[c['name'] for c in out]}")
    return out


async def list_cranes(verbose=False, timeout=1.5):
    """Discover CameraRig_Crane actors in the active level via actor-search.
    Returns [{path, name}]. Used by the auto-scan flow to show the user what
    grip rigs were found (cranes are auto-paired to cameras at set_camera()
    time via retarget_crane_for_camera; this is just for the scan summary)."""
    paths = await discover_actors_by_class(
        "/Script/CinematicCamera.CameraRig_Crane",
        verbose=verbose, timeout=timeout)
    out = [{"path": p, "name": _name_from_path(p)} for p in paths]
    if verbose or out:
        print(f"  Cranes found: {[c['name'] for c in out]}")
    return out


async def auto_scan_level(verbose=False):
    """High-level scan called by the app's 'Scan UE' button. Finds all cameras
    and cranes via actor-search, walks each camera's attach chain to identify
    which crane (if any) it's mounted on, and returns a structured summary the
    app shows in its confirmation panel before applying.

    Returns: {
      'cameras': [{'path', 'name', 'crane_path' or None, 'crane_name' or None}],
      'cranes':  [{'path', 'name'}],
      'method':  'search' | 'preset' | 'none',
    }"""
    cams = await list_cameras(verbose=verbose)
    cranes = await list_cranes(verbose=verbose)
    method = "search" if cams else "none"

    # Pair cameras to cranes by walking each camera's attach chain. Re-uses
    # the existing _find_parent_crane() helper.
    enriched = []
    for c in cams:
        crane_path = None
        crane_name = None
        try:
            crane_path = await _find_parent_crane(c["path"], verbose=verbose)
            if crane_path:
                crane_name = _name_from_path(crane_path)
        except Exception as e:
            if verbose:
                print(f"  auto_scan_level: attach-walk failed for {c['name']} — {e}")
        enriched.append({
            "path": c["path"], "name": c["name"],
            "crane_path": crane_path, "crane_name": crane_name,
        })

    return {"cameras": enriched, "cranes": cranes, "method": method}


def set_camera(actor_path):
    """Re-target the head + lens controls to the chosen camera (no view change).
    pan/tilt/roll -> <actor>.SceneComponent ; zoom/aperture/focus -> <actor>.CameraComponent.
    NOTE: this is the sync 'head + lens' pass only. The async retarget_crane_for_camera()
    handles the grip side (crane yaw/pitch/scope + base X/Y/Z) — call it right after."""
    scene = actor_path + ".SceneComponent"
    cam = actor_path + ".CameraComponent"
    for p in ("/rexy/pan", "/rexy/tilt", "/rexy/roll"):
        if p in _mappings:
            _mappings[p]["objectPath"] = scene
    for p in ("/rexy/zoom", "/rexy/aperture", "/rexy/focus"):
        if p in _mappings:
            _mappings[p]["objectPath"] = cam
    # keep the saved crane-mode grip targets' camera reference fresh too
    _struct_cache.clear()
    print(f"  Active camera: {actor_path.rsplit('.', 1)[-1]}")


async def _find_parent_crane(actor_path, verbose=False):
    """Walk the camera's attach chain upward looking for a CameraRig_Crane.
    Returns the crane actor's path (no component suffix), or None if not on a crane."""
    current = actor_path + ".SceneComponent"
    for _ in range(6):                              # safety bound on the walk
        try:
            resp = await call_function(current, "GetAttachParent", {}, verbose=False)
            body = resp.get("ResponseBody", {}) if isinstance(resp, dict) else {}
            rv = body.get("ReturnValue") or body.get("returnValue")
            if not rv:
                return None
            rv = str(rv)
            if "CameraRig_Crane" in rv and "PersistentLevel." in rv:
                head, after = rv.split("PersistentLevel.", 1)
                actor_name = after.split(".", 1)[0]
                return head + "PersistentLevel." + actor_name
            current = rv                            # keep walking up
        except Exception:
            return None
    return None


async def retarget_crane_for_camera(actor_path, verbose=False):
    """Find the camera's parent crane and re-target the grip + base mappings
    (craneYaw/cranePitch/scope/baseX/Y/Z) to it. If the camera isn't on a crane,
    leave the existing crane mappings untouched. Returns the crane path (or None)."""
    crane_actor = await _find_parent_crane(actor_path, verbose=verbose)
    if not crane_actor:
        if verbose:
            print(f"  retarget_crane: {actor_path.rsplit('.', 1)[-1]} is not on a crane")
        return None
    crane_xform = crane_actor + ".TransformComponent"
    # Crane yaw/pitch/scope go straight to the crane actor (own properties)
    for p in ("/rexy/craneYaw", "/rexy/cranePitch", "/rexy/scope"):
        if p in _mappings:
            _mappings[p]["objectPath"] = crane_actor
        if p in _grip_crane_targets:
            _grip_crane_targets[p]["objectPath"] = crane_actor
    # Base X/Y/Z go to the crane's TransformComponent
    for p in ("/rexy/baseX", "/rexy/baseY", "/rexy/baseZ"):
        if p in _mappings:
            _mappings[p]["objectPath"] = crane_xform
    _struct_cache.clear()
    print(f"  Re-targeted grip + base to crane: {crane_actor.rsplit('.', 1)[-1]}")
    return crane_actor


# ---------------------------------------------------------------------------
# Position readout + manual override + panic stop
# ---------------------------------------------------------------------------

async def get_locations(verbose=False):
    """Read live state for the GUI's 'Live' readouts: camera RelativeLocation +
    RelativeRotation, and crane TransformComponent RelativeLocation.
    Returns {camera:{X,Y,Z}, camera_rot:{Pitch,Yaw,Roll}, crane:{X,Y,Z}}.
    Missing keys if any read fails."""
    out = {}
    cam = _mappings.get("/rexy/pan", {}).get("objectPath")     # camera SceneComponent
    if cam:
        v = await read_property(cam, "RelativeLocation", verbose=False)
        if isinstance(v, dict):
            out["camera"] = {k: float(v.get(k, 0.0)) for k in ("X", "Y", "Z")}
        r = await read_property(cam, "RelativeRotation", verbose=False)
        if isinstance(r, dict):
            out["camera_rot"] = {k: float(r.get(k, 0.0)) for k in ("Pitch", "Yaw", "Roll")}
    crane = _mappings.get("/rexy/baseX", {}).get("objectPath")  # crane TransformComponent
    if crane:
        v = await read_property(crane, "RelativeLocation", verbose=False)
        if isinstance(v, dict):
            out["crane"] = {k: float(v.get(k, 0.0)) for k in ("X", "Y", "Z")}
    return out


async def set_location(target, x, y, z, verbose=False):
    """Write RelativeLocation on 'camera' (drone target) or 'crane' (base target).
    Also halts the matching velocity state — otherwise the velocity tick would
    immediately undo the manual set."""
    global _drone_state, _base_state
    if target == "camera":
        obj = _mappings.get("/rexy/pan", {}).get("objectPath")
        _drone_state.update({"X": 0.5, "Y": 0.5, "Z": 0.5})
    elif target == "crane":
        obj = _mappings.get("/rexy/baseX", {}).get("objectPath")
        _base_state.update({"X": 0.5, "Y": 0.5, "Z": 0.5})
    else:
        return None
    if not obj:
        return None
    body = {"objectPath": obj, "access": _config["access"],
            "propertyName": "RelativeLocation",
            "propertyValue": {"RelativeLocation": {"X": float(x), "Y": float(y), "Z": float(z)}}}
    await _request("PUT", "/remote/object/property", body, verbose=verbose)
    _struct_cache.pop((obj, "RelativeLocation"), None)
    print(f"  Set {target} location → X={float(x):+.1f}  Y={float(y):+.1f}  Z={float(z):+.1f}")
    return True


async def panic_stop(verbose=False):
    """EMERGENCY STOP. Cancels velocity tasks (drone + base), resets velocity
    states to centre, and forces grip mode back to Crane. Use when the camera
    runs away — Rob lost a drone camera once, this is the kill switch."""
    global _drone_task, _base_task, _grip_mode
    _drone_state.update({"X": 0.5, "Y": 0.5, "Z": 0.5})
    _base_state.update({"X": 0.5, "Y": 0.5, "Z": 0.5})
    if _drone_task and not _drone_task.done():
        _drone_task.cancel()
    if _base_task and not _base_task.done():
        _base_task.cancel()
    _drone_task = None
    _base_task = None
    if _grip_mode == "drone":
        _grip_mode = "crane"
    print("  ⚠ PANIC STOP — velocity tasks halted, states reset, grip mode → CRANE")


# ---------------------------------------------------------------------------
# Sending — thread-safe entry points
# ---------------------------------------------------------------------------

def submit_osc(path, value):
    """THREAD-SAFE, SYNC. Call this from the pygame main thread (or anywhere)
    to route an OSC value to UE Remote Control. No-op if the bridge loop isn't
    up yet or there's no mapping for `path`.

    >>> WIRING: in rexy_osc.py's main loop, right after send_osc(...), add:
            if ue5_rc:
                ue5_rc.submit_osc(path, out)
        That makes the wheels drive UE live in the editor while still sending
        plain UDP OSC (so a Play-mode Blueprint receiver also keeps working).
    """
    if _loop is None or path not in _mappings:
        return
    try:
        _loop.call_soon_threadsafe(_enqueue, path, value)
    except Exception:
        pass


def _enqueue(path, value):
    """Runs on the bridge loop. Builds the message and queues it."""
    if _send_queue is None:
        return
    m = _mappings.get(path)
    if not m:
        return
    try:
        msg = _build_message(m, _scale(value, m))
        _send_queue.put_nowait(msg)
    except Exception:
        pass


# Per-mapping write throttling. Some properties (CameraRig_Crane axes) cause UE
# to rebuild editor preview meshes on every change; streaming them at 30+Hz keeps
# the meshes in a perpetual mid-rebuild state, so they look invisible during motion.
# Buffer the latest value per path and drain at the configured rate. Latest write wins.
_throttle_buffer = {}        # osc_path -> latest float value
_throttle_drain_task = None  # single drain task, lazy-started


async def _throttle_drain_loop():
    """Drain the throttled-write buffer. Each path emits its most recent value
    at the configured rate (defaults to 10Hz / 100ms). Runs forever once started."""
    DRAIN_TICK = 0.10                   # 10Hz — matches the typical write_throttle_ms
    while True:
        await asyncio.sleep(DRAIN_TICK)
        if not _throttle_buffer:
            continue
        items = list(_throttle_buffer.items())
        _throttle_buffer.clear()
        for path, value in items:
            m = _mappings.get(path)
            if not m:
                continue
            try:
                msg = _build_message(m, _scale(value, m))
                if _send_queue is not None:
                    _send_queue.put_nowait(msg)
            except Exception:
                pass


# DEBOUNCED RerunConstructionScripts on the crane actor — hypothesis probe for
# "crane goes invisible when moved via the app". Editor details-panel writes
# trigger OnConstruction; RC writes don't, so the rig's visual representation can
# desync. Calling RerunConstructionScripts at high rate caused the crane to flicker
# (rebuild-mid-write), so we now debounce: rerun fires 300ms AFTER the user stops
# moving. Gated by mappings.json "ue5.crane_rerun_construction" (default off) so
# Rob can A/B test without restarting; on=verbose log when it fires.
_RERUN_DEBOUNCE_S = 0.30
_rerun_pending = {}                       # actor_path -> asyncio.Task

async def _maybe_rerun_construction(actor_path, verbose=False):
    if not _config.get("crane_rerun_construction", False):
        return
    # Cancel any pending rerun for this actor — debounce restart
    task = _rerun_pending.pop(actor_path, None)
    if task and not task.done():
        task.cancel()

    async def _delayed():
        try:
            await asyncio.sleep(_RERUN_DEBOUNCE_S)
            print(f"  Crane rerun: RerunConstructionScripts on {actor_path.rsplit('.', 1)[-1]}")
            await call_function(actor_path, "RerunConstructionScripts", {}, verbose=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if verbose:
                print(f"  Crane rerun: error — {e}")
        finally:
            _rerun_pending.pop(actor_path, None)

    _rerun_pending[actor_path] = asyncio.ensure_future(_delayed())


async def apply_osc_to_ue5(path, value, verbose=False):
    """ASYNC. Called by rexy_osc.py's WS handler for explicit osc_send messages."""

    # CONTINUOUS WHEELS intercept: pan/tilt/roll feed the velocity tick loop
    # (camera-local AddLocalRotation) instead of writing the absolute rotation.
    if _wheel_mode == "continuous" and path in ("/rexy/pan", "/rexy/tilt", "/rexy/roll"):
        _wheel_state[path.rsplit("/", 1)[-1]] = float(value)
        return False

    # DRONE intercept: in drone mode the 3 grip axes feed the velocity
    # tick loop (camera-local AddLocalOffset) instead of writing a property.
    if _grip_mode == "drone":
        AXIS = {"/rexy/craneYaw": "X", "/rexy/scope": "Y", "/rexy/cranePitch": "Z"}
        if path in AXIS:
            _drone_state[AXIS[path]] = float(value)
            return False

    # BASE intercept (always): X/Y/Z slider feeds the world-translate velocity
    # loop on the crane TransformComponent. Lazy-start the tick on first use.
    BASE_AXIS = {"/rexy/baseX": "X", "/rexy/baseY": "Y", "/rexy/baseZ": "Z"}
    if path in BASE_AXIS:
        _base_state[BASE_AXIS[path]] = float(value)
        global _base_task
        if _base_task is None or _base_task.done():
            _base_task = asyncio.ensure_future(_base_tick(verbose))
        return False

    m = _mappings.get(path)
    if not m:
        return False
    # Throttled paths: buffer the latest value; the drain loop emits at the
    # configured rate. Latest write wins. Fixes the crane visibility issue
    # (30Hz writes were keeping its editor preview meshes in mid-rebuild).
    if m.get("write_throttle_ms"):
        _throttle_buffer[path] = float(value)
        global _throttle_drain_task
        if _throttle_drain_task is None or _throttle_drain_task.done():
            _throttle_drain_task = asyncio.ensure_future(_throttle_drain_loop())
        if verbose:
            print(f"  RC ~> {m.get('label', path)}  (throttled {m['write_throttle_ms']}ms)")
        return False
    try:
        msg = _build_message(m, _scale(value, m))
        if _send_queue is not None:
            _send_queue.put_nowait(msg)
            if verbose:
                print(f"  RC -> {m.get('label', path)}  ({path})")
    except Exception as e:
        if verbose:
            print(f"  RC bridge: apply error — {e}")
        return False
    return bool(_config.get("suppress_udp_when_handled", False)) and _connected


# ---------------------------------------------------------------------------
# Connection loop — runs on the WS thread's asyncio loop (added to gather())
# ---------------------------------------------------------------------------

async def listener_loop(broadcast, ue5_host=None, verbose=False):
    """Maintain the WebSocket connection to UE Remote Control with quiet
    reconnect/backoff. `broadcast` is rexy_osc.py's state.broadcast — used to
    tell the app about RC connection status. NEVER raises."""
    global _loop, _send_queue, _connected

    if websockets is None:
        print("  RC bridge: 'websockets' not installed — bridge disabled.")
        return

    _loop = asyncio.get_event_loop()
    _send_queue = asyncio.Queue()
    host = ue5_host or _config["host"]
    port = _config["ws_port"]
    url = f"ws://{host}:{port}"

    # If there are no mappings, idle forever (do nothing, harmlessly).
    if not _mappings:
        print("  RC bridge: idle (no mappings).")
        while True:
            await asyncio.sleep(3600)

    while True:
        try:
            if verbose:
                print(f"  RC bridge: connecting to {url} ...")
            async with websockets.connect(url, max_size=None) as ws:
                _connected = True
                print(f"  RC bridge: connected to UE Remote Control at {url}")
                try:
                    broadcast({"type": "rc_status", "connected": True, "url": url})
                except Exception:
                    pass

                sender = asyncio.ensure_future(_sender(ws, verbose))
                receiver = asyncio.ensure_future(_receiver(ws, broadcast, verbose))
                done, pending = await asyncio.wait(
                    [sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
        except Exception as e:
            if verbose:
                print(f"  RC bridge: connection failed/closed — {e}")
        finally:
            _connected = False
            try:
                broadcast({"type": "rc_status", "connected": False, "url": url})
            except Exception:
                pass
        await asyncio.sleep(float(_config.get("reconnect_seconds", 3.0)))


async def _sender(ws, verbose):
    """Drain the send queue to the websocket. Coalesces is unnecessary here;
    UE handles the stream. Exits (and triggers a reconnect) if the socket dies."""
    while True:
        msg = await _send_queue.get()
        await ws.send(msg)


async def _receiver(ws, broadcast, verbose):
    """Read inbound messages (e.g. PresetFieldsChanged) for optional
    bidirectional sync. For now we just surface them to the app via broadcast.
    CONFIRM: message shapes once we have a live preset to watch."""
    async for raw in ws:
        try:
            data = json.loads(raw)
        except Exception:
            continue

        # Resolve awaited request/response calls (read/call/describe) first, so
        # the awaiting caller gets the reply (including error responses) rather
        # than it being swallowed by the write-error logging below.
        rid = data.get("RequestId")
        if rid is not None and rid in _pending:
            fut = _pending.pop(rid)
            if not fut.done():
                fut.set_result(data)
            continue

        # Surface failed property writes so a bad objectPath / propertyName is
        # obvious instead of silently doing nothing (printed always, not just
        # in verbose — this is the #1 gotcha when adding new mappings).
        code = data.get("ResponseCode", data.get("StatusCode"))
        try:
            code = int(code) if code is not None else None
        except (TypeError, ValueError):
            code = None
        if code is not None and code >= 400:
            print(f"  RC ERROR {code} (RequestId {data.get('RequestId')}) — "
                  f"check objectPath/propertyName in mappings.json: {str(data)[:200]}")
            continue

        mtype = data.get("Type") or data.get("type")
        if mtype == "PresetFieldsChanged":
            try:
                broadcast({"type": "rc_fields_changed", "data": data})
            except Exception:
                pass
        elif verbose:
            print(f"  RC <- {str(data)[:120]}")


# ---------------------------------------------------------------------------
# Standalone smoke test:  python ue5_rc_listener.py /rexy/pan 0.75
# (Requires UE running with Remote Control + a matching mappings.json here.)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    load_mappings(here)

    test_path = sys.argv[1] if len(sys.argv) > 1 else "/rexy/pan"
    test_val = float(sys.argv[2]) if len(sys.argv) > 2 else 0.75

    async def _demo():
        broadcast = lambda d: None
        loop_task = asyncio.ensure_future(listener_loop(broadcast, verbose=True))
        await asyncio.sleep(1.5)                 # give it a moment to connect
        for _ in range(20):                      # stream the test value briefly
            await apply_osc_to_ue5(test_path, test_val, verbose=True)
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)
        loop_task.cancel()

    try:
        asyncio.run(_demo())
    except KeyboardInterrupt:
        pass
