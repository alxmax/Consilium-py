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

    def test_brace_in_string_value_parses_correctly(self):
        """A stray '}' inside a string value must not truncate the parse (regression)."""
        text = '{"options": [{"id": "opt1", "sketch": "end of fn }", "rationale": "ok"}], "preferred": "opt1"}'
        result = self.fn(text)
        self.assertEqual(result["preferred"], "opt1")
        self.assertEqual(result["options"][0]["sketch"], "end of fn }")

    def test_multiple_braces_in_string_value(self):
        """Pseudocode with balanced braces in a string must still parse the enclosing object."""
        text = '{"sketch": "if (x) { return y; } else { return z; }", "id": "opt1"}'
        self.assertEqual(
            self.fn(text),
            {"sketch": "if (x) { return y; } else { return z; }", "id": "opt1"},
        )

    def test_fence_path_unaffected_by_brace_in_string(self):
        text = '```json\n{"sketch": "a { b }"}\n```'
        self.assertEqual(self.fn(text), {"sketch": "a { b }"})

    def test_literal_newline_in_string_value(self):
        """`claude -p` voices emit literal newlines inside string values (e.g. a
        multi-line Control `notes`/`assert`). strict JSON rejects those, collapsing
        the voice to {}; extract_json must tolerate them (strict=False)."""
        text = '{"verdicts": [{"id": "x", "notes": "line one\nline two"}]}'
        self.assertEqual(self.fn(text), {"verdicts": [{"id": "x", "notes": "line one\nline two"}]})

    def test_literal_newline_in_fenced_string(self):
        text = '```json\n{"notes": "a\nb"}\n```'
        self.assertEqual(self.fn(text), {"notes": "a\nb"})


class TestClaudeCliDispatch(unittest.TestCase):
    """The claude-cli backend must honor the user's model choice: bare
    'claude-cli' runs sonnet, 'claude-cli:<name>' forwards <name> to the
    subprocess (regression: the model was silently hard-coded to sonnet)."""

    def _dispatch(self, model: str) -> list[str]:
        from consilium.voices import call_voice

        proc = MagicMock(returncode=0, stdout="ok")
        with patch("subprocess.run", return_value=proc) as run, \
                patch("shutil.which", return_value="claude"):
            call_voice("generator", "system", "user", model)
        return run.call_args[0][0]

    def test_default_model_is_sonnet(self):
        argv = self._dispatch("claude-cli")
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_submodel_is_forwarded(self):
        argv = self._dispatch("claude-cli:opus")
        self.assertEqual(argv[argv.index("--model") + 1], "opus")

    def test_json_voice_retries_on_prose_drift(self):
        """`claude -p` intermittently answers a JSON voice in prose. A JSON voice
        (generator) must retry until it gets a parseable object, then return it."""
        from consilium.voices import call_voice

        outs = [
            MagicMock(returncode=0, stdout="**Verdict: STOP** — prose, no JSON here"),
            MagicMock(returncode=0, stdout='```json\n{"candidates": []}\n```'),
        ]
        with patch("subprocess.run", side_effect=outs) as run, \
                patch("shutil.which", return_value="claude"):
            result = call_voice("generator", "system", "user", "claude-cli")
        self.assertEqual(run.call_count, 2)              # retried once past the prose
        self.assertIn('"candidates"', result)            # returned the parseable attempt

    def test_prose_voice_is_never_retried(self):
        """assistant/explain return prose by contract — they must NOT be JSON-retried
        (that would loop on every valid plain answer)."""
        from consilium.voices import call_voice

        proc = MagicMock(returncode=0, stdout="Just a plain conversational reply.")
        with patch("subprocess.run", return_value=proc) as run, \
                patch("shutil.which", return_value="claude"):
            result = call_voice("assistant", "system", "user", "claude-cli")
        self.assertEqual(run.call_count, 1)              # no retry despite no JSON
        self.assertEqual(result, "Just a plain conversational reply.")

    def test_json_voice_gives_up_after_max_retries(self):
        """If every attempt drifts to prose, return the last output (aggregator flags
        it) rather than looping forever."""
        from consilium.voices import call_voice

        proc = MagicMock(returncode=0, stdout="never JSON")
        with patch("subprocess.run", return_value=proc) as run, \
                patch("shutil.which", return_value="claude"):
            result = call_voice("control", "system", "user", "claude-cli")
        self.assertEqual(run.call_count, 3)              # 1 + _CLI_JSON_RETRIES(2)
        self.assertEqual(result, "never JSON")


class TestLoadPrompt(unittest.TestCase):
    """Regression (audit 2026-07-01): prompts lived at the repo root, outside
    the wheel — every non-editable install crashed on the first load_prompt().
    They must resolve inside the consilium package via importlib.resources."""

    _ALL_PROMPTS = [
        "conservator", "control", "generator", "skeptic", "explain",
        "pioneer_lens", "architect_lens", "steward_lens",
    ]

    def test_prompts_dir_inside_package(self):
        from consilium.voices import PROMPTS_DIR
        normalized = str(PROMPTS_DIR).replace("\\", "/")
        self.assertTrue(normalized.endswith("consilium/prompts/voices"), normalized)

    def test_all_prompts_load(self):
        from consilium.voices import load_prompt
        for name in self._ALL_PROMPTS:
            with self.subTest(prompt=name):
                text = load_prompt(name)
                self.assertTrue(text.strip(), f"{name}.md is empty")


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

    def test_litellm_debug_footer_suppressed(self):
        """The LiteLLM path sets suppress_debug_info to silence the stderr footer."""
        from consilium.voices import call_voice
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value.choices[0].message.content = "ok"
        with patch.dict(sys.modules, {"litellm": mock_litellm}):
            call_voice("g", "sys", "user", "openai/gpt-4o")
        self.assertIs(mock_litellm.suppress_debug_info, True)

    def test_slash_model_missing_litellm_raises(self):
        """'/' model with a broken litellm install still raises ImportError."""
        from consilium.voices import call_voice
        with patch.dict(sys.modules, {"litellm": None}):
            with self.assertRaises(ImportError):
                call_voice("g", "sys", "user", "openai/gpt-4o")

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


class TestPlainAnswer(unittest.TestCase):
    def test_routes_through_call_voice(self):
        """plain_answer() makes one call_voice() call with the assistant system prompt."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="hello there") as mock:
            result = voices.plain_answer("hi", "some-model")
        self.assertEqual(result, "hello there")
        mock.assert_called_once()
        _name, system, user_msg, model = mock.call_args.args
        self.assertIn("not a code change", system)
        self.assertEqual(user_msg, "hi")
        self.assertEqual(model, "some-model")

    def test_short_response_routes_through_call_voice(self):
        """short_response() makes one concise call_voice() call."""
        from consilium import voices
        with patch.object(voices, "call_voice", return_value="short!") as mock:
            result = voices.short_response("trivial change", "m")
        self.assertEqual(result, "short!")
        mock.assert_called_once()
        _name, system, user_msg, model = mock.call_args.args
        self.assertIn("2 sentences", system)
        self.assertEqual(user_msg, "trivial change")


if __name__ == "__main__":
    unittest.main()
