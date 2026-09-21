---
id: CPYEXT-RAGEXTRACT-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYEXT-RAG-001]
---

# RAG document extractors for non-plain-text formats

Turns PDF, DOCX, HTML and CSV files into ingestable text for the RAG index (CPYEXT-RAG-001, CPYEXT-DOCRAG-001), loudly when an optional dependency is missing, and deliberately refuses formats whose extraction would mislead retrieval.

## WHAT — Contract

- **Document extractors.** `extract_text(path)` shall return the ingestable text for a supported suffix, `None` for an unsupported one, and raise `ImportError` with a `pip install 'consilium-py[docs]'` hint when the format is supported but its optional dependency is absent — a missing extractor must be loud, never a silently empty document. The registry `_EXTRACTORS` maps suffix → callable: `.pdf` (PyMuPDF), `.docx` (python-docx), `.html`/`.htm` (beautifulsoup4, `<script>`/`<style>` stripped), `.csv` (stdlib). Plain-text suffixes bypass the registry.
- **CSV is summarised, not embedded.** `_extract_csv` shall emit the filename, column list, row count, and at most `_CSV_PREVIEW_ROWS` rows labelled as shape-only, and shall NOT index the remaining rows. Rationale: top-k cosine retrieval over table rows returns arbitrary rows from which a model computes confident wrong aggregates; a figure must come from a deterministic query, not from retrieval. `.sql` is out of scope for the same reason (a schema script is not data).
- Images shall not be ingested: OCR requires an external `tesseract` binary and a silently empty extraction is worse than an explicit skip.
- `_MAX_INGEST_FILE_BYTES` shall be 10 MB, not 1 MB — a single PDF routinely exceeds the old cap.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given an `.html`, `.docx`, `.pdf` or `.csv` file, when `extract_text()` is called, then it returns extracted text (HTML free of `<script>`/`<style>`, CSV a schema summary whose tail rows are absent); an unsupported suffix returns `None`; and a supported suffix with its dependency missing raises `ImportError` naming `consilium-py[docs]` (tested-by `tests/test_rag.py::TestDocumentExtractors`).
- Given an HTML file, when `ingest_path()` runs, then the stored chunk contains the extracted text and NOT the raw markup — the discriminating assertion, since raw `read_text` would also contain the body substring (tested-by `tests/test_rag.py::TestDocumentExtractors::test_ingest_routes_html_through_the_extractor`).

## WHERE — Current implementation

- `src/consilium/rag.py` (`extract_text`, `_EXTRACTORS`, `_extract_*`, `_MAX_INGEST_FILE_BYTES`)
