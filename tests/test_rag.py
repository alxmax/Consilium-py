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
        # Flat $and (kind + confidence + verdict), never a nested $and-in-$and.
        self.assertIn("$and", where)
        clauses = where["$and"]
        self.assertEqual(clauses[0], {"kind": "run"})
        self.assertEqual(len(clauses), 3)
        self.assertFalse(any("$and" in c for c in clauses), "no nested $and")


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

    def test_dedupes_by_source(self):
        """Three chunks from one file + one from another → 2 sources, not 4."""
        from consilium import rag
        col = _mock_collection(
            count=4,
            query_results={
                "ids": [["doc:a.md:0", "doc:a.md:1", "doc:a.md:2", "doc:b.md:0"]],
                "documents": [["a-chunk0", "a-chunk1", "a-chunk2", "b-chunk0"]],
                "metadatas": [[
                    {"kind": "doc", "source": "a.md", "chunk_index": 0},
                    {"kind": "doc", "source": "a.md", "chunk_index": 1},
                    {"kind": "doc", "source": "a.md", "chunk_index": 2},
                    {"kind": "doc", "source": "b.md", "chunk_index": 0},
                ]],
                "distances": [[0.1, 0.15, 0.2, 0.25]],
            },
        )
        with _patched(col):
            result = rag.retrieve_docs("query", k=3)
        self.assertEqual(len(result), 2)  # one per source
        self.assertTrue(any("a.md" in s for s in result))
        self.assertTrue(any("b.md" in s for s in result))


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

    def test_reingest_deletes_stale_chunks(self):
        """Re-indexing a file must drop its previous chunks before upserting."""
        from consilium import rag
        col = _mock_collection()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "notes.md"
            f.write_text("some content", encoding="utf-8")
            with patch("consilium.rag._get_collection", return_value=col):
                rag.ingest_path(str(f))
        col.delete.assert_called_once_with(where={"source": "notes.md"})

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


@unittest.skipUnless(_HAS_CHROMADB, "chromadb not installed — pip install 'consilium-py[rag]'")
class TestFilterIntegration(unittest.TestCase):
    """Exercise the real where-filter on an ephemeral ChromaDB collection.

    The mocked tests verify the where dict's *shape*; this verifies chromadb
    actually accepts and applies the flat $and (kind + confidence + verdict)
    and the doc/run kind split — no false confidence from a mock.
    """

    def test_filter_runs_on_real_chromadb(self):
        import shutil
        from consilium import rag
        from consilium.models import DeliberationInput, Report

        tmp = tempfile.mkdtemp()
        try:
            with patch("consilium.rag._CHROMA_DIR", Path(tmp)):
                def mk(verdict, conf):
                    return Report(verdict=verdict, confidence=conf,
                                  recommendation="add a health check endpoint",
                                  voices=[], mode="sequential")
                inp = DeliberationInput(proposal="add a health check endpoint")
                rag.index("good", inp, mk("GO", 0.9))       # kept
                rag.index("blocked", inp, mk("STOP", 0.9))  # excluded by verdict
                rag.index("weak", inp, mk("GO", 0.2))       # excluded by confidence
                rag.ingest_path(str(_write(tmp, "guide.md", "how to add a health check endpoint")))

                runs = rag.retrieve("add a health endpoint", k=5)
                self.assertTrue(runs, "the GO/high-confidence run should be retrieved")
                self.assertTrue(all("STOP" not in s for s in runs), "STOP excluded")

                docs = rag.retrieve_docs("add a health check endpoint", k=5)
                self.assertTrue(any("guide.md" in d for d in docs), "ingested doc retrieved")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _write(root: str, name: str, text: str) -> str:
    p = Path(root) / name
    p.write_text(text, encoding="utf-8")
    return str(p)


if __name__ == "__main__":
    unittest.main()
