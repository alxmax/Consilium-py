"""Unit tests for dialectic mode — voices mocked, no API calls."""
# tested-by: CPYMOD-DIA-001
import json
import unittest
from unittest.mock import patch

CONS_GO = json.dumps({
    "scores": [{"id": "approach_a", "reversibility": "complete", "magnitude": "minor",
                "regression_risk": {"net_concern": 0.2}, "irreversibility_flag": False}]
})
GEN_GO = json.dumps({
    "preferred": "approach_a",
    "options": [{"id": "approach_a"}, {"id": "approach_b"}],
    "abstain": {"triggered": False},
})
CTRL_GO = json.dumps({"glossary_fail": False, "glossary": ["endpoint"], "disagreements": []})

GEN_NOT_PROPOSAL = json.dumps({
    "options": [],
    "abstain": {"triggered": True, "reason": "not_a_proposal"},
})

GEN_GO_WITH_SKETCH = json.dumps({
    "preferred": "approach_a",
    "candidates": [
        {
            "id": "approach_a",
            "summary": "Add a /health endpoint",
            "sketch": "Add a GET /health route returning 200 + version JSON.",
            "rationale": "Smallest change that satisfies the readiness goal.",
        },
    ],
    "abstain": {"triggered": False},
})

CONS_SCALE_DOWN = json.dumps({
    "scores": [{"id": "approach_a", "reversibility": "complete", "magnitude": "trivial",
                "regression_risk": {"net_concern": 0.1}, "irreversibility_flag": False,
                "meta_recommendation": "scale_down"}]
})

SKEPTIC_NO_OBJECTION = json.dumps({
    "can_object": False,
    "objection": None,
    "notes": "chosen aligns with success_criterion; no edge cases visible",
})

SKEPTIC_IN_PLACE = json.dumps({
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Missing input validation on empty payload", "No rate limiting configured"],
        "failure_mode": "correctness",
        "addressable": "in_place",
    },
    "notes": "Fixable with a guard clause.",
})

SKEPTIC_UNADDRESSABLE = json.dumps({
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Violates data-at-rest compliance requirement", "Cannot be rolled back after deploy"],
        "failure_mode": "correctness",
        "addressable": "unaddressable",
    },
    "notes": "No redesign fixes this.",
})


class TestRunDialectic(unittest.TestCase):
    def _run(self, skeptic_text: str, skeptic_can_override: bool = False):
        from consilium.models import DeliberationInput
        from consilium.modes.dialectic import run_dialectic

        # Generator-first execution order: generator, conservator, control
        seq_outputs = iter([GEN_GO, CONS_GO, CTRL_GO])

        def mock_seq(*_a, **_kw):
            return next(seq_outputs)

        with patch("consilium.modes.sequential.call_voice", side_effect=mock_seq), \
             patch("consilium.skeptic.call_voice", return_value=skeptic_text):
            return run_dialectic(
                DeliberationInput(proposal="Add health check endpoint"),
                skeptic_can_override=skeptic_can_override,
            )

    def test_mode_field(self):
        report = self._run(SKEPTIC_NO_OBJECTION)
        self.assertEqual(report.mode, "dialectic")

    def test_four_voices(self):
        report = self._run(SKEPTIC_NO_OBJECTION)
        self.assertEqual(len(report.voices), 4)
        self.assertIn("skeptic", [v.voice for v in report.voices])

    def test_no_objection_stays_go(self):
        report = self._run(SKEPTIC_NO_OBJECTION)
        self.assertEqual(report.verdict, "GO")
        assert report.skeptic is not None
        self.assertFalse(report.skeptic.can_object)

    def test_advisory_in_place_stays_go(self):
        """Advisory (default): in_place objection doesn't change GO verdict."""
        report = self._run(SKEPTIC_IN_PLACE, skeptic_can_override=False)
        self.assertEqual(report.verdict, "GO")
        assert report.skeptic is not None
        self.assertTrue(report.skeptic.can_object)
        skeptic_voice = next(v for v in report.voices if v.voice == "skeptic")
        self.assertEqual(skeptic_voice.vote, "MODIFY")

    def test_override_in_place_downgrades_to_modify(self):
        report = self._run(SKEPTIC_IN_PLACE, skeptic_can_override=True)
        self.assertEqual(report.verdict, "MODIFY")
        # The in_place recommendation must carry the Skeptic's notes, like the
        # unaddressable / requires_redesign branches do.
        self.assertIn("Fixable with a guard clause.", report.recommendation)

    def test_override_unaddressable_blocks(self):
        report = self._run(SKEPTIC_UNADDRESSABLE, skeptic_can_override=True)
        self.assertEqual(report.verdict, "BLOCK")
        self.assertAlmostEqual(report.confidence, 0.1)

    def test_advisory_unaddressable_stays_go(self):
        """Advisory: unaddressable doesn't override without --skeptic-can-override."""
        report = self._run(SKEPTIC_UNADDRESSABLE, skeptic_can_override=False)
        self.assertEqual(report.verdict, "GO")

    def _run_custom(self, gen: str, cons: str, ctrl: str, skeptic_text: str):
        from consilium.models import DeliberationInput
        from consilium.modes.dialectic import run_dialectic

        seq_outputs = iter([gen, cons, ctrl])
        with patch("consilium.modes.sequential.call_voice", side_effect=lambda *_a, **_kw: next(seq_outputs)), \
             patch("consilium.skeptic.call_voice", return_value=skeptic_text):
            return run_dialectic(DeliberationInput(proposal="Add health check endpoint"))

    def test_chosen_fields_preserved(self):
        """Regression (audit 2026-07-01): the dialectic rebuild dropped
        chosen_summary/chosen_sketch/chosen_rationale, so the CLI's
        'How to implement' section never rendered in dialectic mode."""
        report = self._run_custom(GEN_GO_WITH_SKETCH, CONS_GO, CTRL_GO, SKEPTIC_NO_OBJECTION)
        self.assertEqual(report.chosen, "approach_a")
        self.assertEqual(report.chosen_summary, "Add a /health endpoint")
        self.assertIn("GET /health", report.chosen_sketch or "")
        self.assertIn("readiness goal", report.chosen_rationale or "")

    def test_skeptic_receives_chosen_candidate_details(self):
        """Bug #6 (audit 2026-07-01): the Skeptic challenged the raw proposal;
        it must receive the chosen candidate's summary/sketch/rationale."""
        from consilium.models import DeliberationInput
        from consilium.modes.dialectic import run_dialectic

        seq_outputs = iter([GEN_GO_WITH_SKETCH, CONS_GO, CTRL_GO])
        with patch("consilium.modes.sequential.call_voice", side_effect=lambda *_a, **_kw: next(seq_outputs)), \
             patch("consilium.skeptic.call_voice", return_value=SKEPTIC_NO_OBJECTION) as mock_call:
            run_dialectic(DeliberationInput(proposal="Add health check endpoint"))

        user_msg = mock_call.call_args.args[2]
        self.assertIn("Add a /health endpoint", user_msg)
        self.assertIn("GET /health", user_msg)

    def test_scale_down_reason_preserved(self):
        """Regression (audit 2026-07-01): dropping reason='scale_down' meant
        deliberate() never swapped in the real short response, leaking the
        'max 2 sentences' instruction text to the user."""
        report = self._run_custom(GEN_GO, CONS_SCALE_DOWN, CTRL_GO, SKEPTIC_NO_OBJECTION)
        self.assertEqual(report.mode, "dialectic")
        self.assertEqual(report.reason, "scale_down")

    def test_block_skips_skeptic(self):
        """AC4: a not_a_proposal BLOCK from sequential skips the Skeptic entirely."""
        from consilium.models import DeliberationInput
        from consilium.modes.dialectic import run_dialectic

        seq_outputs = iter([GEN_NOT_PROPOSAL, CONS_GO, CTRL_GO])
        skeptic_calls = []

        def mock_seq(*_a, **_kw):
            return next(seq_outputs)

        def mock_skeptic(*_a, **_kw):
            skeptic_calls.append(1)
            return SKEPTIC_NO_OBJECTION

        with patch("consilium.modes.sequential.call_voice", side_effect=mock_seq), \
             patch("consilium.skeptic.call_voice", side_effect=mock_skeptic):
            report = run_dialectic(DeliberationInput(proposal="weather in Suceava?"))

        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.mode, "dialectic")
        self.assertEqual(len(skeptic_calls), 0)
        self.assertEqual(len(report.voices), 3)
        self.assertIsNone(report.skeptic)


if __name__ == "__main__":
    unittest.main()
