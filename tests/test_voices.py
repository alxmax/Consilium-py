"""Unit tests for voice dispatch utilities — no API calls."""
# tested-by: CPYBUS-VOI-001
# tested-by: CPYEXT-LTL-001
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestExtractJson(unittest.TestCase):
    def setUp(self):
        from consilium.voices import extract_json
        self.fn = extract_json

    def test_fenced_json_block(self):
        self.assertEqual(self.fn('```json\n{"k": 1}\n```'), {"k": 1})

    def test_fenced_no_language(self):
        self.assertEqual(self.fn('```\n{"k": 2}\n```'), {"k": 2})

    def test_raw_json_in_text(self):
        self.assertEqual(self.fn('text before {"k": 3} after'), {"k": 3})

    def test_no_json_returns_empty_dict(self):
        self.assertEqual(self.fn("no json here at all"), {})

    def test_nested_json(self):
        self.assertEqual(self.fn('{"outer": {"inner": 42}}'), {"outer": {"inner": 42}})


class TestCallVoiceAnthropic(unittest.TestCase):
    def test_returns_first_text_block(self):
        from consilium.voices import call_voice
        block = MagicMock(type="text", text="hello")
        mock_resp = MagicMock(content=[block])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        with patch("consilium.voices._get_client", return_value=mock_client):
            self.assertEqual(call_voice("c", "sys", "user", "claude-sonnet-4-6"), "hello")

    def test_no_text_block_returns_empty(self):
        from consilium.voices import call_voice
        mock_resp = MagicMock(content=[])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        with patch("consilium.voices._get_client", return_value=mock_client):
            self.assertEqual(call_voice("g", "sys", "user", "claude-sonnet-4-6"), "")


class TestCallVoiceLiteLLM(unittest.TestCase):
    def test_slash_model_uses_litellm(self):
        """Model with '/' routes to litellm.completion()."""
        from consilium.voices import call_voice
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value.choices[0].message.content = "litellm response"
        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            result = call_voice("g", "sys", "user", "openai/gpt-4o")
        self.assertEqual(result, "litellm response")
        mock_litellm.completion.assert_called_once()
        self.assertEqual(mock_litellm.completion.call_args.kwargs["model"], "openai/gpt-4o")

    def test_slash_model_missing_litellm_raises(self):
        """'/' model without litellm installed raises ImportError with hint."""
        from consilium.voices import call_voice
        with patch.dict(sys.modules, {"litellm": None}):
            with self.assertRaises(ImportError) as ctx:
                call_voice("g", "sys", "user", "openai/gpt-4o")
        self.assertIn("consilium-py[litellm]", str(ctx.exception))

    def test_non_slash_model_stays_on_anthropic_path(self):
        """Model without '/' stays on the Anthropic SDK path."""
        from consilium.voices import call_voice
        block = MagicMock(type="text", text="anthropic response")
        mock_resp = MagicMock(content=[block])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        with patch("consilium.voices._get_client", return_value=mock_client):
            result = call_voice("c", "sys", "user", "claude-sonnet-4-6")
        self.assertEqual(result, "anthropic response")


if __name__ == "__main__":
    unittest.main()
