# Changelog

All notable changes to Rexy Bridge will be documented here.

## [2.0.0-beta.1] — Virtual MoCo (beta)

First public beta of the v2 line. The bridge and hardware support are unchanged from 1.0; everything new is in the browser app under the new **Virtual MoCo** panel — a full record / playback system for every bound parameter, with editable curves and file-based take exchange.

> **Beta notes.** The MoCo data format is settled but still pre-1.0 — `.rxmove` files saved during the beta should round-trip cleanly through future beta drops. Please report any issues via GitHub Issues so we can stabilise before v2.0.0 final.

### Virtual MoCo — record / playback

- **Record / play / stop** the live state of every bound parameter at 60Hz into in-memory "takes".
- **Multi-take management** — create new takes, duplicate (deep clone), rename, delete, switch via dropdown.
- **Per-track P / R / E arming** — three-state per-row buttons. **P** = play this track back. **R** = record live input. **E** = edit the curve. P and R are mutually exclusive; E sits alongside P (P+E = play the edited curve).
- **Overdub** — record one parameter (R) while others play back (P) so you can layer a focus pull on top of an existing camera move.
- **Relative-from-current playback** — playback applies the recorded delta from the slider's current position rather than snapping the camera to the recorded start. Cinematographer-natural behaviour.
- **Home** — settles every P-armed track to its recorded starting value (or rewinds the playhead to t=0 if there's nothing to home). Bindable.
- **Spacebar** = play/pause toggle (ignored when typing or in a learn state).
- **Bindable transport** — REC, PLAY/STOP, and HOME live in the Functions panel and can be bound to keys or gamepad buttons.

### Canvas timeline

- HTML5 canvas timeline beneath the transport, one colour-coded polyline per track.
- **Playhead** is draggable end-to-end, with a chunky flag head + grip dots for affordance. Always drawn — including on empty new takes at t=0.
- **Click-to-seek + drag-to-scrub** anywhere on the canvas. Disabled mid-record so a stray click can't corrupt a take.
- **Hover tooltip** showing time + per-track values under the cursor.
- **Zoom + horizontal scroll** — `+` / `−` / Fit buttons, mouse-wheel zoom anchored at the cursor, draggable scroll thumb. Window width displayed live.
- **Smooth playhead-follow** during record and play — once the playhead crosses 80% of the visible window the view slides forward at the playhead's velocity, so the playhead stays pinned at 80% and the timeline glides past underneath. Backward jumps (Rewind) re-centre the view.
- **Adaptive time grid** — second markers and sub-grid step automatically as you zoom.
- **Shaded region** past the take's end so empty space is distinguishable from recorded space.

### Bezier-lite curve editing

- Click **E** on any track row with recorded data to enter anchor-editing mode. Raw samples drop to a faint ghost; a smoothed **Catmull-Rom spline** through 6–40 anchors becomes the playback curve.
- **Adaptive anchor density** — anchors are placed by **Ramer-Douglas-Peucker** simplification with auto-tuned tolerance, so complex moves get more anchors automatically and smooth stretches stay clean.
- **Drag anchors** to reshape the move. Inner anchors clamp between neighbours (no crossing); endpoints are pinned in time but free in value.
- **Manual insert** — double-click anywhere over the curve to add an anchor. Snaps to the curve if you click within 10% of slider range, otherwise lands exactly where you clicked.
- **Manual remove** — right-click an anchor. Endpoints protected.
- **R clears P + E** — clicking record on an edited track wipes both flags so the next REC starts clean.

### Colours

- **32-swatch Rexy palette** — hand-picked colours arranged 4 rows × 8 columns. Each row matches a hardware family (Wheels / Lens / Grip / Base); each column reads as visually distinct from its neighbours.
- **Per-track colour picker** — click the colour dot on any track row to open the 32-swatch picker; right-click to reset to default. Overrides persist in localStorage.
- **Three-way distinct defaults** within each family — e.g. pan = deep pink, tilt = pure red, roll = pale pink, so a triple is unmistakable on the timeline at a glance.

### Take exchange

- **Save** — exports the active take to a `.rxmove` JSON file via the native "Save As" dialog (with Downloads fallback). Includes tracks, anchor edits, and per-track P/R/E arming state.
- **Load** — file picker reads a `.rxmove`, mints a fresh take id so it doesn't collide, adds it to the take list with " (imported)" appended. Per-track arming restored from the file. v1 (pre-arming) files still load — the importer just skips that block.

### Other v2 changes

- **Lens reorder** — cards are now **Focus / Iris / Zoom** (on-set order). The "Aperture" label is now "Iris" everywhere user-facing; the underlying parameter id stays `aperture` so existing `mappings.json`, bindings, and saved configs work unchanged.
- **MoCo Reset button** — confirms, then wipes all takes + colour overrides + per-track arming + view state, leaving bindings / tunings / calibration / custom lenses intact.
- **Defensive arming logic** — P/R/E mutual exclusion is enforced at read-time as well as write-time, so a track on an empty take always shows R-armed (the "you can't play back what hasn't been captured" rule).
- **Late-binding render fix** — MoCo tracks list re-renders when the active camera arrives, so all bound params appear immediately instead of just the legacy default slot.
- **Recording arming lock** — REC explicitly locks in the recordable-track set so the auto-default rule can't flip a track mid-take after the first sample is captured.

## [1.0.0] — Initial public release

### Bridge (Python)

- Mappings-driven OSC → UE Remote Control bridge — every parameter defined in `mappings.json`, no hard-coded camera or crane references in code.
- Per-camera rig discovery — `set_camera` walks the actor's attach chain and re-targets crane / base mappings to the camera's parent CameraRig_Crane.
- Velocity tick loops: drone (camera-local `K2_AddLocalOffset`), base (world `K2_AddWorldOffset` on crane TransformComponent), continuous wheels (camera-local `K2_AddLocalRotation`).
- Per-mapping access override (`WRITE_ACCESS` vs `WRITE_TRANSACTION_ACCESS`) — crane params use transactional to keep editor preview meshes visible during moves.
- Per-mapping write throttling (`write_throttle_ms`) — 10Hz coalesced writes for crane axes to stop UE's mesh rebuild from making the crane invisible during high-rate writes.
- Per-mapping output scale (`scale_type: log`) — focus uses log mapping so the slider has useful range from 30cm to ∞.
- Calibration model: `calibrate_param`, `clear_offset`, `force_write`, `force_write_value`. Used by Reset and Autolevel.
- Custom lens system: writes `LensSettings` directly to the camera, re-scopes zoom/aperture/focus mappings, supports infinity focus.
- Filmback preset support.
- Live state broadcast at 4Hz (camera location, camera rotation, crane location) for the GUI's Live readouts.
- Position read/write/zero API for camera and crane.
- Panic stop function (programmatic, also drives the per-axis Reset).
- Multi-camera discovery via Remote Control preset (`RexyControl`).

### Browser app (HTML/JS)

- Mappings-aware GUI with cards for every parameter (wheels, focus/lens, grip, base).
- Per-card tuning: **S** (sensitivity), **C** (curve gamma), **D** (deadband), **F** (feather).
- Per-card Min/Max with unit-aware display (cm ↔ ft).
- Per-camera bindings — switching cameras swaps the binding slot; each camera has its own.
- Multi-input binding: keyboard, gamepad axes, gamepad buttons. Auto-invert on bind based on first deflection direction.
- Gamepad debug panel with per-axis live values, calibration display, and 5-second null-drift capture.
- Out-of-range axis filter (handles Rexy Wheels firmware bug on axis 9).
- Hold per-axis: freezes binding processing until released.
- Reset per-axis: halts velocity for velocity-driven axes; clears offset + zeroes for absolute axes.
- Autolevel Roll function — bindable, animated with time + feather controls, works in both absolute and continuous modes.
- Wheels mode toggle: Absolute / Continuous.
- Grip mode toggle: Crane / Dolly / Drone with auto-greying based on camera-on-crane status.
- Independent units toggles: global (metric / imperial) + focus-only.
- Custom lens dialog with full LensSettings write.
- Position panel with Set / Zero per-axis for camera (drone target) and crane (base).
- Live readouts on every card showing UE's actual property value.
- Full Export / Import of all state (bindings, tunings, ranges, custom lenses, units, mode selections).

### Hardware

- Rexy Wheels: filtered for the known firmware quirk on axis 9 and 0.008 idle drift.
- PS4/Xbox controllers: supported via Gamepad API.
- Keyboard: bindable per parameter.

## Snagging list (for the next session)

- Rexy Wheels firmware: phantom data on axis 9, ~0.008 idle drift, VID/PID
- Per-camera lens persistence
- `PARAM_RANGES` mode-awareness (dolly Min/Max showing crane units)
