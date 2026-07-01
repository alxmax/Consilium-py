"""Unit tests for Trias mode — _run_personality + skeptic mocked, no API calls."""
# tested-by: CPYMOD-TRI-001
import json
import unittest
from unittest.mock import patch

from consilium.models import Report, VoiceOutput

SKEPTIC_NO_OBJECTION = json.dumps({
    "can_object": False,
    "objection": None,
    "notes": "winner aligns with success_criterion; no edge cases visible",
})

SKEPTIC_IN_PLACE = json.dumps({
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Missing input validation", "No rate limiting"],
        "failure_mode": "correctness",
        "addressable": "in_place",
    },
    "notes": "Fixable with a guard clause.",
})

SKEPTIC_UNADDRESSABLE = json.dumps({
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Violates compliance requirement", "Cannot be rolled back"],
        "failure_mode": "correctness",
        "addressable": "unaddressable",
    },
    "notes": "No redesign fixes this.",
})


def _report(
    chosen: str | None,
    verdict: str = "GO",
    confidence: float = 1.0,
    reason: str | None = None,
    **chosen_fields: str,
) -> Report:
    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        recommendation=f"ok, chosen={chosen}",
        voices=[VoiceOutput(voice="conservator", vote="GO", reasoning="ok", score=0.9)],
        chosen=chosen,
        reason=reason,
        mode="sequential",
        **chosen_fields,  # type: ignore[arg-type]
    )


class TestRunTrias(unittest.TestCase):
    def _run(
        self,
        personality_returns: dict[str, Report],
        skeptic_text: str = SKEPTIC_NO_OBJECTION,
        skeptic_can_override: bool = False,
    ):
        from consilium.models import DeliberationInput
        from consilium.modes.trias import run_trias

        def mock_personality(name: str, inp: object, shared_gen: str) -> Report:
            return personality_returns[name]

        with patch("consilium.modes.trias._neutral_generator", return_value="NEUTRAL GEN OUTPUT"), \
             patch("consilium.modes.trias._run_personality", side_effect=mock_personality), \
             patch("consilium.skeptic.call_voice", return_value=skeptic_text):
            return run_trias(
                DeliberationInput(proposal="Add health check"),
                skeptic_can_override=skeptic_can_override,
            )

    def _unanimous(self, **kw):
        return self._run(
            {"pioneer": _report("a"), "architect": _report("a"), "steward": _report("a")},
            **kw,
        )

    def test_mode_field(self):
        self.assertEqual(self._unanimous().mode, "trias")

    def test_decisive_vote_appends_skeptic_voice(self):
        r = self._unanimous()
        self.assertEqual(len(r.voices), 4)
        self.assertEqual(
            {v.voice for v in r.voices},
            {"pioneer", "architect", "steward", "skeptic"},
        )

    def test_unanimous_go_high_confidence(self):
        r = self._unanimous()
        self.assertEqual(r.verdict, "GO")
        self.assertAlmostEqual(r.confidence, 0.95)
        self.assertEqual(r.chosen, "a")

    def test_recommendation_includes_vote_pattern(self):
        self.assertIn("3-0", self._unanimous().recommendation)

    def test_split_vote_lower_confidence(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": _report("b")})
        self.assertIn(r.verdict, ("GO", "MODIFY"))
        self.assertAlmostEqual(r.confidence, 0.75)
        self.assertEqual(r.chosen, "a")  # majority

    def test_three_way_escalates(self):
        r = self._run({"pioneer": _report("a"), "architect": _report("b"), "steward": _report("c")})
        self.assertEqual(r.verdict, "ESCALATE")
        self.assertIsNone(r.chosen)

    def test_escalate_skips_skeptic(self):
        """No winner → no decisive answer to challenge → Skeptic does not fire."""
        r = self._run({"pioneer": _report("a"), "architect": _report("b"), "steward": _report("c")})
        self.assertEqual(len(r.voices), 3)
        self.assertNotIn("skeptic", [v.voice for v in r.voices])
        self.assertIsNone(r.skeptic)

    def test_pipeline_executed(self):
        self.assertTrue(self._unanimous().pipeline_executed)

    def test_skeptic_advisory_does_not_flip(self):
        """Advisory (default): an objection never changes the winner or verdict."""
        r = self._unanimous(skeptic_text=SKEPTIC_IN_PLACE)
        self.assertEqual(r.verdict, "GO")
        self.assertEqual(r.chosen, "a")
        self.assertAlmostEqual(r.confidence, 0.95)
        assert r.skeptic is not None
        self.assertTrue(r.skeptic.can_object)

    def test_skeptic_override_in_place_downgrades_with_notes(self):
        r = self._unanimous(skeptic_text=SKEPTIC_IN_PLACE, skeptic_can_override=True)
        self.assertEqual(r.verdict, "MODIFY")
        self.assertEqual(r.chosen, "a")
        # in_place recommendation must carry the Skeptic's notes.
        self.assertIn("Fixable with a guard clause.", r.recommendation)

    def test_skeptic_override_unaddressable_blocks(self):
        r = self._unanimous(skeptic_text=SKEPTIC_UNADDRESSABLE, skeptic_can_override=True)
        self.assertEqual(r.verdict, "BLOCK")
        self.assertAlmostEqual(r.confidence, 0.1)
        self.assertEqual(r.chosen, "a")  # chosen unchanged even when blocked

    def test_categorical_block_propagates(self):
        """Regression (audit 2026-07-01 bug #5): a personality BLOCK used to
        count as a mere vote abstention — a not_a_proposal input yielded
        ESCALATE 'no majority' instead of the BLOCK that deliberate() converts
        to ANSWER."""
        block = _report(None, verdict="BLOCK", confidence=0.1, reason="not_a_proposal")
        r = self._run({"pioneer": block, "architect": block, "steward": block})
        self.assertEqual(r.verdict, "BLOCK")
        self.assertEqual(r.reason, "not_a_proposal")
        self.assertEqual(r.mode, "trias")

    def test_irreversibility_block_not_outvoted(self):
        """A single personality's irreversibility veto is absolute — two GO
        votes must not override the safety layer."""
        block = _report(None, verdict="BLOCK", confidence=0.1, reason="irreversibility_no_consent")
        r = self._run({"pioneer": _report("a"), "architect": _report("a"), "steward": block})
        self.assertEqual(r.verdict, "BLOCK")
        self.assertEqual(r.reason, "irreversibility_no_consent")

    def test_winner_chosen_fields_propagate(self):
        """Regression (audit 2026-07-01): trias rebuilt the Report without the
        winner's chosen_summary/sketch/rationale, hiding 'How to implement'."""
        winner = _report(
            "a",
            chosen_summary="Add a /health endpoint",
            chosen_sketch="GET /health returns 200",
            chosen_rationale="Smallest change",
        )
        r = self._run({"pioneer": winner, "architect": winner, "steward": winner})
        self.assertEqual(r.chosen_summary, "Add a /health endpoint")
        self.assertEqual(r.chosen_sketch, "GET /health returns 200")
        self.assertEqual(r.chosen_rationale, "Smallest change")

    def test_skeptic_receives_winner_candidate_details(self):
        """Bug #6: the Skeptic must challenge the actual winning candidate,
        not just its opaque id."""
        winner = _report("a", chosen_summary="SUMMARY_MARKER", chosen_sketch="SKETCH_MARKER")
        from consilium.models import DeliberationInput
        from consilium.modes.trias import run_trias

        with patch("consilium.modes.trias._neutral_generator", return_value=""), \
             patch("consilium.modes.trias._run_personality",
                   side_effect=lambda *_a, **_kw: winner), \
             patch("consilium.skeptic.call_voice", return_value=SKEPTIC_NO_OBJECTION) as mock_call:
            run_trias(DeliberationInput(proposal="Add health check"))

        user_msg = mock_call.call_args.args[2]
        self.assertIn("SUMMARY_MARKER", user_msg)
        self.assertIn("SKETCH_MARKER", user_msg)


class TestSharedCandidates(unittest.TestCase):
    def test_personality_generator_receives_shared_candidates(self):
        """Bug #4: candidate ids were only comparable across personalities by
        accident. Each personality's Generator must receive the shared neutral
        candidate set and select among those exact ids."""
        from consilium.models import DeliberationInput
        from consilium.modes.trias import _run_personality

        calls: list[tuple[str, str]] = []

        def mock_cv(voice: str, _sys: str, user: str, _model: str) -> str:
            calls.append((voice, user))
            return '{"x": 1}'  # parseable; content irrelevant here

        with patch("consilium.modes.trias.call_voice", side_effect=mock_cv):
            _run_personality("pioneer", DeliberationInput(proposal="x"), "SHARED_CANDIDATES_BLOCK")

        gen_voice, gen_msg = calls[0]
        self.assertEqual(gen_voice, "generator")
        self.assertIn("SHARED_CANDIDATES_BLOCK", gen_msg)
        self.assertIn("do not invent new ids", gen_msg.lower())


if __name__ == "__main__":
    unittest.main()
