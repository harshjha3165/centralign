"""Pure functions: notebook + run facts -> field scores, run score, band.

No side effects, no API calls. The model never states confidence; this is
computed from what actually happened and is the only place that happens.
"""

AFFIRMATIVE_REPLIES = {"yes", "y", "approve", "approved", "ok", "okay", "sure", "go ahead", "confirmed"}


def band_for(score):
    if score >= 90:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def field_score(entry):
    """entry: value/raw_text/source/kind/ambiguity/confirmed_by_user/verifier_check/rechecked."""
    score = 100
    reasons = []

    if entry.get("confirmed_by_user"):
        reasons.append("100: resolved by the user via ask_user")
    else:
        ambiguity = entry.get("ambiguity", "none")
        if ambiguity == "resolved":
            score = min(score, 85)
            reasons.append("cap 85: several candidates seen, one chosen")
        elif ambiguity == "guessed":
            score = min(score, 50)
            reasons.append("cap 50: ambiguous and guessed, not resolved")
        if entry.get("kind") == "computed":
            score = min(score, 75)
            reasons.append("cap 75: computed, not read verbatim")

    verifier_check = entry.get("verifier_check")
    if verifier_check == "not_ok":
        score = min(score, 0)
        reasons.append("cap 0: verifier check not ok")
    elif verifier_check == "unconfirmed":
        score = min(score, 60)
        reasons.append("cap 60: verifier could not confirm")

    if not entry.get("rechecked", True):
        score = min(score, 70)
        reasons.append("cap 70: not independently re-read after the write")

    if not reasons:
        reasons.append("100: read verbatim, label matched exactly")

    return max(0, score), "; ".join(reasons)


def run_score(notebook, verifier_pass, retried_after_error=False, verifier_failed_then_passed=False,
              steps_used=0, step_budget=30, db_diff_outside_dod=False, injection_flagged=False):
    fields = {}
    for key, raw_entry in notebook.items():
        entry = dict(raw_entry)
        entry.setdefault("rechecked", bool(verifier_pass))
        score, why = field_score(entry)
        fields[key] = {"score": score, "why": why}

    base = min((f["score"] for f in fields.values()), default=100)
    caps = []

    def cap(value, reason):
        nonlocal base
        if value < base:
            base = value
        caps.append(reason)

    if not verifier_pass:
        cap(0, "run cap 0: verifier has not passed")
    if db_diff_outside_dod:
        cap(50, "run cap 50: DB diff shows a change outside the Definition of Done")
    if injection_flagged:
        cap(80, "run cap 80: injection text flagged in an input")
    if retried_after_error:
        cap(85, "run cap 85: a write was retried after an error")
    if verifier_failed_then_passed:
        cap(85, "run cap 85: verifier failed once, then passed on retry")
    if step_budget and steps_used / step_budget > 0.7:
        cap(85, "run cap 85: more than 70% of the step budget was used")

    base = max(0, min(100, base))
    return {"score": base, "band": band_for(base), "fields": fields, "run_caps": caps}
