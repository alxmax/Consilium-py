"""Unit tests for RAG module — chromadb mocked, temp dirs for filesystem."""
# tested-by: CPYEXT-RAG-001
# tested-by: CPYEXT-DOCRAG-001
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


class TestBuildRagBundle(unittest.TestCase):
    """The retrieved doc identifiers must escape rag.py, not only reach the model."""

    def test_returns_doc_source_ids_alongside_text(self):
        from consilium import rag
        col = _mock_collection(
            count=1,
            query_results={
                "ids": [["doc:README.md:2"]],
                "documents": [["Consilium is a deliberation engine."]],
                "metadatas": [[{"kind": "doc", "source": "README.md", "chunk_index": 2}]],
                "distances": [[0.1]],
            },
        )
        with _patched(col), patch.object(rag, "retrieve", return_value=[]):
            text, sources = rag.build_rag_bundle("What is consilium?")
        self.assertIn("RELEVANT DOCS", text)
        self.assertEqual(sources, ["README.md#2"])

    def test_empty_index_returns_empty_text_and_no_sources(self):
        from consilium import rag
        col = _mock_collection(count=0)
        with _patched(col), redirect_stderr(io.StringIO()):
            text, sources = rag.build_rag_bundle("Add health check")
        self.assertEqual(text, "")
        self.assertEqual(sources, [])


class TestTenantScoping(unittest.TestCase):
    """Two modes: tenant=None keeps the shared single-user corpus (current
    behaviour); a tenant string scopes reads AND writes to that tenant."""

    def test_index_tags_the_run_with_the_tenant(self):
        from consilium import rag
        from consilium.models import DeliberationInput, Report
        col = _mock_collection(count=0)
        report = Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[])
        with _patched(col):
            rag.index("r1", DeliberationInput(proposal="x"), report, tenant="acme")
        self.assertEqual(col.upsert.call_args.kwargs["metadatas"][0]["tenant"], "acme")

    def test_index_omits_tenant_key_when_none(self):
        """Single-user mode must not write a tenant field at all."""
        from consilium import rag
        from consilium.models import DeliberationInput, Report
        col = _mock_collection(count=0)
        report = Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[])
        with _patched(col):
            rag.index("r1", DeliberationInput(proposal="x"), report)
        self.assertNotIn("tenant", col.upsert.call_args.kwargs["metadatas"][0])

    def test_retrieve_filters_by_tenant(self):
        from consilium import rag
        col = _mock_collection(count=1, query_results={
            "ids": [["r1"]], "documents": [["d"]],
            "metadatas": [[{"kind": "run", "verdict": "GO", "confidence": 0.9,
                            "recommendation": "ok", "mode": "sequential"}]],
            "distances": [[0.1]]})
        with _patched(col):
            rag.retrieve("q", tenant="acme")
        clauses = col.query.call_args.kwargs["where"]["$and"]
        self.assertIn({"tenant": "acme"}, clauses)

    def test_retrieve_without_tenant_adds_no_tenant_clause(self):
        from consilium import rag
        col = _mock_collection(count=1, query_results={
            "ids": [["r1"]], "documents": [["d"]],
            "metadatas": [[{"kind": "run", "verdict": "GO", "confidence": 0.9,
                            "recommendation": "ok", "mode": "sequential"}]],
            "distances": [[0.1]]})
        with _patched(col):
            rag.retrieve("q")
        clauses = col.query.call_args.kwargs["where"]["$and"]
        self.assertNotIn("tenant", json.dumps(clauses))

    def test_doc_retrieval_filters_by_tenant(self):
        from consilium import rag
        col = _mock_collection(count=1, query_results={
            "ids": [["doc:a.md:0"]], "documents": [["d"]],
            "metadatas": [[{"kind": "doc", "source": "a.md", "chunk_index": 0}]],
            "distances": [[0.1]]})
        with _patched(col):
            rag.retrieve_docs("q", tenant="acme")
        where = col.query.call_args.kwargs["where"]
        self.assertIn({"tenant": "acme"}, where["$and"])

    def test_ingest_tags_chunks_with_tenant(self):
        from consilium import rag
        col = _mock_collection(count=0)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.md").write_text("hello world", encoding="utf-8")
            with _patched(col):
                rag.ingest_path(tmp, tenant="acme")
        self.assertEqual(col.upsert.call_args.kwargs["metadatas"][0]["tenant"], "acme")

    def test_untagged_legacy_records_are_invisible_to_a_tenant(self):
        """Fail closed: a record written before tenancy existed carries no tenant
        key, so a scoped query must not return it."""
        from consilium import rag
        col = _mock_collection(count=1, query_results={
            "ids": [["doc:a.md:0"]], "documents": [["d"]],
            "metadatas": [[{"kind": "doc", "source": "a.md", "chunk_index": 0}]],
            "distances": [[0.1]]})
        with _patched(col):
            rag.retrieve_docs("q", tenant="acme")
        # the tenant clause is sent to chromadb, which excludes docs lacking the key
        self.assertIn({"tenant": "acme"}, col.query.call_args.kwargs["where"]["$and"])


class TestDocumentExtractors(unittest.TestCase):
    """Pluggable per-suffix extractors, each guarded by its optional dependency."""

    def test_html_is_reduced_to_visible_text(self):
        pytest.importorskip("bs4")
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.html"
            p.write_text(
                "<html><head><style>b{}</style><script>x=1</script></head>"
                "<body><h1>Title</h1><p>Body sentence.</p></body></html>",
                encoding="utf-8")
            text = rag.extract_text(p)
        self.assertIn("Title", text)
        self.assertIn("Body sentence.", text)
        self.assertNotIn("x=1", text)  # script/style stripped, not embedded

    def test_docx_paragraphs_are_extracted(self):
        docx = pytest.importorskip("docx")
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.docx"
            d = docx.Document()
            d.add_paragraph("First para.")
            d.add_paragraph("Second para.")
            d.save(str(p))
            text = rag.extract_text(p)
        self.assertIn("First para.", text)
        self.assertIn("Second para.", text)

    def test_pdf_pages_are_extracted(self):
        fitz = pytest.importorskip("fitz")
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.pdf"
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), "Hello from page one")
            doc.save(str(p))
            doc.close()
            text = rag.extract_text(p)
        self.assertIn("Hello from page one", text)

    def test_csv_yields_a_structural_summary_not_the_rows(self):
        """Numbers must not be answerable from retrieved rows — only structure."""
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "trades.csv"
            rows = ["symbol,profit"] + [f"S{i},{i * 111}" for i in range(200)]
            p.write_text("\n".join(rows), encoding="utf-8")
            text = rag.extract_text(p)
        self.assertIn("symbol", text)
        self.assertIn("profit", text)
        self.assertIn("200", text)            # row count is reported
        self.assertNotIn("S199", text)        # the tail is NOT embedded
        self.assertIn("not a source for numeric answers", text)

    def test_unsupported_suffix_returns_none(self):
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.png"
            p.write_bytes(b"\x89PNG\r\n")
            self.assertIsNone(rag.extract_text(p))

    def test_plain_text_still_works_without_any_extra(self):
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.md"
            p.write_text("# Heading", encoding="utf-8")
            self.assertIn("Heading", rag.extract_text(p))

    def test_missing_dependency_raises_with_install_hint(self):
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.pdf"
            p.write_bytes(b"%PDF-1.4")
            with patch.dict(sys.modules, {"fitz": None}):
                with self.assertRaises(ImportError) as ctx:
                    rag.extract_text(p)
        self.assertIn("consilium-py[docs]", str(ctx.exception))

    def test_ingest_routes_html_through_the_extractor(self):
        """The stored chunk must be extracted text, not raw markup."""
        pytest.importorskip("bs4")
        from consilium import rag
        col = _mock_collection(count=0)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.html").write_text(
                "<html><body><p>ingested html body</p></body></html>", encoding="utf-8")
            with _patched(col):
                n = rag.ingest_path(tmp)
        self.assertEqual(n, 1)
        stored = col.upsert.call_args.kwargs["documents"][0]
        self.assertIn("ingested html body", stored)
        self.assertNotIn("<p>", stored)  # would pass on raw read_text — the real check

    def test_ingest_skips_an_unsupported_binary(self):
        from consilium import rag
        col = _mock_collection(count=0)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            with _patched(col), redirect_stderr(io.StringIO()):
                n = rag.ingest_path(tmp)
        self.assertEqual(n, 0)


class TestStorageRootOverride(unittest.TestCase):
    """A server process must not be pinned to the OS user's home directory."""

    def test_consilium_home_redirects_runs_and_chroma(self):
        from consilium import rag
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONSILIUM_HOME": tmp}):
                self.assertEqual(rag.runs_dir(), Path(tmp) / "runs")
                self.assertEqual(rag.chroma_dir(), Path(tmp) / "chroma")

    def test_defaults_under_user_home_when_unset(self):
        from consilium import rag
        cleaned = {k: v for k, v in os.environ.items() if k != "CONSILIUM_HOME"}
        with patch.dict(os.environ, cleaned, clear=True):
            self.assertEqual(rag.runs_dir(), Path.home() / ".consilium" / "runs")
            self.assertEqual(rag.chroma_dir(), Path.home() / ".consilium" / "chroma")

    def test_save_run_writes_under_the_override(self):
        """Senate anchor: redirect storage, confirm nothing lands in the real home."""
        from consilium import rag
        from consilium.models import DeliberationInput, Report
        report = Report(verdict="GO", confidence=0.9, recommendation="ok", voices=[])
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONSILIUM_HOME": tmp}):
                written = rag.save_run("run-1", DeliberationInput(proposal="x"), report)
            self.assertEqual(written.parent, Path(tmp) / "runs")
            self.assertTrue(written.exists())


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
