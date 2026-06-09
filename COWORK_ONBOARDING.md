Hi Claude. I want to set up "Rexy Bridge v2 beta" on my computer — it's an open-source tool for controlling cameras in Unreal Engine 5 with physical wheels or game controllers. The v2 beta adds a Virtual Motion Control system on top of v1: I can record live camera moves, play them back, edit the curves, and save/load takes as files.

I'd like you to walk me through it one step at a time, and use your tools to do as much of the work for me as possible (running shell commands, editing files, checking what's installed).

The project is here: https://github.com/RexyGaming/rexy-bridge

**This is a v2 beta** — the stable v1 lives on the `main` branch. v2 is on the `v2-beta` branch and the `v2.0.0-beta.1` tag. If something feels rough, that's expected — please tell me what to report back as a beta issue.

Before we start: PLEASE FETCH AND READ these three pages so you understand what we're setting up:
- https://github.com/RexyGaming/rexy-bridge/blob/v2-beta/README.md
- https://github.com/RexyGaming/rexy-bridge/blob/v2-beta/docs/ue5-setup.md
- https://github.com/RexyGaming/rexy-bridge/blob/v2-beta/CHANGELOG.md (read the v2.0.0-beta.1 section — that's what's new)

Here's my starting point — please ask me about anything I haven't filled in:
- My computer: [Mac / Windows / Linux]
- My UE5: [I have UE 5.x installed / I haven't installed UE5 yet]
- My UE5 project: [it's at <path> / I'll create one with your help]
- My controller / hardware: [Rexy Wheels / PS4 controller / Xbox controller / keyboard only / nothing yet]
- I've used Rexy Bridge before? [yes, v1 is already working on this machine / no, fresh install]

Here's the high-level workflow. Please verify each step works before moving on:

## Part 1 — install (skip if v1 is already working on this machine; just `git fetch && git checkout v2-beta && git pull` to upgrade)

1. Check what's installed (Python, pip, git). Install whatever's missing.
2. Clone the Rexy Bridge repo to a sensible folder, then check out the v2-beta branch:
   ```
   git clone https://github.com/RexyGaming/rexy-bridge
   cd rexy-bridge
   git checkout v2-beta
   ```
3. Install Python dependencies — **on Mac, use a virtual environment** (the system pip is protected):
   ```
   python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
   ```
4. Enable the Remote Control API plugin in UE5 (Edit → Plugins → search "Remote Control").
5. In UE5, add a **Cine Camera Actor** (not plain CameraActor) and optionally a CameraRig_Crane. Attach the camera to the crane if using one.
6. Create the `RexyControl` Remote Control preset — **right-click in the Content Browser → Remote Control → Remote Control Preset**, name it exactly `RexyControl`. The Window menu path no longer works in UE 5.5+.
7. Expose **any one property** on each actor (CineCameraActor, CameraRig_Crane) to the RexyControl preset. Any property works — one per actor is enough.
8. Find the UE object paths for the camera and crane. The pattern is:
   `/Game/<LEVEL>.<LEVEL>:PersistentLevel.<ACTOR>.<COMPONENT>`
   Find `<LEVEL>` from the editor tab, `<ACTOR>` from the World Outliner.
9. Copy and fill in `bridge/mappings.json` from `mappings.json.example`. **The file must go in the `bridge/` subfolder, not the repo root.**
10. Run the bridge — **on Mac with venv:**
    ```
    ./venv/bin/python3 bridge/rexy_osc.py --verbose
    ```
    On Windows: `cd bridge && python rexy_osc.py --verbose`
11. Open `app/index.html` in Chrome/Firefox. Check the three status indicators:
    - **SCRIPT RUNNING** — pink dot (active)
    - **WS CONNECTED** — green dot
    - **UE RC** — green dot. If grey but camera sliders still move UE, the connection is working — it's a display timing issue.
12. Click **Rescan** to find cameras. If nothing appears, check you used CineCameraActor and exposed at least one property to RexyControl.
13. Drag the pan slider — confirm the camera moves in UE.
14. To bind hardware: click **Bind** on a param card. **First click the page, then press a physical button on the device** — the browser Gamepad API requires a button press (not just moving axes) to detect controllers.
15. If using Rexy Wheels, bind pan and tilt axes. If using PS4/Xbox sticks, run Null Drift calibration (Gamepad Debug → Null Drift 5s) after moving the sticks.

## Part 2 — Virtual MoCo tour (this is new in v2)

Bind at least pan and tilt (or any two parameters) before starting this part. The MoCo panel sits below Rexy Grip.

16. **Record your first take.** Click **● REC** in the Virtual MoCo panel, then wheel pan and tilt around for ~10 seconds. Hit **■ STOP**. You should see two coloured curves appear on the timeline below the transport row.
17. **Play it back.** Click **▶ PLAY**. The camera should move on its own, replaying what you just performed. Hit STOP to interrupt at any time.
18. **Scrub the timeline.** Click and drag anywhere on the timeline — the playhead follows the cursor, and the camera updates live as you scrub. The flag-head on the playhead is the visible drag handle.
19. **Zoom in.** Use the `+` / `−` buttons under the timeline, the mouse wheel, or **⤢ Fit** to fit the whole take. There's a horizontal scroll thumb so you can pan around when zoomed in. During playback the view auto-follows the playhead.
20. **Make another take.** Click **+ New** — a fresh empty take appears in the dropdown. Records pile up, you can switch between them via the dropdown.
21. **Try per-track arming.** Each track row has **P** (play) and **R** (record) buttons. Toggle **R** off on pan — now hit REC. Tilt re-records but pan plays back from your previous take. That's overdub.
22. **Try Bezier editing.** Pick a track with data and click its **E** button. Anchor dots appear on the curve. Drag an anchor to reshape the move. Double-click on the curve to add a new anchor. Right-click an anchor to remove it. Hit PLAY — the camera now follows your edited path.
23. **Save a take.** Click **↑ Save** at the top of the MoCo header. Save it somewhere as a `.rxmove` file. That's a portable take file you can email, archive, or share.
24. **Load a take.** Click **↓ Load** and pick the file you just saved. It appears in your take list with " (imported)" appended.
25. **Reset if things get tangled.** The **⟲ Reset** button at the top wipes all takes + colour overrides + arming, leaving your bindings/tunings/calibration alone. Useful for starting clean during the beta.

How I'd like you to work with me:
- Explain what you're doing as you go, but keep it brief.
- If a step fails, troubleshoot with me — don't just point me at the docs.
- After each major step, briefly summarise what we did and what's next.
- If I get confused, ask me to take a screenshot.
- For the v2 features specifically: if something doesn't behave like the docs claim, that's a beta bug — note it down so I can report it on GitHub Issues with the `v2-beta` tag.

Don't go ahead until I'm ready. Start by asking me to confirm the bracketed details above, then read the README, ue5-setup.md, and the v2 CHANGELOG section before we begin.
