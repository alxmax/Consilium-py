# TODO

## A. Doc-RAG — corpusul de documente legacy (cea mai valoroasă)

1. `docs.py` + comanda `consilium ingest <path>` — loader (md/txt/cod la v1) → chunking cu
   overlap → embed → upsert într-o colecție nouă `consilium_docs`, cu metadata `source` +
   `chunk_index`. Fișiere: nou `src/consilium/docs.py` + o comandă în `cli.py`. De ce: e
   singura cale prin care implementezi chunking real (conceptul de pe CV) și primul RAG
   care ingeră documente externe. Efort: **L**.
2. Injectarea în `deliberate()` a unui bloc separat „RELEVANT DOCS", distinct de „SIMILAR
   PAST DECISIONS", cu citarea sursei în output. Fișier: `__init__.py` + un `retrieve()` în
   `docs.py`. De ce: vocea Control face deja „glossary compliance" — un corpus îi dă exact
   ce să verifice și poate cita „conform CODING_STANDARDS.md". Depinde de #1. Efort: **M**.
3. Corpus pinuit/versionat — comiți corpusul în repo + model de embedding fix → retrieval
   reproductibil. De ce: rezolvă tensiunea cu determinismul; calea „docs" (corpus fix) e
   singura care poate fi vreodată default-safe, spre deosebire de memoria de rulări.
   Efort: **S** (decizie de design + un manifest).

## B. Fixuri pe RAG-ul de rulări existent (`rag.py`)

4. Embed document mai bogat — în `index()`, `documents = proposal + context`, nu doar
   `proposal`. De ce: cea mai mare îmbunătățire de calitate dintr-o singură modificare;
   acum match-uiești pe un string subțire. Efort: **S**.
5. Cosine + colecție versionată — creezi colecția cu `metadata={"hnsw:space":"cosine"}`, o
   redenumești (`consilium_runs_v2`) ca să nu coliziune cu indexul L2 vechi, și recalibrezi
   `_MAX_DISTANCE`. De ce: default-ul Chroma e L2; pragul actual de 0.35 probabil taie
   aproape tot silențios. Efort: **S**.
6. Filtru la query (`where`) — recuperezi doar rulări cu `confidence >= prag` și `verdict`
   care nu e `STOP`/`BLOCK`. De ce: acum surfacezi și decizii slabe ca „past guidance".
   Efort: **S**.

## C. Calitate transversală

7. Reranking opțional (`[rerank]` extra) — retrieve top-10 → cross-encoder
   (ms-marco-MiniLM) → top-3. Se aplică mai ales pe docs. De ce: al doilea concept de pe CV,
   implementat pe bune; util doar când ai corpus mare de chunk-uri. Efort: **M**.
8. Embedding function pluggable — env `CONSILIUM_EMBED` pentru MiniLM ↔ OpenAI (comentariul
   deja e în cod). De ce: demonstrezi că înțelegi trade-off-ul local vs API. Efort: **S**.

## D. Ergonomie

9. `--rag/--no-rag` + env `CONSILIUM_RAG` — default livrat off, dar poți face default-on pe
   mașina locală cu o setare, fără să-l impui în CI. Fișiere: `cli.py` + `__init__.py`.
   Efort: **S**.

## E. Dovadă (diferențiatorul pentru rol de eval pipelines)

10. `eval_rag.py` — set mic etichetat (query → chunk/run așteptat), măsori recall@k / MRR,
    before vs. after. De ce: îți dă numere care închid definitiv întrebarea „chiar înțelegi
    RAG?". Efort: **M**.

## Ordine recomandată (cale MVP)

`4 → 5 → 6` (fixuri rapide) → `1 → 2` (doc-RAG, miezul) → `10` (dovezi cu numere) →
`7 → 3 → 8 → 9` (rafinări).

**Guardrail de scop:** A (doc-RAG) e o zi de lucru, nu o după-amiază — nu-l subestima. Restul
sunt felii mici, bifabile una câte una.
