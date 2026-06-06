"""Unit tests for sequential mode — voices mocked, no API calls."""
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


class TestRunSequential(unittest.TestCase):
    def _run(self, cons: str, gen: str, ctrl: str, proposal: str = "Add health check"):
        from consilium.modes.sequential import run_sequential
        from consilium.models import DeliberationInput

        outputs = iter([cons, gen, ctrl])
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

    def test_sample_fixture_validates(self):
        data = json.loads((FIXTURE_DIR / "sample_report.json").read_text())
        from consilium.models import Report
        report = Report(**data)
        self.assertEqual(report.verdict, "GO")


if __name__ == "__main__":
    unittest.main()
