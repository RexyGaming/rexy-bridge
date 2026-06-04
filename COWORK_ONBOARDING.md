# Cowork Onboarding Prompt

Copy the prompt below, paste it into Cowork mode in the Claude desktop app, fill in the bracketed details, and send. Claude will walk you through the entire setup.

Tested with the Claude desktop app's Cowork mode. The agent has access to your filesystem (with permission), a shell, and a web browser — it can install Python, clone the repo, edit your config files, and test the connection on your behalf.

---

## The prompt

```
Hi Claude. I want to set up "Rexy Bridge" on my computer — it's an open-source tool 
for controlling cameras in Unreal Engine 5 with physical wheels or game controllers.
I have very little experience with this kind of thing. I'd like you to walk me through 
it patiently, one step at a time, and use your tools to do as much of the work for me 
as possible (running shell commands, editing files, checking what's installed).

The project is here: https://github.com/[OWNER]/rexy-bridge

Before we start: PLEASE FETCH AND READ these two pages so you understand what we're 
setting up:
- https://github.com/RexyGaming/rexy-bridge/blob/main/README.md
- https://github.com/RexyGaming/rexy-bridge/blob/main/docs/ue5-setup.md

Here's my starting point — please ask me about anything I haven't filled in:
- My computer: [Mac / Windows / Linux]
- My UE5: [I have UE 5.x installed / I haven't installed UE5 yet]
- My UE5 project: [it's at <path> / I'll create one with your help]
- My controller / hardware: [Rexy Wheels / PS4 controller / Xbox controller / keyboard only / nothing yet]

Here's the high-level workflow we're working through. Please verify each step works 
before moving on, and tell me when you need me to do something in Unreal Engine 
(since you can't drive UE5 directly):

1. Check what I already have installed (Python? Pip? Git?). Install whatever's missing.
2. Download the Rexy Bridge code from GitHub to a sensible folder on my machine.
3. Install the Python dependencies from requirements.txt.
4. Enable the Remote Control plugin in UE5 (you'll guide me).
5. Create the "RexyControl" preset in UE5 and expose at least one property per camera.
6. Find the object paths for my camera and crane (if any) and edit mappings.json.
7. Run the bridge script.
8. Open the app's index.html in my browser.
9. Verify all three status indicators are green (HARDWARE LIVE, WS CONNECTED, UE RC CONNECTED).
10. Help me click "Rescan" and confirm cameras appear.
11. Drag the pan slider in the app and confirm my UE5 camera moves.
12. Help me bind my hardware to the pan/tilt wheels (or sticks) for hands-on control.
13. If I have a Rexy Wheels device, also help me bind it to the appropriate axes.
14. If I have a controller with sticks, help me run the "Null Drift" calibration to 
    cancel stick drift.

How I'd like you to work with me:
- Explain WHAT you're doing as you do it, so I learn — but keep it brief.
- If a step fails, troubleshoot WITH me using the README's Troubleshooting section. 
  Don't just give up and tell me to "check the docs".
- After each major step works, briefly summarise what we just did and what we're 
  doing next.
- If I get confused, just ask me to take a screenshot of what I'm seeing — that's 
  often faster than long explanations.

Don't go ahead until I'm ready. Start by asking me which of the bracketed details 
I want to confirm or change, and then read the README and ue5-setup.md before we 
actually begin.
```

---

## What the user fills in

Before pasting, replace these placeholders:

| Placeholder | Replace with |
|---|---|
| `RexyGaming` (×3) | The GitHub owner / org of the published repo |
| `[Mac / Windows / Linux]` | Your OS |
| `[I have UE 5.x installed / I haven't installed UE5 yet]` | Whichever applies |
| `[it's at <path> / I'll create one with your help]` | Your existing project path, or pick the second option |
| `[Rexy Wheels / PS4 controller / Xbox controller / keyboard only / nothing yet]` | Your input device |

The bracketed phrases inside the prompt are deliberately user-readable so it stays self-explanatory if the user reads it before sending. Claude will ask about anything that's still ambiguous.

## Tips for the recommender

When you tell someone to use Cowork to install Rexy Bridge, point them at:

1. **Download the Claude desktop app** (free tier is fine for a one-off install).
2. **Switch to Cowork mode** (the sliding tray in the desktop app).
3. **Allow file system + shell access** when Claude asks. Pick the folder you want Rexy Bridge installed in.
4. **Paste the prompt above**, filling in the brackets.
5. Follow Claude's lead. The agent can install Python, clone the repo, run the bridge, and verify the connection — typically end-to-end in 15-30 minutes for someone who's never done it before.

If something goes wrong mid-setup, the user can ask Claude to start the relevant section over. Claude has the conversation context so it won't lose progress.

## Power user note

For experienced users who don't need Cowork, the README's Quick Start section + the UE5 setup guide is enough — Cowork is specifically for the "I've never touched a Python file" audience that this prompt is aimed at.
