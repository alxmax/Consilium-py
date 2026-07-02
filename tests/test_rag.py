"""Unit tests for RAG module — chromadb mocked, temp dirs for filesystem."""
# tested-by: CPYEXT-RAG-001
# tested-by: CPYEXT-DOCRAG-001
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import chromadb  # noqa: F401
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False


def _mock_collection(count: int = 0, query_results=None):
    col = MagicMock()
    col.count.return_value = count
    if query_results is not None:
        col.query.return_value = query_results
    return col


def _patched(col):
    """Patch _get_collection and silence _legacy_index_hint (which otherwise
    opens a real chromadb PersistentClient against the user's home dir)."""
    return patch.multiple(
        "consilium.rag",
        _get_collection=MagicMock(return_value=col),
        _legacy_index_hint=MagicMock(),
    )


class TestRetrieve(unittest.TestCase):
    def test_empty_index_returns_empty_and_prints_stderr(self):
        from consilium import rag
        col = _mock_collection(count=0)
        buf = io.StringIO()
        with _patched(col), redirect_stderr(buf):
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
                "distances": [[0.9]],  # exceeds 0.55 threshold
            },
        )
        with _patched(col):
            result = rag.retrieve("completely different", max_distance=0.55)
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
                "distances": [[0.2]],  # within 0.55 threshold
            },
        )
        with _patched(col):
            result = rag.retrieve("Add health endpoint")
        self.assertEqual(len(result), 1)
        self.assertIn("GO", result[0])
        self.assertIn("Add health check", result[0])

    def test_query_filters_by_kind_and_quality(self):
        """retrieve() must scope the where clause to kind=run + confidence/verdict."""
        from consilium import rag
        col = _mock_collection(
            count=1,
            query_results={
                "ids": [["id1"]],
                "documents": [["Add health check"]],
                "metadatas": [[{"verdict": "GO", "confidence": 0.9,
                                "recommendation": "ok", "mode": "sequential"}]],
                "distances": [[0.1]],
            },
        )
        with _patched(col):
            rag.retrieve("Add health endpoint")
        where = col.query.call_args.kwargs["where"]
        self.assertEqual(where["$and"][0], {"kind": "run"})


class TestRetrieveDocs(unittest.TestCase):
    def test_returns_source_cited_snippet(self):
        from consilium import rag
        col = _mock_collection(
            count=1,
            query_results={
                "ids": [["doc:README.md:0"]],
                "documents": [["Consilium is a deliberation engine."]],
                "metadatas": [[{"kind": "doc", "source": "README.md", "chunk_index": 0}]],
                "distances": [[0.1]],
            },
        )
        with _patched(col):
            result = rag.retrieve_docs("What is consilium?")
        self.assertEqual(len(result), 1)
        self.assertIn("README.md", result[0])


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


class TestIndex(unittest.TestCase):
    def test_embeds_proposal_and_context(self):
        from consilium import rag
        from consilium.models import DeliberationInput, Report
        inp = DeliberationInput(proposal="Add health check", context="see api.py")
        report = Report(verdict="GO", confidence=0.9, recommendation="ok",
                         voices=[], mode="sequential")
        col = _mock_collection()
        with _patched(col):
            rag.index("run1", inp, report)
        document = col.upsert.call_args.kwargs["documents"][0]
        self.assertIn("Add health check", document)
        self.assertIn("see api.py", document)

    def test_metadata_tags_kind_run(self):
        from consilium import rag
        from consilium.models import DeliberationInput, Report
        inp = DeliberationInput(proposal="Add health check")
        report = Report(verdict="GO", confidence=0.9, recommendation="ok",
                         voices=[], mode="sequential")
        col = _mock_collection()
        with _patched(col):
            rag.index("run1", inp, report)
        metadata = col.upsert.call_args.kwargs["metadatas"][0]
        self.assertEqual(metadata["kind"], "run")


class TestBuildRagContext(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        from consilium import rag
        col = _mock_collection(count=0)
        with _patched(col), redirect_stderr(io.StringIO()):
            result = rag.build_rag_context("Add health check")
        self.assertEqual(result, "")

    def test_non_empty_run_returns_block_header(self):
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
        with _patched(col):
            result = rag.build_rag_context("Add health endpoint")
        self.assertIn("SIMILAR PAST DECISIONS", result)


class TestChunkText(unittest.TestCase):
    def test_short_text_returns_single_chunk(self):
        from consilium import rag
        chunks = rag._chunk_text("short text")
        self.assertEqual(chunks, ["short text"])

    def test_long_text_overlaps(self):
        from consilium import rag
        text = "x" * 3000
        chunks = rag._chunk_text(text, size=1200, overlap=200)
        self.assertGreater(len(chunks), 1)
        # consecutive chunks overlap by `overlap` characters
        self.assertEqual(chunks[0][-200:], chunks[1][:200])

    def test_blank_text_returns_no_chunks(self):
        from consilium import rag
        self.assertEqual(rag._chunk_text("   \n  "), [])


class TestIngestPath(unittest.TestCase):
    def test_ingests_markdown_file(self):
        from consilium import rag
        col = _mock_collection()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "notes.md"
            f.write_text("# Notes\n\nSome content here.", encoding="utf-8")
            with patch("consilium.rag._get_collection", return_value=col):
                count = rag.ingest_path(str(f))
        self.assertEqual(count, 1)
        metadata = col.upsert.call_args.kwargs["metadatas"][0]
        self.assertEqual(metadata["kind"], "doc")
        self.assertEqual(metadata["source"], "notes.md")

    def test_skips_oversized_file(self):
        from consilium import rag
        col = _mock_collection()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "big.md"
            f.write_text("x" * (rag._MAX_INGEST_FILE_BYTES + 1), encoding="utf-8")
            with patch("consilium.rag._get_collection", return_value=col), \
                 redirect_stderr(io.StringIO()):
                count = rag.ingest_path(str(f))
        self.assertEqual(count, 0)
        col.upsert.assert_not_called()

    def test_skips_binary_file(self):
        from consilium import rag
        col = _mock_collection()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "image.md"  # deliberately mismatched extension
            f.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x00\x00\x00\x01")
            with patch("consilium.rag._get_collection", return_value=col), \
                 redirect_stderr(io.StringIO()):
                count = rag.ingest_path(str(f))
        self.assertEqual(count, 0)

    def test_missing_path_raises(self):
        from consilium import rag
        with self.assertRaises(FileNotFoundError):
            rag.ingest_path("/no/such/path/exists")

    def test_ingests_directory_recursively(self):
        from consilium import rag
        col = _mock_collection()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("Doc A content.", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.txt").write_text("Doc B content.", encoding="utf-8")
            (root / "ignored.png").write_bytes(b"\x89PNG\r\n")
            with patch("consilium.rag._get_collection", return_value=col):
                count = rag.ingest_path(str(root))
        self.assertEqual(count, 2)


@unittest.skipUnless(_HAS_CHROMADB, "chromadb not installed — pip install 'consilium-py[rag]'")
class TestMaxDistanceCalibration(unittest.TestCase):
    """Committed calibration fixture for _MAX_DISTANCE (cosine space).

    Not mocked — exercises the real embedding function so the threshold is
    validated against actual distances, not an assumption. Slower than the
    rest of the suite (loads the onnx model on first run).
    """

    def test_max_distance_separates_known_pairs(self):
        import shutil
        from consilium import rag

        tmp = tempfile.mkdtemp()
        try:
            with patch("consilium.rag._CHROMA_DIR", Path(tmp)):
                col = rag._get_collection()

                similar_pairs = [
                    ("Add a health check endpoint to the API", "Add a /health endpoint returning 200 OK"),
                    ("Refactor the authentication module for clarity",
                     "Clean up the auth code, split into smaller functions"),
                ]
                dissimilar_pairs = [
                    ("Add a health check endpoint to the API", "Migrate the database to PostgreSQL"),
                    ("Refactor the authentication module for clarity", "Add dark mode to the settings UI"),
                ]

                for i, (a, _b) in enumerate(similar_pairs + dissimilar_pairs):
                    col.upsert(ids=[f"pair{i}"], documents=[a])

                for i, (_a, b) in enumerate(similar_pairs):
                    result = col.query(query_texts=[b], n_results=1)
                    distance = result["distances"][0][0]
                    self.assertLessEqual(
                        distance, rag._MAX_DISTANCE,
                        f"similar pair {i} distance {distance:.4f} should be <= _MAX_DISTANCE",
                    )

                for i, (_a, b) in enumerate(dissimilar_pairs):
                    result = col.query(query_texts=[b], n_results=1)
                    distance = result["distances"][0][0]
                    self.assertGreater(
                        distance, rag._MAX_DISTANCE,
                        f"dissimilar pair {i} distance {distance:.4f} should be > _MAX_DISTANCE",
                    )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
