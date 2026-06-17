# Getting a UE5 scene set up for Rexy Bridge

This page covers the bit before `ue5-setup.md`: **how to get a level loaded into UE5 with a working crane + camera ready for Rexy to drive**. If you've already got UE5 open with a scene you like, skip to [Adding the crane + camera](#3-adding-the-crane--camera).

If you're brand new to UE5 and just want to see Rexy doing its thing as fast as possible, follow this in order.

---

## 1. Pick a project template (the fastest path)

When you first launch UE5 and click **New Project**, you're offered templates. Three good starting points depending on what you want:

| Template | When to pick it | Why |
|---|---|---|
| **Film / Video & Live Events** | You want the "real" VP experience | Pre-built virtual production stage with LED wall, lights, and cinematic actors. Closest match to a real on-set workflow. |
| **Third Person** | You just want a simple level to test against | Default Quixel-styled map, runs on any GPU, you'll be driving cameras in under 2 minutes. |
| **Blank** | You want full control | Empty level — you'll add a Floor, SkyLight, and DirectionalLight yourself before dropping in actors. |

For your first time, pick **Film / Video & Live Events** if it's installed (UE 5.4+), otherwise **Third Person**. Save the project somewhere local (not in Dropbox / OneDrive / iCloud — sync races corrupt UE asset writes).

---

## 2. Recommended levels for practice (Rexy-friendly, all free)

The template's starter map is fine for first tests, but for a richer scene — especially when you're learning the wheels — these are worth grabbing. All free, all on Fab (Epic's content marketplace), all built for UE5.

### How to install any of these

1. Open the [Fab marketplace](https://www.fab.com) in a browser (or use the **Fab** plugin inside UE5: enable it via Edit → Plugins, then access via Window → Fab).
2. Sign in with your Epic Games account.
3. Find the asset (links in each entry below).
4. Click **Add to My Library**.
5. Back in the **Epic Games Launcher** → **Unreal Engine** → **Library** → **Fab Library**, find the asset and click **Install to Engine** (for asset packs you load into an existing project) or **Create Project** (for full sample projects with their own level).

### Top picks for Rexy practice

These are ranked roughly by "how quickly you can get a great-looking shot with wheels in your hands."

| Project | Size | UE | What it's good for |
|---|---|---|---|
| **Electric Dreams Environment** | ~13 GB | 5.2+ | The single best Rexy practice scene. A photoreal PCG jungle with a forest road — lots of parallax, dramatic lighting, perfect for testing focus pulls, crane swings through trees, and dolly moves along the road. Great visual feedback even for small wheel inputs. [Fab listing](https://www.fab.com/listings/d79688f5-29be-4fb2-a650-2d4a813f5306) |
| **Valley of the Ancient** | ~100 GB | 5.0+ | Massive 2x2km canyon environment showing off Nanite/Lumen. Two distinct sub-scenes (photoreal valley + mythical interior). Huge but visually outstanding — heavyweight on GPU. Best for "wow factor" demos rather than quick tests. [Fab listing](https://www.fab.com/listings/0c19880e-21bd-42ba-8287-1caccc3951b1) |
| **City Sample (Matrix Awakens)** | ~100 GB | 5.0+ | Open city with cars, crowds, MetaHuman pedestrians. Test urban camera work — crane up to street level, dolly along sidewalks, focus pulls on passing vehicles. Needs a strong GPU (RTX 3080+ comfortable). [Fab listing](https://www.fab.com/listings/4898e707-7855-404b-af0e-a505ee690e68) |
| **Project Titan** | ~80 GB | 5.5+ | 8x8km open world with 9 biomes — forest, desert, snow, etc. Excellent for variety in one project. Released Dec 2024, designed as an open-world learning resource. [Fab listing](https://www.fab.com/listings/c05aac82-4c1a-4e42-96b3-be668dc40fca) |
| **Lyra Starter Game** | ~20 GB | 5.1+ | Multiple game-style environments built into one project. Good for testing different lighting setups and indoor/outdoor variety. From the Epic Library → Sample Projects. |
| **Stack O Bot** | ~5 GB | 5.6+ | Small, friendly sample game rebuilt for 5.6. The level is simple but it's the lightest-weight project here — runs on a laptop GPU. Quick to load. [Fab listing](https://www.fab.com/listings/b4dfff49-0e7d-4c4b-a6c5-8a0315831c9c) |

### Lightweight asset packs (drop into your own project)

If you don't want a full sample project, these are pure environment packs you load into a blank or template-based level. Good for building your own scene from scratch.

- **Soul: City** — 419 meshes + materials, urban props, mobile-optimised so it's snappy. [Free on Fab](https://www.fab.com/listings/dd77fee6-0ad2-41ce-b32c-09300c24c9f3). Pair with a simple street layout for dolly tests.
- **Soul: Cave** — 173 meshes, rock and water props. Smaller scope but the dramatic lighting suits intimate camera moves.
- **Quixel Megascans** (free, built into UE since 2025) — open Window → Quixel Bridge inside UE, browse Collections → Environment, drop any preset asset into your level. Hundreds of options. [Fab Megascans hub](https://www.fab.com/category/megascans).
- **A-COM Animation Sample** (Agora Studio, 2025) — full short-film project showing virtual art department workflows. Worth grabbing if you want to see how a real cinematic project is structured.

### What about the Film/Video & Live Events template?

When you create a new project from this template, UE generates a virtual production stage with an LED wall, lighting rig, and cinematic actors already in place. It's the closest thing to a real on-set workflow but the GPU load is significant. Best for showing what a real VP setup looks like once you've gotten comfortable with the wheels on a lighter scene.

### Things to test in each scene

Once you've got Rexy connected to one of these:

| Test | Why |
|---|---|
| Slow crane up through trees / buildings | Tests parallax + your sense of timing on the wheels |
| Focus pull from foreground subject to background | Tests the focus wheel + lens range. Electric Dreams is ideal for this |
| Dolly along a road or path | Tests sustained smooth motion + auto-invert direction |
| Quick whip-pan with auto-level on the return | Tests Autolevel function + recovery |
| Record a 10-second performance, then play back via Bake mode | Tests Virtual MoCo + UE Take Recorder integration |
| Switch between two cameras at different rig points | Tests multi-camera + per-camera bindings |

## 3. Adding the crane + camera

This is the bit Rexy actually needs. Two actors, attached together.

### 3a. Drop in the crane

1. Open **Window → Place Actors** (top menu). A panel appears on the left or right.
2. In the search box, type **`Camera Rig Crane`**.
3. **Drag the result into the viewport** — drop it anywhere on the floor. You should see a small crane-shaped wireframe appear.
4. Optionally move/rotate it to a useful position (W/E/R for translate/rotate/scale gizmos).

### 3b. Drop in the camera

1. Same Place Actors panel, search **`Cine Camera Actor`**.
2. Drag it into the viewport. A floating cinematic camera appears.

> ⚠️ **Important:** Use **Cine Camera Actor**, *not* plain "Camera Actor". Rexy only finds CineCameraActors. Plain CameraActors won't show up in Scan UE.

### 3c. Attach the camera to the crane

1. Open the **World Outliner** (top-right of the editor by default — if not visible: **Window → World Outliner**).
2. You'll see your two new actors listed: `CameraRig_Crane` and `CineCameraActor`.
3. **Drag the `CineCameraActor` line directly onto the `CameraRig_Crane` line**.
4. A dialog appears asking which socket to attach to. **Pick `CameraMount`** (the only sensible option for a crane).
5. The outliner now shows `CineCameraActor` indented under `CameraRig_Crane` — that's the parenting working.

### 3d. Save the level

`File → Save Current Level As...` if it's a new map, or `Ctrl+S` if you've already named it.

---

## 4. Verify with Rexy

1. Make sure the **Remote Control API plugin** is enabled (Edit → Plugins → search "Remote Control" → tick). Restart UE5 if you just enabled it.
2. Start the bridge: `cd "C:\Dev\Rexy OSC UE5\rexy-bridge\bridge" && python rexy_osc.py --verbose` (or run `start_bridge.ps1`).
3. Open `app/index.html` in your browser.
4. Status row should read amber **UE — waiting…** for a moment, then green **UE RC · N cams**.
5. Click **⌕ Scan UE** in the active-camera row.
6. The confirmation panel should show one camera (`CineCameraActor`) paired with one crane (`CameraRig_Crane`).
7. Click **Apply + Save** → camera appears in the row. Click it to make active.
8. Drag the pan slider — the cine camera in UE should rotate.

If any of that fails, see `ue5-setup.md` for the deeper troubleshooting (Remote Control plugin settings, WebSocket port, etc).

---

## 5. Multiple cameras and cranes

You can have as many cameras and cranes as you like in a single level. Drop in extras the same way:

- More cameras → repeat 3b + 3c (attach each to a crane, or leave some "free" / unattached for handheld-style work)
- More cranes → repeat 3a, then attach a fresh camera to each

Rexy's Scan UE finds them all. The camera-picker row in the app lets you switch between them, and per-camera bindings are remembered separately so you can have different wheel mappings per camera (e.g. one camera bound to a Rexy Wheels device, another to a PS4 stick).

---

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Scan UE returns 0 cameras | UE still loading the level | Wait for the editor to finish compiling shaders, then try again |
| Scan UE returns 0 cameras (after load) | You dropped in a plain "Camera Actor", not "Cine Camera Actor" | Delete it, drop in `CineCameraActor` instead |
| Camera doesn't appear paired with crane | You didn't pick `CameraMount` socket in the attach dialog | In Outliner: right-click camera → Detach. Re-drag onto crane, pick `CameraMount` this time |
| Crane is invisible | The crane mesh is hidden when the camera moves through it — UE editor preview quirk | This is cosmetic, not a Rexy bug. The crane is still there |
| Sliders move in app but camera doesn't move in UE | Active camera not selected, or wrong camera selected | Click the camera button in the camera row to make it active |
| UE 5.7 specifically: "RexyControl preset not found" | You're on v2-beta which doesn't need it | That's a warning, not an error — auto-scan works without the preset |

---

## Where this fits in the workflow

```
1. Open UE5 + project (this doc)
        ↓
2. Drop crane + camera (this doc)
        ↓
3. Run bridge + open app
        ↓
4. Click ⌕ Scan UE (auto-mapping, v2-beta)
        ↓
5. Bind wheels/sticks/keys (README)
        ↓
6. Drive the camera live, or record performances with Virtual MoCo (CHANGELOG v2)
```

For step 4 onwards, see the [main README](../README.md) and [`ue5-setup.md`](ue5-setup.md). For the v2 MoCo features, see the [CHANGELOG](../CHANGELOG.md) v2.0.0-beta.2 entry.
