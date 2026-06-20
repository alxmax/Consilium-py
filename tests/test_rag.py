"""Unit tests for RAG module — chromadb mocked, temp dirs for filesystem."""
# tested-by: CPYEXT-RAG-001
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch


def _mock_collection(count: int = 0, query_results=None):
    col = MagicMock()
    col.count.return_value = count
    if query_results is not None:
        col.query.return_value = query_results
    return col


class TestRetrieve(unittest.TestCase):
    def test_empty_index_returns_empty_and_prints_stderr(self):
        from consilium import rag
        col = _mock_collection(count=0)
        buf = io.StringIO()
        with patch("consilium.rag._get_collection", return_value=col), redirect_stderr(buf):
            result = rag.retrieve("Add health endpoint")
        self.assertEqual(result, [])
        self.assertIn("empty", buf.getvalue().lower())

    def test_no_match_above_threshold_returns_empty(self):
        from consilium import rag
        col = _mock_collection(
            count=3,
            query_results={
                "ids": [["id1"]],
                "documents": [["Unrelated topic"]],
                "metadatas": [[{"verdict": "GO", "confidence": 0.9,
                                "recommendation": "ok", "mode": "sequential"}]],
                "distances": [[0.9]],  # exceeds 0.35 threshold
            },
        )
        with patch("consilium.rag._get_collection", return_value=col):
            result = rag.retrieve("completely different", max_distance=0.35)
        self.assertEqual(result, [])

    def test_match_within_threshold_returns_snippet(self):
        from consilium import rag
        col = _mock_collection(
            count=1,
            query_results={
                "ids": [["id1"]],
                "documents": [["Add health check"]],
                "metadatas": [[{"verdict": "GO", "confidence": 0.9,
                                "recommendation": "Looks good", "mode": "sequential"}]],
                "distances": [[0.2]],  # within 0.35 threshold
            },
        )
        with patch("consilium.rag._get_collection", return_value=col):
            result = rag.retrieve("Add health endpoint")
        self.assertEqual(len(result), 1)
        self.assertIn("GO", result[0])
        self.assertIn("Add health check", result[0])


class TestChromadbImportError(unittest.TestCase):
    def test_missing_chromadb_raises_with_install_hint(self):
        from consilium import rag
        saved = sys.modules.get("chromadb")
        try:
            sys.modules["chromadb"] = None  # type: ignore[assignment]
            with self.assertRaises(ImportError) as ctx:
                rag._get_collection()
            self.assertIn("consilium-py[rag]", str(ctx.exception))
        finally:
            if saved is not None:
                sys.modules["chromadb"] = saved
            elif "chromadb" in sys.modules:
                del sys.modules["chromadb"]


class TestSaveRun(unittest.TestCase):
    def test_proposal_stored_in_record(self):
        """save_run must include proposal text inside the JSON record."""
        from consilium import rag
        from consilium.models import DeliberationInput, Report
        inp = DeliberationInput(proposal="Add health check endpoint")
        report = Report(verdict="GO", confidence=0.9, recommendation="ok",
                        voices=[], mode="sequential")
        run_id = rag.new_run_id()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("consilium.rag._RUNS_DIR", Path(tmp)):
                path = rag.save_run(run_id, inp, report)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["proposal"], "Add health check endpoint")
        self.assertIn("id", data)
        self.assertIn("timestamp", data)
        self.assertIn("report", data)


class TestBuildRagContext(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        from consilium import rag
        col = _mock_collection(count=0)
        with patch("consilium.rag._get_collection", return_value=col), \
             redirect_stderr(io.StringIO()):
            result = rag.build_rag_context("Add health check")
        self.assertEqual(result, "")

    def test_non_empty_returns_block_header(self):
        from consilium import rag
        col = _mock_collection(
            count=1,
            query_results={
                "ids": [["id1"]],
                "documents": [["Add health check"]],
                "metadatas": [[{"verdict": "GO", "confidence": 0.9,
                                "recommendation": "ok", "mode": "sequential"}]],
                "distances": [[0.2]],
            },
        )
        with patch("consilium.rag._get_collection", return_value=col):
            result = rag.build_rag_context("Add health endpoint")
        self.assertIn("SIMILAR PAST DECISIONS", result)


if __name__ == "__main__":
    unittest.main()
