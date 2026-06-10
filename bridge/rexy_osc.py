#!/usr/bin/env python3
"""
Rexy Wheels -> OSC  (standalone + control panel server)
=======================================================
- Reads the Rexy Wheels gamepad directly (no browser focus needed)
- Sends OSC directly to UE5 via UDP
- Hosts a WebSocket server so the iPad control panel can update
  speed, deadzone, and invert in real time

Requirements:
    pip3 install pygame python-osc websockets --break-system-packages

Usage:
    python3.12 rexy_osc.py
    python3.12 rexy_osc.py --osc-host 192.168.1.100 --verbose
"""

import argparse
import asyncio
import json
import os
import sys
import time
import signal
import threading

try:
    import pygame
except ImportError:
    print("ERROR: pygame not found. Run: python3.12 -m pip install pygame python-osc websockets --break-system-packages")
    sys.exit(1)

try:
    from pythonosc import udp_client
    from pythonosc.osc_message_builder import OscMessageBuilder
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import AsyncIOOSCUDPServer
except ImportError:
    print("ERROR: python-osc not found. Run: python3.12 -m pip install pygame python-osc websockets --break-system-packages")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("ERROR: websockets not found. Run: python3.12 -m pip install pygame python-osc websockets --break-system-packages")
    sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(description="Rexy Wheels -> OSC with iPad control panel")
    p.add_argument("--osc-host",  default="127.0.0.1", help="OSC target IP (default: 127.0.0.1)")
    p.add_argument("--osc-port",  default=8000, type=int, help="OSC target port (default: 8000)")
    p.add_argument("--base-path", default="/rexy", help="OSC base path (default: /rexy)")
    p.add_argument("--pan-axis",  default=3, type=int, help="Gamepad axis for pan (default: 3)")
    p.add_argument("--tilt-axis", default=4, type=int, help="Gamepad axis for tilt (default: 4)")
    p.add_argument("--joystick-name", default=None,
                   help="Prefer a joystick whose name contains this substring (case-insensitive). "
                        "Use to pin selection when multiple joysticks are present.")
    p.add_argument("--skip-joystick", default="vjoy",
                   help="Skip joysticks whose name contains this substring (case-insensitive). "
                        "Default: 'vjoy' to avoid the vJoy virtual driver on Windows. "
                        "Pass an empty string to disable.")
    p.add_argument("--ws-port",   default=9000, type=int, help="WebSocket control panel port (default: 9000)")
    p.add_argument("--hz",        default=120, type=int, help="Poll rate in Hz (default: 120)")
    p.add_argument("--osc-return-port", default=8001, type=int, help="UDP port to listen for OSC feedback from UE5 (default: 8001)")
    p.add_argument("--verbose", "-v", action="store_true", help="Print every OSC message")
    p.add_argument("--auto-pan-tilt", action="store_true",
                   help="LEGACY: auto-drive /rexy/pan and /rexy/tilt from the selected joystick's "
                        "--pan-axis / --tilt-axis. OFF by default — bind wheels in the app's Bind UI "
                        "instead, which uses the browser Gamepad API and supports multiple devices.")
    p.add_argument("--ue-startup-grace", default=10.0, type=float,
                   help="Seconds the bridge will quietly wait for UE to finish loading the project "
                        "before declaring RC offline to the app. Reduces 'red dot' panic during a "
                        "fresh editor launch. (default: 10.0)")
    return p.parse_args()


# Previz companion app forward — set _COMPANION_PORT = None to disable
_COMPANION_HOST = "127.0.0.1"
_COMPANION_PORT = 8765

def send_osc(client, osc_host, osc_port, path, value, verbose):
    builder = OscMessageBuilder(address=path)
    builder.add_arg(float(value), arg_type='f')
    msg = builder.build()
    client._sock.sendto(msg.dgram, (osc_host, osc_port))
    if _COMPANION_PORT:
        try:
            client._sock.sendto(msg.dgram, (_COMPANION_HOST, _COMPANION_PORT))
        except Exception:
            pass
    if verbose:
        print(f"  {path}  {value:.4f}")


# ---------------------------------------------------------------------------
# Shared mutable state (main thread writes, WS thread reads)
# ---------------------------------------------------------------------------
# Use a simple dict + threading.Lock rather than asyncio primitives so there
# are no event-loop ownership issues across threads.

class SharedState:
    def __init__(self, args):
        self.lock       = threading.Lock()
        self.controls   = {
            "pan":  {"deadzone": 0.02, "speed": 1.0, "invert": False, "span": 720.0, "held": False},
            "tilt": {"deadzone": 0.02, "speed": 1.0, "invert": False, "span": 180.0, "held": False},
        }
        self.osc = {
            "host":      args.osc_host,
            "port":      args.osc_port,
            "base_path": args.base_path,
        }
        self.device_name = "No device"
        self.osc_client  = udp_client.SimpleUDPClient(args.osc_host, args.osc_port)
        self.osc_key     = (args.osc_host, args.osc_port)

        # Thread-safe message queue: main thread puts, WS broadcaster gets
        # Created here; the asyncio loop will use it after it starts.
        self.accumulated = {"pan": 0.5, "tilt": 0.5}  # shared with WS thread for reset
        self._broadcast_queue = None   # set by WS thread once loop exists

    def set_broadcast_queue(self, q):
        with self.lock:
            self._broadcast_queue = q

    def broadcast(self, msg_dict):
        """Called from any thread — puts a message onto the async queue."""
        with self.lock:
            q = self._broadcast_queue
        if q is not None:
            # loop.call_soon_threadsafe is safe from any thread
            loop.call_soon_threadsafe(q.put_nowait, json.dumps(msg_dict))


# Global so pygame main loop and ws_thread can both reach it
loop   = None   # set in main() before thread starts
state  = None   # set in main()
ue5_rc = None   # set in _ws_server() once ue5_rc_listener.py loads; read by main()


# ---------------------------------------------------------------------------
# WebSocket server (runs in background thread)
# ---------------------------------------------------------------------------

def ws_thread_main(args):
    global loop
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_ws_server(args))


async def _ws_server(args):
    global ue5_rc
    connections = set()

    # Create queue inside the running loop so it's owned by this loop
    q = asyncio.Queue()
    state.set_broadcast_queue(q)

    async def broadcast_state_to_others(exclude):
        """Send full current state to all clients except the one that triggered the change."""
        with state.lock:
            snap = {"type": "state", "controls": state.controls, "device_name": state.device_name}
        msg = json.dumps(snap)
        dead = set()
        for conn in list(connections):
            if conn is exclude:
                continue
            try:
                await conn.send(msg)
            except Exception:
                dead.add(conn)
        connections.difference_update(dead)

    async def handle(websocket):
        connections.add(websocket)
        print(f"  Control panel connected from {websocket.remote_address[0]}")
        try:
            # Send current state on connect
            with state.lock:
                snap = {
                    "type":        "state",
                    "controls":    state.controls,
                    "device_name": state.device_name,
                }
            await websocket.send(json.dumps(snap))
            # Send current discovery state so the UI shows "waiting…" / "ready"
            # immediately on connect instead of silent until next probe.
            if ue5_rc:
                await websocket.send(json.dumps({"type": "discovery_status",
                                                 "state": ue5_rc.get_discovery_state(),
                                                 "cameras": ue5_rc._discovery_camera_count}))
            # Send discovered RC field names so app can populate picker
            if ue5_rc:
                fields_msg = json.dumps({"type": "rc_fields", "fields": ue5_rc.get_rc_fields()})
                await websocket.send(fields_msg)

            async for raw in websocket:
                try:
                    data      = json.loads(raw)
                    msg_type  = data.get("type")
                    wheel     = data.get("wheel")
                    param     = data.get("param")
                    value     = data.get("value")

                    if msg_type == "get_rc_fields":
                        # App is requesting the current field list
                        if ue5_rc:
                            fields = ue5_rc.get_rc_fields()
                            await websocket.send(json.dumps({"type": "rc_fields", "fields": fields}))

                    elif msg_type == "osc_send":
                        path = data.get("path")
                        if path and value is not None:
                            async def _send(p, v):
                                handled = False
                                if ue5_rc:
                                    handled = await ue5_rc.apply_osc_to_ue5(p, float(v), args.verbose)
                                if not handled:
                                    with state.lock:
                                        client   = state.osc_client
                                        osc_host = state.osc["host"]
                                        osc_port = state.osc["port"]
                                    send_osc(client, osc_host, osc_port, p, float(v), args.verbose)
                            asyncio.ensure_future(_send(path, value))

                    elif msg_type == "lens_preset":
                        name = data.get("name")
                        if name and ue5_rc:
                            asyncio.ensure_future(ue5_rc.apply_lens_preset(name, args.verbose))

                    elif msg_type == "custom_lens":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.apply_custom_lens(
                                data.get("name", "custom"),
                                data.get("min_focal"), data.get("max_focal"),
                                data.get("min_aperture"), data.get("max_aperture"),
                                data.get("min_focus"),
                                max_focus=data.get("max_focus", 100000),
                                verbose=args.verbose))

                    elif msg_type == "filmback_preset":
                        name = data.get("name")
                        if name and ue5_rc:
                            asyncio.ensure_future(ue5_rc.apply_filmback_preset(name, args.verbose))

                    elif msg_type == "grip_mode":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.set_grip_mode(data.get("mode"), args.verbose))

                    elif msg_type == "wheel_mode":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.set_wheel_mode(data.get("mode"), args.verbose))

                    elif msg_type == "list_cameras":
                        if ue5_rc:
                            async def _lc(ws):
                                cams = await ue5_rc.list_cameras(verbose=args.verbose)
                                try: await ws.send(json.dumps({"type": "cameras", "cameras": cams}))
                                except Exception: pass
                            asyncio.ensure_future(_lc(websocket))

                    elif msg_type == "auto_scan":
                        # User clicked "Scan UE" — discover cameras + cranes via
                        # actor-search, pair cameras to their parent cranes, and
                        # send a structured summary back to the app for confirmation.
                        if ue5_rc:
                            async def _scan(ws):
                                result = await ue5_rc.auto_scan_level(verbose=args.verbose)
                                try: await ws.send(json.dumps({"type": "auto_scan_result",
                                                               "result": result}))
                                except Exception: pass
                            asyncio.ensure_future(_scan(websocket))

                    elif msg_type == "apply_scan":
                        # User confirmed the scan and (optionally) wants it saved
                        # to mappings.json so the next bridge launch starts pre-mapped.
                        save_to_disk = bool(data.get("save", False))
                        if ue5_rc:
                            async def _apply(ws):
                                saved_path = None
                                if save_to_disk:
                                    try:
                                        saved_path = ue5_rc.save_mappings_with_backup(
                                            os.path.dirname(os.path.abspath(__file__)))
                                    except Exception as e:
                                        print(f"  apply_scan: save failed — {e}")
                                # Refresh the camera list so the app's picker repaints.
                                cams = await ue5_rc.list_cameras(verbose=args.verbose)
                                try: await ws.send(json.dumps({"type": "apply_scan_result",
                                                               "saved": bool(saved_path),
                                                               "savedPath": saved_path,
                                                               "cameras": cams}))
                                except Exception: pass
                            asyncio.ensure_future(_apply(websocket))

                    elif msg_type == "set_camera":
                        p = data.get("path")
                        if ue5_rc and p:
                            ue5_rc.set_camera(p)
                            async def _post(ws, path):
                                # Re-target crane + base mappings to the camera's parent rig
                                # BEFORE auto-calibrate, so calibration reads the right crane.
                                await ue5_rc.retarget_crane_for_camera(path, args.verbose)
                                await ue5_rc.auto_calibrate_camera(args.verbose)
                                on_c = await ue5_rc.is_camera_on_crane(path, args.verbose)
                                try: await ws.send(json.dumps({"type": "camera_active",
                                                               "path": path, "on_crane": on_c}))
                                except Exception: pass
                            asyncio.ensure_future(_post(websocket, p))

                    elif msg_type == "get_locations":
                        if ue5_rc:
                            async def _gl(ws):
                                locs = await ue5_rc.get_locations(args.verbose)
                                try: await ws.send(json.dumps({"type": "locations", **locs}))
                                except Exception: pass
                            asyncio.ensure_future(_gl(websocket))

                    elif msg_type == "set_location":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.set_location(
                                data.get("target"), data.get("x", 0.0),
                                data.get("y", 0.0), data.get("z", 0.0), args.verbose))

                    elif msg_type == "panic_stop":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.panic_stop(args.verbose))

                    elif msg_type == "calibrate":
                        p = data.get("path")
                        if ue5_rc and p:
                            asyncio.ensure_future(ue5_rc.calibrate_param(p, args.verbose))

                    elif msg_type == "clear_offset":
                        p = data.get("path")
                        if ue5_rc and p:
                            ue5_rc.clear_offset(p)

                    elif msg_type == "force_write":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.force_write(
                                data.get("path"), data.get("value")))

                    elif msg_type == "force_write_value":
                        if ue5_rc:
                            asyncio.ensure_future(ue5_rc.force_write_value(
                                data.get("path"), data.get("value")))

                    elif msg_type == "tuning":
                        if ue5_rc:
                            ue5_rc.set_tuning(sensitivity=data.get("sensitivity"),
                                              deadband=data.get("deadband"))

                    elif msg_type == "tuning_param":
                        if ue5_rc:
                            ue5_rc.set_param_tuning(data.get("path"),
                                                    sensitivity=data.get("sensitivity"),
                                                    deadband=data.get("deadband"))

                    elif msg_type == "param_range":
                        if ue5_rc:
                            ue5_rc.set_param_range(data.get("path"),
                                                   out_min=data.get("out_min"),
                                                   out_max=data.get("out_max"))

                    elif wheel in ("pan", "tilt") and param is not None:
                        changed = False
                        with state.lock:
                            if param in state.controls[wheel]:
                                state.controls[wheel][param] = value
                                changed = True
                        if changed:
                            await broadcast_state_to_others(websocket)

                    elif wheel == "osc" and param in ("host", "port", "base_path"):
                        with state.lock:
                            state.osc[param] = value
                            new_key = (state.osc["host"], state.osc["port"])
                            if new_key != state.osc_key:
                                state.osc_client = udp_client.SimpleUDPClient(*new_key)
                                state.osc_key    = new_key
                        await broadcast_state_to_others(websocket)


                    elif msg_type == "companion_config":
                        # Update previz companion forwarding at runtime
                        global _COMPANION_HOST, _COMPANION_PORT
                        enabled = data.get("enabled", True)
                        _COMPANION_HOST = data.get("host", "127.0.0.1")
                        _COMPANION_PORT = int(data.get("port", 8765)) if enabled else None
                        if args.verbose:
                            print(f"  Companion: {'enabled' if _COMPANION_PORT else 'disabled'} → {_COMPANION_HOST}:{_COMPANION_PORT}")
                    elif msg_type == "set_value":
                        wh  = data.get("wheel")
                        val = data.get("value")
                        if wh in ("pan", "tilt") and val is not None:
                            val = max(0.0, min(1.0, float(val)))
                            with state.lock:
                                state.accumulated[wh] = val
                                osc_host  = state.osc["host"]
                                osc_port  = state.osc["port"]
                                base_path = state.osc["base_path"]
                                client    = state.osc_client
                            path = f"{base_path}/{wh}"
                            send_osc(client, osc_host, osc_port, path, val, args.verbose)
                            state.broadcast({"type": "osc", "wheel": wh, "path": path, "value": val})

                except Exception as e:
                    if args.verbose:
                        print(f"  WS parse error: {e}")

        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosedError:
            pass
        finally:
            connections.discard(websocket)
            print("  Control panel disconnected")

    async def broadcaster():
        while True:
            msg = await q.get()
            dead = set()
            for conn in list(connections):
                try:
                    await conn.send(msg)
                except Exception:
                    dead.add(conn)
            connections.difference_update(dead)

    # OSC return server — receives values broadcast back from UE5
    async def start_osc_return_server():
        def osc_return_handler(address, *osc_args):
            value = osc_args[0] if osc_args else 0.0
            if isinstance(value, (int, float)):
                msg = json.dumps({"type": "osc_value", "path": address, "value": float(value)})
                state.broadcast({"type": "osc_value", "path": address, "value": float(value)})
                if args.verbose:
                    print(f"  OSC return: {address} = {value}")

        dispatcher = Dispatcher()
        dispatcher.set_default_handler(osc_return_handler)
        server = AsyncIOOSCUDPServer(("0.0.0.0", args.osc_return_port), dispatcher, asyncio.get_event_loop())
        transport, protocol = await server.create_serve_endpoint()
        print(f"  OSC return listener on UDP port {args.osc_return_port}")
        return transport

    # UE5 Remote Control WebSocket listener (bidirectional sync)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ue5_rc_listener", os.path.join(script_dir, "ue5_rc_listener.py"))
        ue5_rc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ue5_rc)
        rc_mapping = ue5_rc.load_mappings(script_dir)
        # Wire the discovery-state machine so transitions push to the app's
        # status UI. state.broadcast() is thread-safe (uses call_soon_threadsafe).
        ue5_rc.register_discovery_broadcaster(state.broadcast)
        ue5_rc.set_discovery_state("waiting", camera_count=0,
                                   note=f"Bridge online. Waiting for UE (grace {args.ue_startup_grace:.0f}s).")
    except Exception as e:
        print(f"  UE5 RC: could not load ue5_rc_listener.py — {e}")
        ue5_rc     = None
        rc_mapping = {}

    print(f"  Control panel WebSocket on ws://0.0.0.0:{args.ws_port}")
    osc_transport = await start_osc_return_server()

    async def locations_broadcaster():
        """Every ~250ms, read camera + crane RelativeLocation and broadcast to the
        app so the position readouts stay live (independent of who is driving).
        4Hz is brisk enough to feel real-time when moving the camera, and the
        per-cycle cost (3 RC reads) is tiny compared to UE's RC capacity."""
        if not ue5_rc:
            return
        await asyncio.sleep(2.0)                            # let RC connect first
        while True:
            try:
                locs = await ue5_rc.get_locations(args.verbose)
                if locs:
                    state.broadcast({"type": "locations", **locs})
            except Exception:
                pass
            await asyncio.sleep(0.25)

    try:
        async with websockets.serve(handle, "0.0.0.0", args.ws_port):
            tasks = [asyncio.Future(), broadcaster()]
            if ue5_rc:
                tasks.append(ue5_rc.listener_loop(
                    state.broadcast,
                    ue5_host=args.osc_host, verbose=args.verbose))
                tasks.append(locations_broadcaster())
            await asyncio.gather(*tasks)
    finally:
        osc_transport.close()


# ---------------------------------------------------------------------------
# Joystick selection — skip virtual drivers (vJoy) and prefer Rexy Wheels
# ---------------------------------------------------------------------------

def select_joystick(args):
    """Pick a pygame joystick using user filters.

    Preference order:
      1. If --joystick-name is set, return the first device whose name contains it.
      2. Otherwise, return the first device whose name does NOT contain
         --skip-joystick (default: 'vjoy').
      3. If --skip-joystick is empty and no preferred match was found, fall
         back to device 0.
      4. If every detected device matched --skip-joystick, return (None, None)
         so the main loop keeps waiting instead of grabbing a filtered device.

    Returns (initialised_joystick, name) or (None, None).
    """
    count = pygame.joystick.get_count()
    if count == 0:
        return None, None

    devices = []
    for i in range(count):
        js = pygame.joystick.Joystick(i)
        devices.append((i, js.get_name()))

    preferred = (args.joystick_name or "").strip().lower()
    skip      = (args.skip_joystick or "").strip().lower()

    chosen_idx = None
    reason     = ""

    if preferred:
        for i, n in devices:
            if preferred in n.lower():
                chosen_idx = i
                reason = f"matches --joystick-name '{args.joystick_name}'"
                break

    if chosen_idx is None and skip:
        for i, n in devices:
            if skip not in n.lower():
                chosen_idx = i
                reason = f"first device not matching --skip-joystick '{args.skip_joystick}'"
                break

    if chosen_idx is None and not skip and not preferred:
        chosen_idx = 0
        reason     = "device 0 (no filters set)"

    if chosen_idx is None:
        print(f"  No suitable joystick — detected {len(devices)} device(s) but all were filtered out:")
        for i, n in devices:
            print(f"      [{i}] {n}")
        if preferred:
            print(f"  (looking for name containing '{args.joystick_name}')")
        if skip:
            print(f"  (skipping name containing '{args.skip_joystick}' — pass --skip-joystick '' to disable, or use --joystick-name to override)")
        return None, None

    js = pygame.joystick.Joystick(chosen_idx)
    js.init()
    chosen_name = js.get_name()

    print(f"  Joysticks detected: {len(devices)}")
    for i, n in devices:
        marker = ">" if i == chosen_idx else " "
        print(f"    {marker} [{i}] {n}")
    print(f"  Selected [{chosen_idx}] '{chosen_name}' ({reason})")

    return js, chosen_name


# ---------------------------------------------------------------------------
# Main — pygame runs on the main thread (required by macOS)
# ---------------------------------------------------------------------------

def main():
    global loop, state

    args  = parse_args()
    state = SharedState(args)

    print()
    print("  Rexy Wheels -> OSC")
    print("  " + "-" * 40)
    print(f"  OSC target    {args.osc_host}:{args.osc_port}")
    if getattr(args, "auto_pan_tilt", False):
        print(f"  Pan path      {args.base_path}/pan  (axis {args.pan_axis})  [LEGACY auto]")
        print(f"  Tilt path     {args.base_path}/tilt  (axis {args.tilt_axis})  [LEGACY auto]")
    else:
        print(f"  Auto pan/tilt OFF — bind wheels via the app's Bind UI")
        print(f"  (pass --auto-pan-tilt to re-enable hard-wired axis {args.pan_axis}/{args.tilt_axis})")
    print(f"  Poll rate     {args.hz} Hz")
    print("  " + "-" * 40)

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=ws_thread_main, args=(args,), daemon=True)
    t.start()

    pygame.init()
    pygame.joystick.init()

    joystick    = None
    # accumulated now lives in state so WS thread can reset it
    smoothed    = {"pan": 0.0, "tilt": 0.0}
    last_sent   = {"pan": None, "tilt": None}
    interval    = 1.0 / args.hz
    last_attempted_count = -1   # track device-topology changes to avoid log spam

    print("  Waiting for Rexy Wheels... (press any button on the device)")

    def handle_stop(*_):
        pygame.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT,  handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    while True:
        t_start = time.perf_counter()
        pygame.event.pump()

        count = pygame.joystick.get_count()

        if joystick is None and count > 0 and count != last_attempted_count:
            # Device topology changed — try to (re)select a joystick.
            joystick, name = select_joystick(args)
            last_attempted_count = count
            if joystick is not None:
                print(f"  Connected: {name}")
                with state.lock:
                    state.device_name = name
                state.broadcast({"type": "device_connected", "device_name": name})

        elif joystick is not None and count == 0:
            print("  Disconnected — waiting for reconnect...")
            joystick = None
            last_attempted_count = -1
            with state.lock:
                state.accumulated = {"pan": 0.5, "tilt": 0.5}
            smoothed = {"pan": 0.0, "tilt": 0.0}
            with state.lock:
                state.device_name = "No device"
            state.broadcast({"type": "device_disconnected"})

        if joystick is not None:
            num_axes = joystick.get_numaxes()

            with state.lock:
                controls_snap = {
                    "pan":  dict(state.controls["pan"]),
                    "tilt": dict(state.controls["tilt"]),
                }
                osc_host  = state.osc["host"]
                osc_port  = state.osc["port"]
                base_path = state.osc["base_path"]
                client    = state.osc_client

            # LEGACY auto pan/tilt path. OFF by default so the wheels appear as a
            # generic gamepad to the browser — the app's Bind UI can then map any
            # axis on any device to any parameter (multiple Rexy Wheels supported).
            # Pass --auto-pan-tilt to bring back the old hard-wired behaviour.
            _legacy_wheels = [
                ("pan",  args.pan_axis,  True),
                ("tilt", args.tilt_axis, False),
            ] if getattr(args, "auto_pan_tilt", False) else []

            for wheel_name, axis_idx, flip in _legacy_wheels:
                if axis_idx >= num_axes:
                    continue

                raw = joystick.get_axis(axis_idx)
                v   = raw if flip else -raw

                dz     = controls_snap[wheel_name]["deadzone"]
                speed  = controls_snap[wheel_name]["speed"]
                invert = controls_snap[wheel_name]["invert"]
                span   = controls_snap[wheel_name].get("span", 720.0)
                # Normalize speed by span so same speed = same degrees/sec regardless of RC range
                # OSC step is inversely proportional to span: smaller span = smaller OSC steps
                # Using 180 as reference (smallest typical span) so tilt is the baseline
                reference_span = 180.0
                speed_scaled = speed * (reference_span / max(1.0, span))

                if invert:
                    v = -v

                if abs(v) < dz:
                    v = 0.0
                elif dz > 0:
                    v = (v - (1 if v > 0 else -1) * dz) / (1 - dz)

                smoothed[wheel_name] = smoothed[wheel_name] * 0.6 + v * 0.4

                with state.lock:
                    state.accumulated[wheel_name] = max(0.0, min(1.0,
                        state.accumulated[wheel_name] + smoothed[wheel_name] * 0.002 * speed_scaled
                    ))
                    out = state.accumulated[wheel_name]

                # Skip OSC send if this wheel is held — value freezes at last sent
                if controls_snap[wheel_name].get("held", False):
                    last_sent[wheel_name] = out  # keep accumulator aligned
                    continue

                if last_sent[wheel_name] != out:
                    last_sent[wheel_name] = out
                    path = f"{base_path}/{wheel_name}"
                    send_osc(client, osc_host, osc_port, path, out, args.verbose)
                    if ue5_rc:                       # NEW: also drive UE Remote Control (editor-live)
                        ue5_rc.submit_osc(path, out)
                    state.broadcast({"type": "osc", "wheel": wheel_name, "path": path, "value": out})

        elapsed   = time.perf_counter() - t_start
        remaining = interval - elapsed
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
