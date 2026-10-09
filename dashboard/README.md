# Live dashboard

A thin browser front end over `worker.run_task()`, for watching a run happen instead of only
reading its replay afterward. Not part of `worker/` (keeps that package's line budget and
task-agnostic design untouched) and not a replacement for the CLI or `tests/run_scenarios.py` -
just another way to drive the same loop.

```bash
python -m dashboard.app
# open http://localhost:5050
```

Pick a scenario preset (seeds the sandbox and sets the right fault/UI variant automatically) or
type a custom task against whatever's currently in the sandbox. Steps appear live as the worker
takes them. If the worker calls `ask_user` - including the destructive-action approval gate - a
box appears on the page and the run genuinely blocks until you type a reply and submit it; it does
not auto-answer. When the run finishes, the page links to that run's real `report.md` and
`replay.html`.

One run at a time, by design - this is a demo tool, not a scheduler. Requires `GEMINI_API_KEY` set
the same way the CLI needs it (`.env` at the repo root, or exported).
