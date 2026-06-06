"""Unit tests for Trias mode — _run_personality mocked, no API calls.
# tested-by: CPYMOD-TRI-001
"""
import unittest
from unittest.mock import patch

from consilium.models import Report, VoiceOutput


def _report(chosen: str | None, verdict: str = "GO", confidence: float = 1.0) -> Report:
    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        recommendation=f"ok, chosen={chosen}",
        voices=[VoiceOutput(voice="conservator", vote="GO", reasoning="ok", score=0.9)],
        chosen=chosen,
        mode="sequential",
    )


class TestRunTrias(unittest.TestCase):
    def _run(self, personality_returns: dict[str, Report]):
        from consilium.models import DeliberationInput
        from consilium.modes.trias import run_trias

        def mock_personality(name: str, inp: object) -> Report:
            return personality_returns[name]

        with patch("consilium.modes.trias._run_personality", side_effect=mock_personality):
            return run_trias(DeliberationInput(proposal="Add health check"))

    def test_mode_field(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertEqual(r.mode, "trias")

    def test_three_voice_outputs(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertEqual(len(r.voices), 3)
        self.assertEqual({v.voice for v in r.voices}, {"pioneer", "architect", "steward"})

    def test_unanimous_go_high_confidence(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertEqual(r.verdict, "GO")
        self.assertAlmostEqual(r.confidence, 0.95)
        self.assertEqual(r.chosen, "a")

    def test_recommendation_includes_vote_pattern(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertIn("3-0", r.recommendation)

    def test_split_vote_lower_confidence(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("b")})
        self.assertIn(r.verdict, ("GO", "MODIFY"))
        self.assertAlmostEqual(r.confidence, 0.75)
        self.assertEqual(r.chosen, "a")  # majority

    def test_three_way_escalates(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("b"), "steward": _report("c")})
        self.assertEqual(r.verdict, "ESCALATE")
        self.assertIsNone(r.chosen)

    def test_pipeline_executed(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertTrue(r.pipeline_executed)


if __name__ == "__main__":
    unittest.main()
