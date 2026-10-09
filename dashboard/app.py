"""A thin live front end over worker.run_task(), for demoing.

Not part of worker/ (keeps that package's line budget and task-agnostic
design untouched) and not a replacement for the CLI or tests/run_scenarios.py
- just a browser view of the same loop, with a text box for the task and a
live feed of its steps. One run at a time, by design: this is a demo tool,
not a scheduler.
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import yaml
from flask import Flask, Response, redirect, render_template, request, send_from_directory, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker.__main__ import run_task  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
RUNS_DIR = ROOT / "runs"
PY = sys.executable

app = Flask(__name__)


def _auth_ok():
    """HTTP Basic Auth gate. If DASHBOARD_USER/DASHBOARD_PASS aren't set,
    auth is skipped - fine for local use, not fine for a public deployment
    (this dashboard has no rate limiting beyond "one run at a time" and
    whatever your API key's own quota enforces)."""
    user, pw = os.environ.get("DASHBOARD_USER"), os.environ.get("DASHBOARD_PASS")
    if not user or not pw:
        return True
    auth = request.authorization
    return bool(auth and auth.username == user and auth.password == pw)


@app.before_request
def require_auth():
    if not _auth_ok():
        return Response("Authentication required.", 401,
                         {"WWW-Authenticate": 'Basic realm="CentrAlign Dashboard"'})


STATE_LOCK = threading.Lock()
RUNS = {}  # run_id -> {steps, done, result, error, pending_question, reply_queue}
CURRENT_RUN_ID = {"value": None}
LEDGER = {"proc": None, "fault": None, "ui_variant": None}


def _port_busy(port=8000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def _wait_for_server(url="http://localhost:8000/", timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def ensure_ledger(fault, ui_variant):
    """FAULT/UI_VARIANT are read once at Flask startup (sandbox/ledger_app/app.py),
    so changing either means restarting the server, not just reseeding."""
    if LEDGER["proc"] is not None and LEDGER["proc"].poll() is None:
        if LEDGER["fault"] == fault and LEDGER["ui_variant"] == ui_variant:
            return
        LEDGER["proc"].terminate()
        LEDGER["proc"].wait(timeout=10)
    elif _port_busy():
        return  # something's already on :8000 that we don't own; leave it alone
    env = dict(os.environ)
    env["FAULT"], env["UI_VARIANT"] = fault, ui_variant
    proc = subprocess.Popen([PY, "-m", "sandbox.ledger_app"], cwd=ROOT, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait_for_server():
        raise RuntimeError("Ledger app did not start.")
    LEDGER.update(proc=proc, fault=fault, ui_variant=ui_variant)


def list_scenarios():
    specs = []
    for p in sorted(TASKS_DIR.glob("*.yaml")):
        spec = yaml.safe_load(p.read_text())
        specs.append({"id": spec["id"], "task": spec["task"]})
    return specs


def dashboard_reply(run_id):
    """Builds the get_user_reply callable for one run: blocks the worker
    thread until a human answers via POST /run/<id>/reply, instead of
    reading stdin or a scripted queue."""
    reply_q = queue.Queue()
    RUNS[run_id]["reply_queue"] = reply_q

    def _reply(question):
        RUNS[run_id]["pending_question"] = question
        answer = reply_q.get()
        RUNS[run_id]["pending_question"] = None
        return answer

    return _reply


@app.route("/")
def index():
    with STATE_LOCK:
        current = CURRENT_RUN_ID["value"]
        current_done = RUNS.get(current, {}).get("done", True) if current else True
    scenarios = list_scenarios()
    return render_template(
        "index.html", scenarios=scenarios, current_run_id=current, current_done=current_done,
        scenarios_json=json.dumps({s["id"]: s["task"] for s in scenarios}),
    )


@app.route("/start", methods=["POST"])
def start():
    with STATE_LOCK:
        current = CURRENT_RUN_ID["value"]
        if current and not RUNS.get(current, {}).get("done", True):
            return redirect(url_for("run_page", run_id=current))

    scenario_id = request.form.get("scenario", "").strip()
    task_text = request.form.get("task", "").strip()
    no_verifier = request.form.get("no_verifier") == "on"
    no_policy = request.form.get("no_policy") == "on"
    today_override, fault, ui_variant = None, "none", "a"

    if scenario_id:
        spec = yaml.safe_load((TASKS_DIR / f"{scenario_id}.yaml").read_text())
        task_text = task_text or spec["task"]
        fault = spec.get("fault", "none")
        ui_variant = spec.get("ui_variant", "a")
        today_override = spec.get("today_override")
        subprocess.run([PY, "-m", "sandbox.seed", scenario_id], cwd=ROOT, check=True,
                        capture_output=True, text=True)

    if not task_text:
        return redirect(url_for("index"))

    ensure_ledger(fault, ui_variant)

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-dashboard"
    RUNS[run_id] = {"steps": [], "done": False, "result": None, "error": None,
                     "pending_question": None, "reply_queue": None}
    with STATE_LOCK:
        CURRENT_RUN_ID["value"] = run_id

    get_user_reply = dashboard_reply(run_id)

    def on_step(entry):
        RUNS[run_id]["steps"].append(entry)

    def worker_thread():
        prior_today = os.environ.get("WORKER_TODAY")
        try:
            if today_override:
                os.environ["WORKER_TODAY"] = today_override
            _, result_summary, _ = run_task(
                task_text, run_id=run_id, no_verifier=no_verifier, no_policy=no_policy,
                get_user_reply=get_user_reply, on_step=on_step,
            )
            RUNS[run_id]["result"] = result_summary
        except Exception as e:
            RUNS[run_id]["error"] = f"{type(e).__name__}: {e}"
        finally:
            RUNS[run_id]["done"] = True
            if today_override:
                if prior_today is not None:
                    os.environ["WORKER_TODAY"] = prior_today
                else:
                    os.environ.pop("WORKER_TODAY", None)

    threading.Thread(target=worker_thread, daemon=True).start()
    return redirect(url_for("run_page", run_id=run_id))


@app.route("/run/<run_id>")
def run_page(run_id):
    if run_id not in RUNS:
        return redirect(url_for("index"))
    return render_template("run.html", run_id=run_id)


@app.route("/run/<run_id>/reply", methods=["POST"])
def reply(run_id):
    run = RUNS.get(run_id)
    if run and run.get("reply_queue") is not None:
        run["reply_queue"].put(request.form.get("answer", ""))
    return ("", 204)


@app.route("/stream/<run_id>")
def stream(run_id):
    def gen():
        sent, last_question = 0, None
        while True:
            run = RUNS.get(run_id)
            if run is None:
                yield "event: done\ndata: {}\n\n"
                return
            steps = run["steps"]
            while sent < len(steps):
                yield f"data: {json.dumps(steps[sent], default=str)}\n\n"
                sent += 1
            if run["pending_question"] and run["pending_question"] != last_question:
                last_question = run["pending_question"]
                yield f"event: ask_user\ndata: {json.dumps({'question': last_question})}\n\n"
            if run["done"]:
                yield f"event: done\ndata: {json.dumps({'result': run['result'], 'error': run['error']}, default=str)}\n\n"
                return
            time.sleep(0.4)
    return Response(gen(), mimetype="text/event-stream")


@app.route("/runs/<run_id>/<path:filename>")
def run_file(run_id, filename):
    return send_from_directory(RUNS_DIR / run_id, filename)


@app.route("/reset", methods=["POST"])
def reset():
    with STATE_LOCK:
        CURRENT_RUN_ID["value"] = None
    return redirect(url_for("index"))


if __name__ == "__main__":
    # 0.0.0.0 so this is reachable from outside a container; local-only use is
    # still safe since nothing routes to your machine from the internet unless
    # you deploy it. PORT is read for hosts (Render, etc.) that assign one.
    host = "127.0.0.1" if not os.environ.get("PORT") else "0.0.0.0"
    port = int(os.environ.get("PORT", 5050))
    app.run(host=host, port=port, debug=False, threaded=True)
