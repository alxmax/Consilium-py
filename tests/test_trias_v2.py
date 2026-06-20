"""Unit tests for Trias v2 — personalities + verification mocked, no API calls.
# tested-by: CPYMOD-TRI2-001
"""
import unittest
from unittest.mock import patch

from consilium.models import DeliberationInput, Report, SkepticObjection, VoiceOutput


def _report(chosen: str | None, verdict: str = "GO", confidence: float = 1.0) -> Report:
    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        recommendation=f"ok, chosen={chosen}",
        voices=[VoiceOutput(voice="conservator", vote="GO", reasoning="ok", score=0.9)],
        chosen=chosen,
        mode="sequential",
    )


def _skeptic(can_object: bool, addressable: str | None = None):
    sk = SkepticObjection(
        can_object=can_object,
        failure_mode="edge case" if can_object else None,
        addressable=addressable,  # type: ignore[arg-type]
        notes="n",
    )
    voice = VoiceOutput(
        voice="skeptic",
        vote="MODIFY" if can_object else "GO",
        reasoning="r",
        score=0.5 if can_object else 0.9,
    )
    return sk, voice


class TestRunTriasV2(unittest.TestCase):
    def _run(self, returns, verify=None):
        from consilium.modes.trias_v2 import run_trias_v2

        def mock_personality(name, inp):
            return returns[name]

        verify = verify or (lambda *a, **k: _skeptic(False))
        with patch("consilium.modes.trias._run_personality", side_effect=mock_personality), \
             patch("consilium.modes.trias_v2._verify_winner", side_effect=verify) as mv:
            r = run_trias_v2(DeliberationInput(proposal="Add health check"))
            return r, mv

    # ── consensus: no verification ───────────────────────────────────────────
    def test_consensus_no_verification(self):
        r, mv = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertEqual(r.mode, "trias_v2")
        self.assertEqual(r.chosen, "a")
        self.assertAlmostEqual(r.confidence, 0.95)
        self.assertIsNone(r.skeptic)          # verification skipped on consensus
        mv.assert_not_called()
        self.assertEqual(len(r.voices), 3)    # no verifier voice added
        self.assertIn("disagreement=1", r.recommendation)

    # ── split: verification fires, advisory ──────────────────────────────────
    def test_split_runs_verification(self):
        r, mv = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("b")})
        self.assertEqual(r.chosen, "a")       # majority winner
        mv.assert_called_once()               # capped: exactly one pass
        self.assertIsNotNone(r.skeptic)
        self.assertEqual(len(r.voices), 4)    # 3 personalities + verifier
        self.assertIn("disagreement=2", r.recommendation)

    def test_split_verification_is_advisory_no_vote_flip(self):
        # Skeptic objects 'unaddressable' but the winner must NOT change.
        r, _ = self._run(
            {"pioneer": _report("a"), "architect": _report("a"), "steward": _report("b")},
            verify=lambda *a, **k: _skeptic(True, "unaddressable"),
        )
        self.assertEqual(r.chosen, "a")               # unchanged (independence audit)
        self.assertLessEqual(r.confidence, 0.75)      # advisory lowered confidence
        self.assertTrue(r.skeptic.can_object)
        self.assertIn("CAVEAT", r.recommendation)

    def test_split_clean_verification_keeps_winner(self):
        r, _ = self._run(
            {"pioneer": _report("a"), "architect": _report("a"), "steward": _report("b")},
            verify=lambda *a, **k: _skeptic(False),
        )
        self.assertEqual(r.chosen, "a")
        self.assertAlmostEqual(r.confidence, 0.75)    # base 2-1 confidence, no penalty
        self.assertFalse(r.skeptic.can_object)

    # ── three-way split → escalate, no verification ──────────────────────────
    def test_three_way_escalates_no_verification(self):
        r, mv = self._run({"pioneer": _report("a"), "architect": _report("b"), "steward": _report("c")})
        self.assertEqual(r.verdict, "ESCALATE")
        self.assertIsNone(r.chosen)
        mv.assert_not_called()
        self.assertIn("disagreement=3", r.recommendation)

    def test_pipeline_executed(self):
        r, _ = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")})
        self.assertTrue(r.pipeline_executed)


if __name__ == "__main__":
    unittest.main()
