"""Unit tests for the shared Skeptic challenge — voices mocked, no API calls."""
# tested-by: CPYBUS-SKEPTIC-001
import json
import unittest
from unittest.mock import patch

from consilium.models import DeliberationInput, SkepticObjection, VoiceOutput
from consilium.skeptic import challenge, parse_skeptic

NO_OBJECTION = {
    "can_object": False,
    "objection": None,
    "notes": "chosen aligns with success_criterion; no edge cases visible",
}

IN_PLACE = {
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Missing input validation", "No rate limiting configured"],
        "failure_mode": "correctness",
        "addressable": "in_place",
    },
    "notes": "Fixable with a guard clause.",
}

UNADDRESSABLE = {
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Cannot be rolled back after deploy", "Violates data-at-rest compliance"],
        "failure_mode": "correctness",
        "addressable": "unaddressable",
    },
    "notes": "No redesign fixes this.",
}


class TestParseSkeptic(unittest.TestCase):
    def test_no_objection_votes_go_score_high(self):
        sk, voice = parse_skeptic(NO_OBJECTION, raw_text="ok")
        self.assertIsInstance(sk, SkepticObjection)
        self.assertIsInstance(voice, VoiceOutput)
        self.assertFalse(sk.can_object)
        self.assertEqual(voice.voice, "skeptic")
        self.assertEqual(voice.vote, "GO")
        self.assertAlmostEqual(voice.score, 0.9)

    def test_unaddressable_votes_stop_score_low(self):
        sk, voice = parse_skeptic(UNADDRESSABLE, raw_text="blocked")
        self.assertTrue(sk.can_object)
        self.assertEqual(sk.addressable, "unaddressable")
        self.assertEqual(voice.vote, "STOP")
        self.assertAlmostEqual(voice.score, 0.2)

    def test_addressable_objection_votes_modify_score_mid(self):
        sk, voice = parse_skeptic(IN_PLACE, raw_text="fixable")
        self.assertTrue(sk.can_object)
        self.assertEqual(sk.addressable, "in_place")
        self.assertEqual(voice.vote, "MODIFY")
        self.assertAlmostEqual(voice.score, 0.5)
        self.assertEqual(sk.concrete_concerns, ["Missing input validation", "No rate limiting configured"])


class TestValidationGate(unittest.TestCase):
    """skeptic.md validation gate (audit 2026-07-01 bug #7): can_object with
    fewer than 2 concrete_concerns AND no quoted_scenario is discarded — the
    chosen ships unchallenged instead of a vague objection downgrading it."""

    def test_insufficient_evidence_discarded(self):
        vague = {
            "can_object": True,
            "objection": {"concrete_concerns": ["might break"], "failure_mode": "correctness",
                          "addressable": "unaddressable"},
            "notes": "feels risky",
        }
        sk, voice = parse_skeptic(vague, raw_text="vague")
        self.assertFalse(sk.can_object)
        self.assertIsNone(sk.addressable)
        self.assertEqual(voice.vote, "GO")
        self.assertIn("discarded", sk.notes)

    def test_one_concern_with_quoted_scenario_kept(self):
        with_scenario = {
            "can_object": True,
            "objection": {"concrete_concerns": ["Empty payload crashes handler"],
                          "quoted_scenario": "POST /health with empty body returns 500",
                          "failure_mode": "correctness", "addressable": "in_place"},
            "notes": "",
        }
        sk, voice = parse_skeptic(with_scenario, raw_text="ok")
        self.assertTrue(sk.can_object)
        self.assertEqual(voice.vote, "MODIFY")

    def test_two_concerns_no_scenario_kept(self):
        sk, voice = parse_skeptic(IN_PLACE, raw_text="ok")
        self.assertTrue(sk.can_object)
        self.assertEqual(voice.vote, "MODIFY")


class TestChallenge(unittest.TestCase):
    def test_single_voice_call_and_pair_returned(self):
        with patch("consilium.skeptic.call_voice", return_value=json.dumps(IN_PLACE)) as mock_call, \
             patch("consilium.skeptic.load_prompt", return_value="SKEPTIC PROMPT"):
            sk, voice = challenge("approach_a", DeliberationInput(proposal="Add caching"))

        self.assertEqual(mock_call.call_count, 1)
        self.assertEqual(mock_call.call_args.args[0], "skeptic")
        self.assertIsInstance(sk, SkepticObjection)
        self.assertIsInstance(voice, VoiceOutput)
        self.assertEqual(voice.voice, "skeptic")

    def test_chosen_id_and_proposal_in_skeptic_input(self):
        with patch("consilium.skeptic.call_voice", return_value=json.dumps(NO_OBJECTION)) as mock_call, \
             patch("consilium.skeptic.load_prompt", return_value="SKEPTIC PROMPT"):
            challenge("approach_b", DeliberationInput(proposal="Add rate limiting"))

        user_msg = mock_call.call_args.args[2]
        self.assertIn("approach_b", user_msg)
        self.assertIn("Add rate limiting", user_msg)

    def test_candidate_details_forwarded(self):
        """Regression (audit 2026-07-01 bug #6): the Skeptic prompt promises
        the chosen candidate's summary/sketch/rationale, but challenge() sent
        the raw proposal instead — the Skeptic critiqued the wrong thing."""
        with patch("consilium.skeptic.call_voice", return_value=json.dumps(NO_OBJECTION)) as mock_call, \
             patch("consilium.skeptic.load_prompt", return_value="SKEPTIC PROMPT"):
            challenge(
                "approach_a", DeliberationInput(proposal="Add health check"),
                summary="Add a /health endpoint",
                sketch="GET /health returns 200 + version JSON",
                rationale="Smallest change satisfying readiness",
            )

        user_msg = mock_call.call_args.args[2]
        self.assertIn("Add a /health endpoint", user_msg)
        self.assertIn("GET /health returns 200", user_msg)
        self.assertIn("Smallest change satisfying readiness", user_msg)
        # success_criterion stays the proposal (the goal), not the candidate.
        self.assertIn("success_criterion: Add health check", user_msg)


if __name__ == "__main__":
    unittest.main()
