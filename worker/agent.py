"""The loop: call model, run tool, append observation. ~150 lines by design.

Policy and confidence are enforced by code (policy.py, confidence.py), not by
asking the model to behave - this file just wires the pieces together.
"""
import hashlib
import json
import time

from google.genai import errors, types

from . import tools as toolmod
from .policy import Policy, args_key
from .prompts import SYSTEM_PROMPT

MAX_STEPS = 30
MAX_VERIFIER_ROUNDS = 2
KEEP_SNAPSHOTS = 2
SNAPSHOT_TOOLS = {"browser_open", "browser_snapshot", "browser_click", "browser_type", "browser_select"}

RETRYABLE_CODES = {429, 500, 502, 503, 504}
MIN_CALL_INTERVAL = 4.5  # paces under free-tier's 15 req/min cap; shared across agent + verifier calls
_last_call_at = [0.0]

# Rough, display-only cost estimate (USD per token, flash-tier ballpark), not billing-accurate.
_COST_PER_INPUT_TOKEN = 1e-7
_COST_PER_OUTPUT_TOKEN = 4e-7


def call_with_retries(fn, max_retries=5, base_delay=2.0):
    """Free-tier model capacity is shared, rate-limited (15 req/min on the
    model this defaults to), and occasionally just overloaded (503). Self-pace
    every call, and back off and retry transient 429/5xx instead of dying."""
    for attempt in range(max_retries):
        wait = MIN_CALL_INTERVAL - (time.time() - _last_call_at[0])
        if wait > 0:
            time.sleep(wait)
        _last_call_at[0] = time.time()
        try:
            return fn()
        except errors.APIError as e:
            if getattr(e, "code", None) not in RETRYABLE_CODES or attempt == max_retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))


class HistEntry:
    __slots__ = ("tool", "args_key", "obs_hash")

    def __init__(self, tool, args_key, obs_hash):
        self.tool = tool
        self.args_key = args_key
        self.obs_hash = obs_hash


class RunState:
    def __init__(self, sandbox_root, browser, get_user_reply, run_verifier_fn,
                 max_steps=MAX_STEPS, max_verifier_rounds=MAX_VERIFIER_ROUNDS):
        self.sandbox_root = sandbox_root
        self.browser = browser
        self.max_steps = max_steps
        self.max_verifier_rounds = max_verifier_rounds
        self.define_done_called = False
        self.checklist = []
        self.step_count = 0
        self.notebook = {}
        self.sources = {}
        self.injection_flags = []
        self.ask_user_log = []
        self.destructive_approval = False
        self.pending_confirmation = False
        self.finished = None
        self.verifier_attempts = 0
        self.verifier_result = None
        self.verifier_failed_once = False
        self.verifier_failed_then_passed = False
        self.retried_after_write_error = False
        self.history = []
        self._get_user_reply = get_user_reply
        self._run_verifier_fn = run_verifier_fn

    def get_user_reply(self, question):
        return self._get_user_reply(question)

    def run_verifier(self, summary, proof_url):
        verdict = self._run_verifier_fn(self.checklist, self.notebook, self.sources, proof_url, self.browser)
        if verdict.get("pass"):
            if self.verifier_failed_once:
                self.verifier_failed_then_passed = True
        else:
            self.verifier_failed_once = True
        return verdict

    def consume_destructive_approval(self):
        v = self.destructive_approval
        self.destructive_approval = False
        return v

    def consume_pending_confirmation(self):
        v = self.pending_confirmation
        self.pending_confirmation = False
        return v

    def lowest_unconfirmed_field(self):
        return Policy.lowest_unconfirmed_field(self.notebook)

    def repeat_count(self, tool_name, args):
        key = args_key(args)
        count, last_hash = 0, None
        for entry in reversed(self.history):
            if entry.tool != tool_name or entry.args_key != key:
                break
            if last_hash is None:
                last_hash, count = entry.obs_hash, 1
            elif entry.obs_hash == last_hash:
                count += 1
            else:
                break
        return count

    def record_history(self, tool_name, args, observation_text):
        h = hashlib.sha256(observation_text.encode()).hexdigest()[:16]
        self.history.append(HistEntry(tool_name, args_key(args), h))


def _elide_old_snapshots(contents, snapshot_positions, keep=KEEP_SNAPSHOTS):
    while len(snapshot_positions) > keep:
        pos, tool_name = snapshot_positions.pop(0)
        contents[pos] = types.Content(role="user", parts=[
            types.Part.from_function_response(name=tool_name, response={"content": "[snapshot elided]"})
        ])


def run(client, model, task, today, sandbox_root, browser, proof_url, get_user_reply, run_verifier_fn,
        trace, use_policy=True, max_steps=MAX_STEPS):
    """Runs one task to completion. Returns (state, usage_totals)."""
    policy = Policy(max_steps=max_steps)
    state = RunState(sandbox_root, browser, get_user_reply, run_verifier_fn, max_steps=max_steps)

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(today=today, start_url=proof_url),
        tools=[toolmod.gemini_tool()],
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=f"Task: {task}")])]
    snapshot_positions = []  # [(index into contents, tool_name_at_that_index)]
    usage_totals = {"input_tokens": 0, "output_tokens": 0}
    no_tool_call_strikes = 0

    while state.finished is None:
        resp = call_with_retries(lambda: client.models.generate_content(model=model, contents=contents, config=config))
        usage = resp.usage_metadata
        usage_totals["input_tokens"] += usage.prompt_token_count or 0
        usage_totals["output_tokens"] += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        model_content = resp.candidates[0].content
        contents.append(model_content)

        fc = next((p.function_call for p in model_content.parts if p.function_call is not None), None)
        if fc is None:
            no_tool_call_strikes += 1
            if no_tool_call_strikes >= 3:
                state.finished = {"status": "failed", "summary": "Model stopped calling tools.",
                                   "proof_url": proof_url, "assumptions": ""}
                break
            contents.append(types.Content(role="user",
                             parts=[types.Part(text="Call exactly one tool, including `why`.")]))
            continue
        no_tool_call_strikes = 0

        tool_name, args = fc.name, dict(fc.args)
        why = args.get("why", "")
        state.step_count += 1

        block_reason = policy.before_call(tool_name, args, state) if use_policy else None
        if block_reason is not None:
            label, observation = "BLOCKED", block_reason
            result = {"is_error": True, "content": block_reason}
        else:
            result = toolmod.execute(tool_name, args, state)
            risk = toolmod.TOOL_RISK.get(tool_name, "none")
            if result["is_error"]:
                label = "ERROR"
                if risk == "write":
                    state.retried_after_write_error = True
            else:
                label = "WRITE" if risk == "write" else "OK"
            observation = result["content"]

        state.record_history(tool_name, args, observation)

        screenshot_path = None
        if browser is not None and tool_name in SNAPSHOT_TOOLS and not result["is_error"]:
            screenshot_path = trace.shots_dir / f"step_{state.step_count:03d}.png"
            try:
                browser.screenshot(screenshot_path)
            except Exception:
                screenshot_path = None

        trace.record(state.step_count, tool_name, args, why, label, observation,
                      json.loads(json.dumps(state.notebook, default=str)), screenshot_path)

        contents.append(types.Content(role="user", parts=[types.Part.from_function_response(
            name=tool_name, response={"content": observation, "is_error": result["is_error"]},
        )]))
        if tool_name in SNAPSHOT_TOOLS:
            snapshot_positions.append((len(contents) - 1, tool_name))
            _elide_old_snapshots(contents, snapshot_positions)

        if state.notebook:
            contents.append(types.Content(role="user", parts=[
                types.Part(text=f"Notebook:\n{json.dumps(state.notebook, default=str)}")
            ]))

    return state, usage_totals


def approx_cost_usd(usage_totals):
    return (usage_totals["input_tokens"] * _COST_PER_INPUT_TOKEN
            + usage_totals["output_tokens"] * _COST_PER_OUTPUT_TOKEN)
