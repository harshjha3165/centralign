"""Policy lives in code, not in the prompt: the prompt asks nicely, this enforces.

Pure(ish) gate: before_call(tool_name, args, state) returns None if the call
may proceed, or a string explaining why it's blocked. A poisoned document can
override the prompt; it can't override this.
"""
import json
from urllib.parse import urlparse

from .confidence import AFFIRMATIVE_REPLIES, field_score

WRITE_TOOLS = {"browser_click", "browser_type", "browser_select"}
STUCK_THRESHOLD = 3
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


class PolicyError(Exception):
    pass


def check_domain(url):
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise PolicyError(f'URL "{url}" is not on the allowlist (localhost only).')


def check_path(sandbox_root, path):
    resolved = (sandbox_root / path).resolve()
    root = sandbox_root.resolve()
    if root != resolved and root not in resolved.parents:
        raise PolicyError(f'Path "{path}" resolves outside the sandbox and is blocked.')
    return resolved


def args_key(args):
    return json.dumps(args, sort_keys=True, default=str)


class Policy:
    def __init__(self, max_steps=30):
        self.max_steps = max_steps

    def before_call(self, tool_name, args, state):
        if not state.define_done_called and tool_name != "define_done":
            return "define_done must be called first, before any other tool."

        if state.step_count >= self.max_steps and tool_name not in ("finish", "ask_user"):
            return (f"Step budget ({self.max_steps}) reached. Call finish() with status "
                    "'failed' or 'needs_input' and say exactly what is and isn't done.")

        if tool_name not in ("ask_user", "finish") and state.repeat_count(tool_name, args) >= STUCK_THRESHOLD:
            return (f"The exact same {tool_name} call has produced the same result "
                    f"{STUCK_THRESHOLD} times in a row. Try a genuinely different approach, "
                    "or call ask_user / finish(failed).")

        if tool_name in WRITE_TOOLS:
            low = state.lowest_unconfirmed_field()
            if low is not None:
                key, score = low
                return f'Low-confidence fact: "{key}" (field score {score}). Ask the user before writing.'

        if tool_name == "browser_click":
            try:
                risk = state.browser.element_risk(args.get("id")) if state.browser else ""
            except Exception:
                # An invalid/stale id: let the click itself raise and explain that,
                # rather than crashing the policy check over it.
                risk = ""
            if risk == "destructive" and not state.consume_destructive_approval():
                return ('This click targets a destructive action (data-risk="destructive"). Call '
                        "ask_user with a plain-words description of exactly what will happen and "
                        "that it cannot be undone. Retry this click only if the user approves.")

        if tool_name == "browser_open":
            try:
                check_domain(args.get("url", ""))
            except PolicyError as e:
                return str(e)

        if tool_name in ("list_files", "read_file"):
            path = args.get("path") or args.get("dir") or "."
            try:
                check_path(state.sandbox_root, path)
            except PolicyError as e:
                return str(e)

        return None

    @staticmethod
    def lowest_unconfirmed_field(notebook):
        worst = None
        for key, entry in notebook.items():
            if entry.get("confirmed_by_user"):
                continue
            score, _ = field_score(entry)
            if score < 60 and (worst is None or score < worst[1]):
                worst = (key, score)
        return worst

    @staticmethod
    def is_affirmative(reply):
        return reply.strip().lower() in AFFIRMATIVE_REPLIES
