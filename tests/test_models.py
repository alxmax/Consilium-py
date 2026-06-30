"""Regression guards for removed dead code (confidence.py, DeliberationInput.effort)."""
import importlib
import unittest


class TestDeadCodeRemoved(unittest.TestCase):
    def test_effort_field_removed_from_deliberation_input(self):
        from consilium.models import DeliberationInput
        self.assertNotIn("effort", DeliberationInput.model_fields)

    def test_confidence_module_deleted(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("consilium.confidence")

    def test_deliberation_input_construction_unaffected(self):
        from consilium.models import DeliberationInput
        inp = DeliberationInput(proposal="x")
        self.assertEqual(inp.proposal, "x")
        self.assertEqual(inp.context, "")
        self.assertEqual(inp.model, "openrouter/google/gemini-2.0-flash-001")


if __name__ == "__main__":
    unittest.main()
