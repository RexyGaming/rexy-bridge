# UE5 Setup Guide

This is the part most people get stuck on. Take it step by step. Once you've done it once for one project, you'll fly through it for the next.

## 1. Enable the Remote Control plugin

1. Open your project in UE5.
2. **Edit → Plugins**.
3. Search for **Remote Control**.
4. Tick the **Remote Control API** plugin checkbox.
5. Tick the **Remote Control Web Interface** plugin if available (optional, but useful for testing).
6. Restart UE5 when prompted.


## 2. Enable the Remote Control WebSocket server

Rexy Bridge talks to UE over WebSocket (not HTTP). You need to confirm the WS server is running.

1. **Project Settings → Plugins → Remote Control**.
2. Verify **WebSocket Server Port** is `30020` (the default).
3. Confirm **WebSocket Server Bind Address** is `0.0.0.0` or `127.0.0.1` (default).
4. Save and restart if anything changed.

You can test the server is up by visiting `http://127.0.0.1:30010` in your browser (the HTTP server, not WS, but it confirms the plugin is active).

## 3. Add your cinematic actors

> ⚠️ **Important:** Use **Cine Camera Actor**, not plain "Camera Actor". Rexy Bridge's camera discovery only finds CineCameraActors — a plain CameraActor will not show up when you click Rescan in the app.

If you're starting from scratch, the actors you'll typically want are under **Place Actors → Cinematic**:

- **Camera Rig Crane** — the rig you'll drive with Crane mode.
- **Cine Camera Actor** — the camera you'll attach to the crane (or use free).

Drop these into your scene and attach the cine camera to the crane (drag it onto the crane in the World Outliner; UE will offer the `CameraMount` socket).

A typical resulting scene looks like this — note the World Outliner hierarchy with `CineCameraActor` parented under `CameraRig_Crane`:

[![A typical Rexy-ready scene in UE5](docs/screenshots/ue5-scene.png)](docs/screenshots/ue5-scene.png)

## 4. Create the RexyControl preset

The bridge uses a Remote Control preset called `RexyControl` to discover cameras automatically.

> **UE 5.5+:** The `Window → Remote Control` menu path no longer exists. Use the Content Browser instead:

1. Open the **Content Browser** (click **Content Drawer** at the bottom of the editor).
2. Navigate to where you want to save the preset (e.g. a `RemoteControl` folder).
3. **Right-click** in an empty area → **Remote Control → Remote Control Preset**.
4. Name it exactly **`RexyControl`** (case-sensitive — capital R, capital C).
5. Hit Enter, then **double-click** it to open the preset editor.


## 5. Expose properties so Rexy Bridge can find your cameras and crane

Rexy Bridge discovers cameras by looking at which actors the `RexyControl` preset has properties exposed on. You only need to expose **one property per actor** — any property will do. The bridge uses this as a "handle" to find the actor, then controls it directly.

For each actor you want available in Rexy Bridge (**CineCameraActor** and **CameraRig_Crane**):

1. Select the actor in your level.
2. In the **Details panel**, right-click on **any property** (e.g. Location, or anything visible).
3. Choose **Expose property** (or **Remote Control → Expose to RexyControl**) from the context menu.
4. If prompted to choose a preset, select **RexyControl**.

Once both actors have at least one property showing in the RexyControl preset, you're done with this step.

> You don't need to expose every property Rexy Bridge controls — just one per actor so the bridge can find them. The bridge then walks each camera's `SceneComponent` and `CameraComponent` directly for the actual control writes.

## 6. Set up your crane (optional)

If you want the Grip section to work with a CameraRig_Crane actor:

1. Add a `CameraRig_Crane` actor (see step 3 above).
2. Attach your camera to it: drag the camera onto the crane in the World Outliner, or set the camera's **Parent Actor** to the crane.
3. Make sure the camera's Attach Socket is `CameraMount` (the crane's mount socket).

The bridge auto-detects the crane attachment when you select a camera in the app — the Crane mode button will be enabled if the camera is on a crane.

## Finding your paths

Your `mappings.json` needs the full object paths to your specific actors. Here's how to find them.

### Method 1: Use the example file

Look at `mappings.json.example` in this repo. The structure of the paths follows a predictable pattern:

```
/Game/<YOUR_LEVEL>.<YOUR_LEVEL>:PersistentLevel.<YOUR_ACTOR>[.<YOUR_COMPONENT>]
```

> **Note:** If your level is directly in the Content folder (not in a subfolder), you don't need a project prefix — just use `/Game/<YOUR_LEVEL>` directly. If your level is in a subfolder like `Content/Maps/`, the path would be `/Game/Maps/<YOUR_LEVEL>.<YOUR_LEVEL>:...`

| Placeholder | What it is | Example |
| --- | --- | --- |
| `<YOUR_LEVEL>` | Your level / map name (shown in the editor tab) | `Main` |
| `<YOUR_ACTOR>` | The actor as named in the World Outliner | `CineCameraActor_0` |
| `<YOUR_COMPONENT>` | The component on that actor | `SceneComponent`, `CameraComponent`, `TransformComponent` |

Find your actor names in the **World Outliner** in UE5. Find your level name in the tab at the top of the editor.

### Method 2: Run the bridge with --verbose

1. Edit `mappings.json` with your best guess at the paths.
2. Run the bridge with `--verbose`.
3. In the app, click **Rescan** in the camera row.
4. The bridge logs every discovered camera to the terminal window. Copy those paths into `mappings.json`.


## Testing the connection

1. Start the bridge (see README for the correct command for your OS).
2. Open `app/index.html` in your browser.
3. You should see in the top-right of the app:
   - **SCRIPT RUNNING** — pink/active dot
   - **WS CONNECTED** — green dot
   - **UE RC** — green dot (may take a moment; if grey but the camera slider still moves UE, the connection is working)
4. In the camera row, click **Rescan**. Your CineCameraActor should appear as a button.
5. Click the camera → drag the pan slider in the app → camera should rotate in UE5 in real time.

If any of the three dots are red or grey:

- **HARDWARE OFFLINE** — your gamepad/wheels aren't detected. Click anywhere on the page first, then **press a physical button** on the device (not just move an axis — the browser Gamepad API requires a button press to activate).
- **WS OFFLINE** — the Python bridge isn't running or the WS port (default 9000) is busy.
- **UE RC OFFLINE** — the Remote Control plugin isn't running, or the port is wrong, or your project isn't open. Verify by dragging a slider — if the camera moves, the connection is actually working despite the indicator.


## Common gotchas

- **Preset name is case-sensitive.** It MUST be `RexyControl` exactly.
- **Use CineCameraActor, not CameraActor.** Plain camera actors won't appear in Rescan.
- **Editor only, not Play mode.** The bridge writes properties via Remote Control, which works live in the editor without entering PIE.
- **Modifying `mappings.json` requires a bridge restart.** The file is read once at startup. Ctrl+C the bridge and restart it after edits.
- **mappings.json lives in the `bridge/` subfolder**, not the repo root.
- **Crane visibility flickers** if `crane_rerun_construction` is `true`. Default is `false`. Only flip it on if you're debugging crane mesh issues.
- **Controller not showing in debug panel?** Click the page first, then press a physical button on your controller. Turning wheels/moving sticks alone won't trigger browser gamepad detection.
