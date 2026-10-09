"""CLI: python -m worker "<task>" [--no-verifier] [--no-policy]

run_task() is the reusable core (also used by dashboard/app.py to drive a
live UI); main() is just argument parsing and printing around it.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from google import genai

from . import agent, confidence, dbdiff as dbdiff_mod, trace as trace_mod, verifier as verifier_mod
from .browser import Browser

ROOT = Path(__file__).resolve().parent.parent
# Which sandbox app's DB to diff. Config, not worker/ logic: a different sandbox
# just points this env var elsewhere; no code here knows what the app is.
DB_PATH = Path(os.environ.get("WORKER_DB_PATH", ROOT / "sandbox" / "ledger_app" / "ledger.db"))


def load_dotenv():
    """Minimal .env loader so GEMINI_API_KEY doesn't need exporting by hand.
    Never overrides an already-set env var (e.g. one run_scenarios.py set)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _today():
    return os.environ.get("WORKER_TODAY") or datetime.now(timezone.utc).date().isoformat()


def _cli_reply(question):
    print(f"\n[ask_user] {question}")
    return input("> ")


def _scripted_reply(replies):
    queue = list(replies)

    def _reply(question):
        if not queue:
            raise RuntimeError("Ran out of scripted ask_user replies for this scenario.")
        reply = queue.pop(0)
        print(f"[ask_user - scripted] {question} -> {reply!r}")
        return reply

    return _reply


def run_task(task, *, run_id=None, proof_url="http://localhost:8000/", no_verifier=False, no_policy=False,
             get_user_reply=None, on_step=None):
    """Runs one task to completion and writes runs/<run_id>/*. Returns
    (state, result_summary, run_dir). Shared by the CLI and dashboard/app.py -
    the only two differences between callers are how a reply/step is surfaced,
    passed in as get_user_reply/on_step rather than hardcoded here."""
    load_dotenv()
    model = os.environ.get("WORKER_MODEL", "gemini-3.1-flash-lite")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    today = _today()

    if get_user_reply is None:
        replies_env = os.environ.get("WORKER_SCRIPTED_REPLIES")
        get_user_reply = _scripted_reply(json.loads(replies_env)) if replies_env else _cli_reply

    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = ROOT / "runs" / run_id
    tracer = trace_mod.Trace(run_dir, on_step=on_step)

    diff_tracker = dbdiff_mod.DBDiff(DB_PATH)
    diff_tracker.capture_before()

    browser = Browser(headless=True)

    def run_verifier_fn(checklist, notebook, sources, proof_url_, browser_):
        if no_verifier:
            return {
                "pass": True,
                "checks": [{"item": c, "expected": "n/a", "actual": "n/a", "ok": True} for c in checklist],
                "problems": ["ABLATION RUN: verifier disabled (--no-verifier)."],
            }
        return verifier_mod.run_verification(client, model, checklist, notebook, sources, proof_url_, browser_)

    start = time.time()
    try:
        state, usage = agent.run(
            client, model, task, today, ROOT / "sandbox", browser, proof_url,
            get_user_reply, run_verifier_fn, tracer, use_policy=not no_policy,
        )
    finally:
        browser.close()
    wall_time = time.time() - start

    diff = diff_tracker.diff_now()
    dbdiff_summary = dbdiff_mod.summarize(diff)
    outside_dod = dbdiff_mod.is_outside_definition_of_done(diff)

    status = state.finished["status"]
    verifier_pass = status == "success"
    confidence_result = confidence.run_score(
        state.notebook,
        verifier_pass=verifier_pass,
        retried_after_error=state.retried_after_write_error,
        verifier_failed_then_passed=state.verifier_failed_then_passed,
        steps_used=state.step_count,
        step_budget=state.max_steps,
        db_diff_outside_dod=outside_dod,
        injection_flagged=bool(state.injection_flags),
    )

    band = confidence_result["band"]
    if no_verifier or no_policy:
        confidence_result["run_caps"].append("ABLATION RUN: excluded from calibration.")

    trace_mod.write_notebook(run_dir, state.notebook)
    trace_mod.write_report(
        run_dir, task=task, status=status, checklist=state.checklist,
        verifier_result=state.verifier_result, confidence_result=confidence_result,
        dbdiff_summary=dbdiff_summary, notebook=state.notebook, ask_user_log=state.ask_user_log,
        injection_flags=state.injection_flags, assumptions=state.finished.get("assumptions", ""),
        steps_used=state.step_count, wall_time_s=wall_time, approx_cost_usd=agent.approx_cost_usd(usage),
    )
    result_summary = {
        "status": status,
        "band": band,
        "score": confidence_result["score"],
        "steps": state.step_count,
        "wall_time_s": wall_time,
        "approx_cost_usd": agent.approx_cost_usd(usage),
        "summary": state.finished.get("summary", ""),
        "assumptions": state.finished.get("assumptions", ""),
        "ask_user_log": state.ask_user_log,
        "injection_flags": state.injection_flags,
        "checklist": state.checklist,
        "define_done_first": bool(tracer.steps) and tracer.steps[0]["tool"] == "define_done",
        "verifier_result": state.verifier_result,
        "db_diff": diff,
        "ablation": bool(no_verifier or no_policy),
        "no_verifier": no_verifier,
        "no_policy": no_policy,
    }
    (run_dir / "result.json").write_text(json.dumps(result_summary, indent=2, default=str))

    trace_mod.write_replay(
        run_dir, task=task, status=status, confidence_result=confidence_result,
        checklist=state.checklist, verifier_result=state.verifier_result, dbdiff_summary=dbdiff_summary,
        steps=tracer.steps, wall_time_s=wall_time,
    )

    return state, result_summary, run_dir


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m worker")
    parser.add_argument("task")
    parser.add_argument("--no-verifier", action="store_true", help="Ablation: skip the verifier gate.")
    parser.add_argument("--no-policy", action="store_true", help="Ablation: skip the policy gate.")
    parser.add_argument("--proof-url", default="http://localhost:8000/")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    state, result_summary, run_dir = run_task(
        args.task, run_id=args.run_id, proof_url=args.proof_url,
        no_verifier=args.no_verifier, no_policy=args.no_policy,
    )

    status, band = result_summary["status"], result_summary["band"]
    print(f"\nStatus: {status}")
    print(f"Confidence: {band.upper()}" + (" (see Double-check list)" if band == "Medium" else
          " (please review before relying on this)" if band == "Low" else ""))
    print(f"Summary: {result_summary['summary']}")
    if result_summary.get("assumptions"):
        print(f"Assumptions: {result_summary['assumptions']}")
    if result_summary["injection_flags"]:
        print(f"Suspicious content flagged and ignored: {result_summary['injection_flags']}")
    print(f"Steps: {result_summary['steps']}  Wall time: {result_summary['wall_time_s']:.1f}s  "
          f"Approx. cost: ${result_summary['approx_cost_usd']:.4f}")
    print(f"Report: {run_dir / 'report.md'}")

    return 0 if status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
