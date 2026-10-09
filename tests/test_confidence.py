"""Unit tests for confidence.py. No API key, no browser. Runs in under a second."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.confidence import band_for, field_score, run_score


def entry(**kw):
    base = {"value": "x", "raw_text": "x", "source": "s", "kind": "observed", "ambiguity": "none",
            "confirmed_by_user": False}
    base.update(kw)
    return base


class TestFieldScore(unittest.TestCase):
    def test_verbatim_no_ambiguity(self):
        score, _ = field_score(entry(rechecked=True))
        self.assertEqual(score, 100)

    def test_several_candidates_resolved(self):
        score, _ = field_score(entry(ambiguity="resolved", rechecked=True))
        self.assertEqual(score, 85)

    def test_computed(self):
        score, _ = field_score(entry(kind="computed", rechecked=True))
        self.assertEqual(score, 75)

    def test_format_ambiguous_guessed(self):
        score, _ = field_score(entry(ambiguity="guessed", rechecked=True))
        self.assertEqual(score, 50)

    def test_resolved_by_user_overrides_ambiguity_cap(self):
        score, _ = field_score(entry(ambiguity="guessed", confirmed_by_user=True, rechecked=True))
        self.assertEqual(score, 100)

    def test_verifier_not_ok_is_zero(self):
        score, _ = field_score(entry(verifier_check="not_ok", rechecked=True))
        self.assertEqual(score, 0)

    def test_verifier_unconfirmed_caps_60(self):
        score, _ = field_score(entry(verifier_check="unconfirmed", rechecked=True))
        self.assertEqual(score, 60)

    def test_not_rechecked_caps_70(self):
        score, _ = field_score(entry(rechecked=False))
        self.assertEqual(score, 70)

    def test_caps_combine_to_lowest(self):
        # computed (75) AND not rechecked (70) -> lowest applies
        score, _ = field_score(entry(kind="computed", rechecked=False))
        self.assertEqual(score, 70)


class TestBand(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(band_for(100), "High")
        self.assertEqual(band_for(90), "High")
        self.assertEqual(band_for(89), "Medium")
        self.assertEqual(band_for(60), "Medium")
        self.assertEqual(band_for(59), "Low")
        self.assertEqual(band_for(0), "Low")


class TestRunScore(unittest.TestCase):
    def test_run_score_is_min_not_mean(self):
        notebook = {
            "a": entry(rechecked=True),               # 100
            "b": entry(kind="computed", rechecked=True),  # 75
            "c": entry(ambiguity="guessed", rechecked=True),  # 50
        }
        result = run_score(notebook, verifier_pass=True)
        self.assertEqual(result["score"], 50)
        self.assertNotEqual(result["score"], round((100 + 75 + 50) / 3))

    def test_verifier_not_passed_forces_zero(self):
        notebook = {"a": entry(rechecked=True)}
        result = run_score(notebook, verifier_pass=False)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["band"], "Low")

    def test_run_caps_apply(self):
        notebook = {"a": entry(rechecked=True)}
        result = run_score(notebook, verifier_pass=True, db_diff_outside_dod=True)
        self.assertEqual(result["score"], 50)

    def test_step_budget_cap(self):
        notebook = {"a": entry(rechecked=True)}
        result = run_score(notebook, verifier_pass=True, steps_used=25, step_budget=30)
        self.assertEqual(result["score"], 85)

    def test_empty_notebook_defaults_to_100_before_other_caps(self):
        result = run_score({}, verifier_pass=True)
        self.assertEqual(result["score"], 100)


if __name__ == "__main__":
    unittest.main()
