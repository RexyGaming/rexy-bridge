# Changelog

All notable changes to Rexy Bridge will be documented here.

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
