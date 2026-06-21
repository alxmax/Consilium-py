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
        "concrete_concerns": ["Missing input validation"],
        "failure_mode": "correctness",
        "addressable": "in_place",
    },
    "notes": "Fixable with a guard clause.",
}

UNADDRESSABLE = {
    "can_object": True,
    "objection": {
        "concrete_concerns": ["Cannot be rolled back after deploy"],
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
        self.assertEqual(sk.concrete_concerns, ["Missing input validation"])


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


if __name__ == "__main__":
    unittest.main()
