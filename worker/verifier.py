"""The independent 'skeptical reviewer'. Fresh context: it gets the frozen
checklist, the notebook, source file text, and a FRESH page load of
proof_url opened in its own browser - never the agent's history or its
own belief that it succeeded.
"""
import json
import re

from google.genai import types

from .agent import call_with_retries
from .prompts import VERIFIER_PROMPT


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.S)
    return match.group(0) if match else text


def run_verification(client, model, checklist, notebook, sources, proof_url, browser):
    """browser: the agent's already-running Browser (see Browser.open_fresh);
    the verifier opens a brand-new incognito context from it, never the
    agent's own session, and never its history or reasoning."""
    try:
        snapshot_text = browser.open_fresh(proof_url)
    except Exception as e:
        return {"pass": False, "checks": [], "problems": [f"Could not open proof_url fresh: {e}"]}

    prompt = VERIFIER_PROMPT.format(
        checklist="\n".join(f"- {c}" for c in checklist),
        notebook=json.dumps(notebook, indent=2, default=str),
        sources=json.dumps(sources, indent=2)[:6000],
        proof_url=proof_url,
        snapshot=snapshot_text,
    )
    resp = call_with_retries(lambda: client.models.generate_content(
        model=model, contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
    ))
    text = "".join(p.text for p in resp.candidates[0].content.parts if p.text)
    try:
        data = json.loads(_extract_json(text))
    except Exception:
        return {"pass": False, "checks": [], "problems": [f"Verifier response was not valid JSON: {text[:300]!r}"]}
    data.setdefault("pass", False)
    data.setdefault("checks", [])
    data.setdefault("problems", [])
    return data
