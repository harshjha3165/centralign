"""trace.jsonl, screenshots, notebook.json, report.md, replay.html.

The report and replay are built FROM trace.jsonl + the verifier output + the
DB diff - never from the model's own recollection (trap #10).
"""
import base64
import html
import json
from pathlib import Path


class Trace:
    def __init__(self, run_dir, on_step=None):
        self.run_dir = Path(run_dir)
        self.shots_dir = self.run_dir / "screenshots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.run_dir / "trace.jsonl"
        self.jsonl_path.write_text("")
        self.steps = []
        self.on_step = on_step  # optional callback(entry), e.g. for a live UI; never required.

    def record(self, step, tool, args, why, label, observation, notebook_snapshot, screenshot_path=None):
        entry = {
            "step": step,
            "tool": tool,
            "args": args,
            "why": why,
            "label": label,
            "observation": observation,
            "notebook": notebook_snapshot,
            "screenshot": str(Path(screenshot_path).relative_to(self.run_dir)) if screenshot_path else None,
        }
        self.steps.append(entry)
        with open(self.jsonl_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        if self.on_step:
            self.on_step(entry)
        return entry


def write_notebook(run_dir, notebook):
    (Path(run_dir) / "notebook.json").write_text(json.dumps(notebook, indent=2, default=str))


def _short(text, limit=160):
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _checklist_rows(checklist, verifier_result):
    checks = {c.get("item"): c for c in (verifier_result or {}).get("checks", [])}
    rows = []
    for item in checklist:
        check = checks.get(item)
        if check is not None:
            mark = "[x]" if check.get("ok") else "[ ]"
            detail = f"expected: {_short(check.get('expected'))!r}, actual: {_short(check.get('actual'))!r}"
        else:
            mark = "[ ]"
            detail = "not checked by the verifier"
        rows.append(f"- {mark} {item} ({detail})")
    return "\n".join(rows)


def _field_table(confidence_result, notebook):
    lines = ["| Field | Value | Source | Confidence | Why |", "|---|---|---|---|---|"]
    for key, f in confidence_result.get("fields", {}).items():
        entry = notebook.get(key, {})
        lines.append(f"| {key} | {entry.get('value', '')} | {entry.get('source', '')} | "
                      f"{f['score']} | {f['why']} |")
    return "\n".join(lines)


def write_report(run_dir, *, task, status, checklist, verifier_result, confidence_result,
                  dbdiff_summary, notebook, ask_user_log, injection_flags, assumptions,
                  steps_used, wall_time_s, approx_cost_usd, replay_name="replay.html"):
    run_dir = Path(run_dir)
    band = confidence_result["band"]
    score = confidence_result["score"]

    doubt = []
    for key, entry in notebook.items():
        if entry.get("kind") == "computed":
            doubt.append(f"`{key}` was computed, not read verbatim.")
    if assumptions:
        doubt.append(f"Assumptions stated: {assumptions}")
    for c in (verifier_result or {}).get("checks", []):
        if not c.get("ok"):
            doubt.append(f"Verifier could not confirm: {c.get('item')}")
    if injection_flags:
        doubt.append(f"Suspicious embedded-instruction text was found and ignored: {injection_flags}")
    if not doubt:
        doubt.append("Nothing flagged.")

    report = f"""# Run report

**Task:** {task}
**Status:** {status}
**Confidence:** {band} ({score}/100)
**Steps:** {steps_used} **Wall time:** {wall_time_s:.1f}s **Approx. cost:** ${approx_cost_usd:.4f}

## Definition of done
{_checklist_rows(checklist, verifier_result)}

## Fields
{_field_table(confidence_result, notebook)}

## Verifier
Pass: {verifier_result.get('pass') if verifier_result else 'not run'}
Problems: {verifier_result.get('problems') if verifier_result else []}

## DB diff
{dbdiff_summary}

## Doubt list
{chr(10).join('- ' + d for d in doubt)}

## Assumptions
{assumptions or '(none stated)'}

## User interactions
{chr(10).join(f"- Q: {a['question']}  A: {a['reply']}" for a in ask_user_log) or '(none)'}

## Receipts
- Full trace: `trace.jsonl`
- Notebook: `notebook.json`
- Replay: [{replay_name}]({replay_name})
"""
    (run_dir / "report.md").write_text(report)
    return report


_REPLAY_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "replay.html"


def write_replay(run_dir, *, task, status, confidence_result, checklist, verifier_result,
                  dbdiff_summary, steps, wall_time_s):
    run_dir = Path(run_dir)
    step_payload = []
    row_html = []
    for i, step in enumerate(steps):
        label = step["label"]
        css = {"OK": "ok", "WRITE": "warn", "BLOCKED": "bad", "ERROR": "bad"}.get(label, "")
        row_html.append(
            f'<tr data-idx="{i}"><td>{step["step"]}</td><td>{html.escape(str(step["tool"]))}</td>'
            f'<td>{html.escape(str(step["why"]))}</td><td class="{css}">{label}</td></tr>'
        )
        shot_b64 = ""
        shot_path = step.get("screenshot")
        if shot_path:
            full = run_dir / shot_path
            if full.exists():
                shot_b64 = base64.b64encode(full.read_bytes()).decode("ascii")
        step_payload.append({"notebook": step.get("notebook", {}), "screenshot_b64": shot_b64})

    tokens = {
        "__TASK_TITLE__": html.escape(task)[:80],
        "__STATUS__": html.escape(status),
        "__BAND__": confidence_result["band"],
        "__SCORE__": str(confidence_result["score"]),
        "__NUM_STEPS__": str(len(steps)),
        "__WALL_TIME__": f"{wall_time_s:.1f}",
        "__CHECKLIST_TEXT__": html.escape("\n".join(f"- {c}" for c in checklist)),
        "__MAX_INDEX__": str(max(len(steps) - 1, 0)),
        "__STEP_ROWS__": "\n".join(row_html),
        "__VERIFIER_TEXT__": html.escape(
            json.dumps(verifier_result, indent=2, default=str) if verifier_result else "not run"
        ),
        "__CONFIDENCE_TEXT__": html.escape(json.dumps(confidence_result, indent=2, default=str)),
        "__DBDIFF_TEXT__": html.escape(dbdiff_summary),
        # Embedded in a <script> block, not a <pre>: guard against a literal "</script"
        # inside some page/file text ending the script tag early, not against HTML display.
        "__STEPS_JSON__": json.dumps(step_payload).replace("</script", "<\\/script"),
    }
    page_html = _REPLAY_TEMPLATE_PATH.read_text()
    for token, value in tokens.items():
        page_html = page_html.replace(token, value)
    (run_dir / "replay.html").write_text(page_html)
    return page_html
