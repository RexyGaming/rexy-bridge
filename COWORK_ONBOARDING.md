Hi Claude. I want to set up "Rexy Bridge" on my computer — it's an open-source tool for controlling cameras in Unreal Engine 5 with physical wheels or game controllers.

I'd like you to walk me through it one step at a time, and use your tools to do as much of the work for me as possible (running shell commands, editing files, checking what's installed).

The project is here: https://github.com/RexyGaming/rexy-bridge

Before we start: PLEASE FETCH AND READ these two pages so you understand what we're setting up:
- https://github.com/RexyGaming/rexy-bridge/blob/main/README.md
- https://github.com/RexyGaming/rexy-bridge/blob/main/docs/ue5-setup.md

Here's my starting point — please ask me about anything I haven't filled in:
- My computer: [Mac / Windows / Linux]
- My UE5: [I have UE 5.x installed / I haven't installed UE5 yet]
- My UE5 project: [it's at <path> / I'll create one with your help]
- My controller / hardware: [Rexy Wheels / PS4 controller / Xbox controller / keyboard only / nothing yet]

Here's the high-level workflow. Please verify each step works before moving on:

1. Check what's installed (Python, pip, git). Install whatever's missing.
2. Clone the Rexy Bridge repo to a sensible folder.
3. Install Python dependencies — **on Mac, use a virtual environment** (the system pip is protected):
   ```
   python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
   ```
4. Enable the Remote Control API plugin in UE5 (Edit → Plugins → search “Remote Control”).
5. In UE5, add a **Cine Camera Actor** (not plain CameraActor) and optionally a CameraRig_Crane. Attach the camera to the crane if using one.
6. Create the `RexyControl` Remote Control preset — **right-click in the Content Browser → Remote Control → Remote Control Preset**, name it exactly `RexyControl`. The Window menu path no longer works in UE 5.5+.
7. Expose **any one property** on each actor (CineCameraActor, CameraRig_Crane) to the RexyControl preset. Any property works — one per actor is enough.
8. Find the UE object paths for the camera and crane. The pattern is:
   `/Game/<LEVEL>.<LEVEL>:PersistentLevel.<ACTOR>.<COMPONENT>`
   Find `<LEVEL>` from the editor tab, `<ACTOR>` from the World Outliner.
9. Copy and fill in `bridge/mappings.json` from `mappings.json.example`. **The file must go in the `bridge/` subfolder, not the repo root.**
10. Run the bridge — **on Mac with venv**
    ```
    ./venv/bin/python3 bridge/rexy_osc.py --verbose
    ```
    On Windows: `cd bridge && python rexy_osc.py --verbose`
11. Open `app/index.html` in Chrome/Firefox. Check the three status indicators:
    - **SCRIPT RUMNING** — pink dot (active)
    - **WS CONNECTED** — green dot
    - **UE RC** — green dot. If grey but camera sliders still move UE, the connection is working — it's a display timing issue.
12. Click **Rescan** to find cameras. If nothing appears, check you used CineCameraActor and exposed at least one property to RexyControl.
13. Drag the pan slider — confirm the camera moves in UE.
14. To bind hardware: click **Bind** on a param card. **First click the page, then press a physical button on the device** — the browser Gamepad API requires a button press (not just moving axes) to detect controllers.
15. If using Rexy Wheels, bind pan and tilt axes. If using PS4/Xbox sticks, run Null Drift calibration (Gamepad Debug → Null Drift 5s) after moving the sticks.

How I'd like you to work with me:
- Explain what you're doing as you go, but keep it brief.
- If a step fails, troubleshoot with me — don't just point me at the docs.
- After each major step, briefly summarise what we did and what's next.
- If I get confused, ask me to take a screenshot.

Don't go ahead until I'm ready. Start by asking me to confirm the bracketed details above, then read the README and ue5-setup.md before we begin.