# TODO

## Status (2026-07-02)

Roadmap audited via `/senate` (9-senator MODIFY verdict, 2 rounds — see
`runs/senate/2026-07-02_142843-consilium-py-rag-roadmap-implementation.json`
in the Senate repo). Key rescope: items 1+2 were merged into the existing
`rag.py` machinery (a `kind` metadata field, not a parallel `docs.py`
subsystem — Musk's finding), and items 3/7/8 were dropped as premature for
a corpus that doesn't exist yet. Implemented: 4, 5, 6, 1+2 (merged), 9, 10.

## A. Doc-RAG — corpusul de documente legacy (cea mai valoroasă)

1. [x] ~~`docs.py`~~ Implemented as `consilium ingest <path>` in `rag.py` (not a
   separate module — see status note above) — loader (md/txt/py/rst la v1) →
   chunking cu overlap (1200 chars / 200 overlap) → embed → upsert în
   `consilium_runs_v2` cu `metadata={"kind":"doc", "source", "chunk_index"}`.
   Guards: fișiere >1MB skip, binare (UTF-8 decode fail) skip, symlink în
   afara root-ului skip.
2. [x] Injectarea în `deliberate()` a unui bloc separat „RELEVANT DOCS", distinct de
   „SIMILAR PAST DECISIONS", cu citarea sursei (`[source#chunk_index]`) în output.
   `build_rag_context()` combină ambele blocuri.
3. [ ] **Deferred** — Corpus pinuit/versionat. Musk: nu există încă un corpus de
   pinuit — pinning-ul unui corpus gol e prematur. Revizitează după ce
   `consilium ingest` are utilizare reală.

## B. Fixuri pe RAG-ul de rulări existent (`rag.py`)

4. [x] Embed document mai bogat — `index()` acum embed `proposal + context`.
5. [x] Cosine + colecție versionată — `metadata={"hnsw:space":"cosine"}`,
   colecție redenumită `consilium_runs_v2`, `_MAX_DISTANCE` recalibrat la
   `0.55` și validat empiric în `tests/test_rag.py::TestMaxDistanceCalibration`
   (perechi proposal similare/diferite, embedding real). Hint pe stderr dacă
   colecția veche L2 are date orfane.
6. [x] Filtru la query (`where`) — exclude rulări `STOP`/`BLOCK` și
   `confidence < 0.5`. Livrat ca default de design, fără pretenție de
   îmbunătățire empirică măsurată (per Deming — vezi requirement doc).

## C. Calitate transversală

7. [ ] **Deferred** — Reranking opțional (`[rerank]` extra). Musk: optimizare
   pentru un corpus/scală care nu există încă — nimic de reranked cu
   `k=3` pe un index mic.
8. [ ] **Deferred** — Embedding function pluggable (`CONSILIUM_EMBED`). Musk:
   surface de config speculativă, în conflict cu #3 (pinning); Dimon: fără un
   check de compatibilitate, un swap silențios amestecă spații de embedding
   incompatibile și întoarce rezultate garbage fără eroare. Revizitează cu
   ambele rezolvate simultan dacă redeschis.

## D. Ergonomie

9. [x] `--rag` + env `CONSILIUM_RAG` (flag existent, env var nou pentru
   default local fără să-l impună în CI).

## E. Dovadă (diferențiatorul pentru rol de eval pipelines)

10. [x] `scripts/eval_rag.py` — set etichetat manual (n=19 perechi
    query → fișier sursă așteptat, verificate contra conținutului real din
    README.md/CLAUDE.md/requirements/*.md, nu fabricate), măsoară recall@k
    și MRR pe o colecție ChromaDB efemeră (nu ~/.consilium/chroma/). Raportează
    ca fracție + tabel per-query, nu procent agregat brut (per Deming).
    Rulare manuală: `python scripts/eval_rag.py` — rezultat curent real:
    11/19, MRR 0.456 (nu un test CI, e o măsurătoare).

**Guardrail de scop:** A (doc-RAG) a fost o zi de lucru, nu o după-amiază.
