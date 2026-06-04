# Screenshots — index

The README and the UE5 setup guide reference the following images. Save the screenshots Rob captured into this directory (`release/docs/screenshots/`) using these exact filenames so the Markdown links resolve.

## Required filenames

| Filename | What it shows | Used in |
|---|---|---|
| `app-header.png` | Top of the app: logos, status indicators, units toggle, config row, active-camera list | `README.md` × 2 |
| `wheels-functions.png` | The Rexy Wheels cards (pan/tilt/roll) + Functions panel with Autolevel | `README.md` × 2 |
| `wheel-card-bound.png` | Close-up of a single roll card with a bound axis (PAD1·AX2) | `README.md` |
| `focus-section.png` | Rexy Focus — lens & body section showing zoom/aperture/focus, focus units toggle | `README.md` |
| `grip-crane-full.png` | Full Rexy Grip in Crane mode — three crane cards + crane-target panel + three base cards + crane-base panel | `README.md` |
| `grip-dolly-mode.png` | Rexy Grip in Dolly mode — X/Y/Z as camera-local distances in cm | `README.md` |
| `grip-drone-mode.png` | Rexy Grip in Drone mode — X/Y/Z as velocities in m/s | `README.md` |
| `gamepad-debug.png` | Gamepad Debug panel with multiple devices (vJoy, PS4, Rexy Wheels), calibration offsets visible, axis 9 flagged red | `README.md` |
| `ue5-place-actors.png` | UE5 Place Actors panel showing Cinematic actors including Camera Rig Crane and Cine Camera Actor | `docs/ue5-setup.md` |
| `ue5-scene.png` | UE5 viewport + World Outliner showing a CineCameraActor parented under a CameraRig_Crane | `docs/ue5-setup.md` |
| `ue5-expose-property.png` | UE5 Details panel with the right-click "Expose property" context menu open | `docs/ue5-setup.md` |
| `ue5-rexycontrol-preset.png` | UE5 Remote Control panel with the RexyControl preset and exposed properties (focal length, aperture, rotation, crane yaw/pitch, transform, focus distance) | `docs/ue5-setup.md` |

## How to save them

For each image Rob attached in the Cowork chat, right-click → **Save image as…** → save into:

```
release/docs/screenshots/<filename>.png
```

The folder `release/docs/screenshots/` doesn't exist yet — create it (or `mkdir -p` in Terminal). Once the files are in place, all the inline images in the README and UE5 setup guide will render correctly on GitHub.

## If you want more shots later

Nice-to-have additions (not in v1.0 README, but would strengthen the project's landing page if/when captured):

- **`autolevel.gif`** — 5-10 second clip of pressing the Autolevel button and watching roll smoothly return to 0°.
- **`continuous-mode.gif`** — pan in continuous mode spun past 180° to demonstrate infinite rotation.
- **`focus-pull.gif`** — focus going from ∞ to ~50 cm with a recognisable UE5 subject going in and out of focus.
- **Hero composite** — wide screenshot of the app and UE5 viewport side-by-side mid-pan.

Tools: ScreenToGif (Windows), Kap (Mac). Keep GIFs at ~10 fps to stay under GitHub's file-size sweet spot.
