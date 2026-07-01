"""Unit tests for sequential mode — voices mocked, no API calls."""
# tested-by: CPYMOD-SEQ-001
# tested-by: CPYBUS-AGG-001
import json
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURE_DIR = Path(__file__).parent / "fixtures"

CONS_GO = json.dumps({
    "scores": [
        {
            "id": "approach_a",
            "reversibility": "complete",
            "magnitude": "minor",
            "regression_risk": {"net_concern": 0.2, "magnitude": "minor"},
            "irreversibility_flag": False,
        }
    ]
})

GEN_GO = json.dumps({
    "preferred": "approach_a",
    "options": [
        {"id": "approach_a", "description": "Primary approach"},
        {"id": "approach_b", "description": "Alternative"},
    ],
    "abstain": {"triggered": False},
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
        {"id": "approach_b", "summary": "Alt", "sketch": "Do nothing."},
    ],
    "abstain": {"triggered": False},
})

CTRL_GO = json.dumps({
    "glossary_fail": False,
    "glossary": ["health check", "endpoint"],
    "disagreements": [],
})

CONS_IRREV = json.dumps({
    "scores": [
        {
            "id": "approach_a",
            "irreversibility_flag": True,
            "regression_risk": {"net_concern": 0.9, "magnitude": "critical"},
        }
    ]
})

CTRL_DISSENT = json.dumps({
    "glossary_fail": False,
    "glossary": ["endpoint"],
    "disagreements": [],
    "strongest_objection": "approach_a",
    "no_blocking_defect_attested": False,
})

CTRL_SUBSTANTIAL = json.dumps({
    "glossary_fail": False,
    "glossary": ["endpoint"],
    "disagreements": [{"type": "substantial", "summary": "Voices disagree on rollout"}],
})

GEN_NOT_PROPOSAL = json.dumps({
    "options": [],
    "abstain": {"triggered": True, "reason": "not_a_proposal"},
})

GEN_SOFT_ABSTAIN = json.dumps({
    "preferred": "approach_a",
    "options": [{"id": "approach_a"}, {"id": "approach_b"}],
    "abstain": {"triggered": True, "reason": "goal_undefined"},
})

GEN_NO_DATA = json.dumps({
    "preferred": "approach_a",
    "options": [{"id": "approach_a"}, {"id": "approach_b"}],
    "abstain": {"triggered": True, "reason": "no_data"},
})

CONS_SCALE_DOWN = json.dumps({
    "scores": [
        {
            "id": "approach_a",
            "reversibility": "complete",
            "magnitude": "trivial",
            "regression_risk": {"net_concern": 0.1, "magnitude": "trivial"},
            "irreversibility_flag": False,
            "meta_recommendation": "scale_down",
        }
    ]
})


class TestRunSequential(unittest.TestCase):
    def _run(self, cons: str, gen: str, ctrl: str, proposal: str = "Add health check"):
        from consilium.modes.sequential import run_sequential
        from consilium.models import DeliberationInput

        # Generator-first execution order: generator, conservator, control
        outputs = iter([gen, cons, ctrl])
        with patch("consilium.modes.sequential.call_voice", side_effect=lambda *_a, **_kw: next(outputs)):
            return run_sequential(DeliberationInput(proposal=proposal))

    def test_go_verdict(self):
        report = self._run(CONS_GO, GEN_GO, CTRL_GO)
        self.assertEqual(report.verdict, "GO")
        self.assertAlmostEqual(report.confidence, 1.0, places=2)
        self.assertEqual(report.mode, "sequential")
        self.assertTrue(report.pipeline_executed)
        self.assertEqual(len(report.voices), 3)
        self.assertEqual(report.chosen, "approach_a")

    def test_voice_votes(self):
        report = self._run(CONS_GO, GEN_GO, CTRL_GO)
        votes = {v.voice: v.vote for v in report.voices}
        self.assertEqual(votes["conservator"], "GO")
        self.assertEqual(votes["generator"], "GO")
        self.assertEqual(votes["control"], "GO")

    def test_block_on_irreversibility(self):
        report = self._run(CONS_IRREV, GEN_GO, CTRL_GO)
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.confidence, 0.1)
        self.assertIn("irreversible", report.recommendation.lower())

    def test_conservator_vote_stop_on_irrev(self):
        report = self._run(CONS_IRREV, GEN_GO, CTRL_GO)
        cons_voice = next(v for v in report.voices if v.voice == "conservator")
        self.assertEqual(cons_voice.vote, "STOP")

    def test_mandatory_dissent_surfaced_in_control_voice(self):
        """A non-null strongest_objection is surfaced and flips the control vote to MODIFY."""
        report = self._run(CONS_GO, GEN_GO, CTRL_DISSENT)
        ctrl_voice = next(v for v in report.voices if v.voice == "control")
        self.assertEqual(ctrl_voice.vote, "MODIFY")
        self.assertTrue(any("strongest_objection: approach_a" in c for c in ctrl_voice.concerns))

    def test_rework_carries_categorical_confidence(self):
        """Substantial disagreement → REWORK is a bypass verdict (CPYBUS-AGG-001):
        surfaces as MODIFY with categorical confidence 0.1, not the adaptive 0.5."""
        report = self._run(CONS_GO, GEN_GO, CTRL_SUBSTANTIAL)
        self.assertEqual(report.verdict, "MODIFY")
        self.assertEqual(report.confidence, 0.1)

    def test_not_a_proposal_blocks(self):
        """AC1: a non-proposal short-circuits to BLOCK, not GO/MODIFY."""
        report = self._run(CONS_GO, GEN_NOT_PROPOSAL, CTRL_GO)
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.confidence, 0.1)
        self.assertNotIn(report.verdict, ("GO", "MODIFY"))
        self.assertIn("not a deliberation input", report.recommendation.lower())

    def test_not_a_proposal_sets_machine_reason(self):
        """Part 1: the bypass reason is exposed for callers (CLI clarify branch)."""
        report = self._run(CONS_GO, GEN_NOT_PROPOSAL, CTRL_GO)
        self.assertEqual(report.reason, "not_a_proposal")

    def test_chosen_sketch_surfaced(self):
        """Part 2: the chosen candidate's how-to-implement detail reaches the Report."""
        report = self._run(CONS_GO, GEN_GO_WITH_SKETCH, CTRL_GO)
        self.assertEqual(report.verdict, "GO")
        self.assertEqual(report.chosen, "approach_a")
        self.assertEqual(report.chosen_summary, "Add a /health endpoint")
        self.assertIn("GET /health", report.chosen_sketch or "")
        self.assertIn("readiness goal", report.chosen_rationale or "")

    def test_chosen_sketch_absent_on_block(self):
        """A non-proposal BLOCK carries no chosen approach to sketch."""
        report = self._run(CONS_GO, GEN_NOT_PROPOSAL, CTRL_GO)
        self.assertIsNone(report.chosen_sketch)

    def test_no_data_stops_low_confidence(self):
        """A prediction (no_data abstain) is a low-confidence STOP, never GO/MODIFY."""
        report = self._run(CONS_GO, GEN_NO_DATA, CTRL_GO)
        self.assertEqual(report.verdict, "STOP")
        self.assertEqual(report.reason, "no_data")
        self.assertLess(report.confidence, 0.4)

    def test_no_data_beats_scale_down(self):
        """Regression (World Cup GO 0.50): no_data short-circuits ABOVE scale_down,
        so a prediction the Conservator deems trivial still STOPs instead of GOing."""
        report = self._run(CONS_SCALE_DOWN, GEN_NO_DATA, CTRL_GO)
        self.assertEqual(report.verdict, "STOP")
        self.assertEqual(report.reason, "no_data")

    def test_malformed_generator_blocks_with_explicit_reason(self):
        """AC2 (revised 2026-07-01): unparseable Generator output is an explicit
        voice_unparseable BLOCK — never mislabeled as not_a_proposal, and never
        the old fall-through that yielded GO 1.0 with chosen=None."""
        report = self._run(CONS_GO, "this is not json", CTRL_GO)
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.reason, "voice_unparseable")
        self.assertNotIn("not a deliberation input", report.recommendation.lower())
        self.assertIn("generator", report.recommendation.lower())

    def test_malformed_conservator_blocks(self):
        """Regression (probe 2026-07-01: garbage conservator → GO 1.0): an
        unparseable Conservator output silently disables the irreversibility
        veto layer — it must BLOCK, not GO."""
        report = self._run("garbage", GEN_GO, CTRL_GO)
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.reason, "voice_unparseable")
        self.assertIn("conservator", report.recommendation.lower())

    def test_malformed_control_blocks(self):
        report = self._run(CONS_GO, GEN_GO, "garbage")
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.reason, "voice_unparseable")

    def test_all_voices_unparseable_blocks(self):
        """Regression (audit 2026-07-01): three garbage outputs used to produce
        GO 0.9 'Deliberation completed without anomalies'."""
        report = self._run("garbage", "also garbage", "still garbage")
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.reason, "voice_unparseable")
        self.assertEqual(report.confidence, 0.1)

    def test_soft_abstain_is_not_short_circuited(self):
        """AC3: a real proposal flagged with a soft abstain reason is NOT mislabeled."""
        report = self._run(CONS_GO, GEN_SOFT_ABSTAIN, CTRL_GO)
        self.assertNotEqual(report.verdict, "BLOCK")
        self.assertNotIn("not a deliberation input", report.recommendation.lower())

    def test_non_dict_option_entries_ignored(self):
        """A malformed options list mixing strings with dicts must not crash
        the aggregator (audit 2026-07-01 minor: missing isinstance guard)."""
        gen = json.dumps({
            "preferred": "approach_a",
            "options": ["stray string", {"id": "approach_a"}],
            "abstain": {"triggered": False},
        })
        report = self._run(CONS_GO, gen, CTRL_GO)
        self.assertEqual(report.verdict, "GO")
        self.assertEqual(report.chosen, "approach_a")

    def test_sample_fixture_validates(self):
        data = json.loads((FIXTURE_DIR / "sample_report.json").read_text())
        from consilium.models import Report
        report = Report(**data)
        self.assertEqual(report.verdict, "GO")


if __name__ == "__main__":
    unittest.main()
