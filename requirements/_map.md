---
generated: 2026-06-06 10:45
nodes: 7
edges: 11
---

# Requirement Map

## System Map

_Capabilities grouped by area; thick border = bus; arrows = `depends_on`. Edges into the bus/hubs are hidden (the Dependency Map shows area-level coupling)._

```mermaid
graph LR
  subgraph sg_CPYBUS["CPYBUS"]
    CPYBUS_AGG_001["Sequential aggregation — veto cascade, voice extraction, Report assembly<br><small>CPYBUS-AGG-001</small>"]
    CPYBUS_API_001["Public Python API — deliberate()<br><small>CPYBUS-API-001</small>"]
    CPYBUS_CLI_001["CLI interface — deliberate and check commands<br><small>CPYBUS-CLI-001</small>"]
    CPYBUS_VOI_001["Voice dispatch — prompt loading, API call, JSON extraction<br><small>CPYBUS-VOI-001</small>"]
  end
  subgraph sg_CPYMOD["CPYMOD"]
    CPYMOD_DIA_001["Dialectic deliberation mode — Sequential + Skeptic challenger<br><small>CPYMOD-DIA-001</small>"]
    CPYMOD_SEQ_001["Sequential deliberation mode<br><small>CPYMOD-SEQ-001</small>"]
    CPYMOD_TRI_001["Trias deliberation mode — 3 parallel personalities with democratic vote<br><small>CPYMOD-TRI-001</small>"]
  end
  CPYBUS_API_001 --> CPYMOD_SEQ_001
  CPYBUS_API_001 --> CPYMOD_DIA_001
  CPYBUS_API_001 --> CPYMOD_TRI_001
  CPYMOD_DIA_001 --> CPYMOD_SEQ_001
  style CPYBUS_AGG_001 stroke-width:3px
  style CPYBUS_API_001 stroke-width:3px
  style CPYBUS_CLI_001 stroke-width:3px
  style CPYBUS_VOI_001 stroke-width:3px
```

## Requirement-to-Code

_Each requirement → its code; arrow label = role (`implements` / `tested-by`). Red = confirmed but no code linked (a gap); grey = baseline/draft, not linked yet (expected)._

```mermaid
graph LR
  CPYBUS_AGG_001["Sequential aggregation — veto cascade, voice extraction, Report assembly<br><small>CPYBUS-AGG-001</small>"]
  f_src_consilium_aggregator_py_2["src/consilium/aggregator.py:2"]
  CPYBUS_AGG_001 -->|implements| f_src_consilium_aggregator_py_2
  f_tests_test_sequential_py_3["tests/test_sequential.py:3"]
  CPYBUS_AGG_001 -->|tested-by| f_tests_test_sequential_py_3
  CPYBUS_API_001["Public Python API — deliberate()<br><small>CPYBUS-API-001</small>"]
  f_src_consilium___init___py_1["src/consilium/__init__.py:1"]
  CPYBUS_API_001 -->|implements| f_src_consilium___init___py_1
  CPYBUS_CLI_001["CLI interface — deliberate and check commands<br><small>CPYBUS-CLI-001</small>"]
  f_src_consilium_cli_py_2["src/consilium/cli.py:2"]
  CPYBUS_CLI_001 -->|implements| f_src_consilium_cli_py_2
  CPYBUS_VOI_001["Voice dispatch — prompt loading, API call, JSON extraction<br><small>CPYBUS-VOI-001</small>"]
  f_src_consilium_voices_py_2["src/consilium/voices.py:2"]
  CPYBUS_VOI_001 -->|implements| f_src_consilium_voices_py_2
  CPYMOD_DIA_001["Dialectic deliberation mode — Sequential + Skeptic challenger<br><small>CPYMOD-DIA-001</small>"]
  f_src_consilium_modes_dialectic_py_1["src/consilium/modes/dialectic.py:1"]
  CPYMOD_DIA_001 -->|implements| f_src_consilium_modes_dialectic_py_1
  f_tests_test_dialectic_py_2["tests/test_dialectic.py:2"]
  CPYMOD_DIA_001 -->|tested-by| f_tests_test_dialectic_py_2
  CPYMOD_SEQ_001["Sequential deliberation mode<br><small>CPYMOD-SEQ-001</small>"]
  f_src_consilium_modes_sequential_py_1["src/consilium/modes/sequential.py:1"]
  CPYMOD_SEQ_001 -->|implements| f_src_consilium_modes_sequential_py_1
  f_tests_test_sequential_py_2["tests/test_sequential.py:2"]
  CPYMOD_SEQ_001 -->|tested-by| f_tests_test_sequential_py_2
  CPYMOD_TRI_001["Trias deliberation mode — 3 parallel personalities with democratic vote<br><small>CPYMOD-TRI-001</small>"]
  f_src_consilium_modes_trias_py_2["src/consilium/modes/trias.py:2"]
  CPYMOD_TRI_001 -->|implements| f_src_consilium_modes_trias_py_2
  f_tests_test_trias_py_2["tests/test_trias.py:2"]
  CPYMOD_TRI_001 -->|tested-by| f_tests_test_trias_py_2
```

## Dependency Map

_Area-level coupling: one box per area (N caps), arrow A->B = some capability in A depends on one in B. The System Map has the per-capability detail._

```mermaid
graph LR
  a_CPYBUS["CPYBUS<br><small>4 caps</small>"]
  a_CPYMOD["CPYMOD<br><small>3 caps</small>"]
  a_CPYBUS --> a_CPYMOD
  a_CPYMOD --> a_CPYBUS
  style a_CPYBUS stroke-width:3px
```

## Risk & Unknowns

_Requirements needing attention: red = unimplemented (confirmed, no code); orange = unreviewed (promote after review); yellow = untested (implemented but no tested-by — set `test_exempt` to silence), or unverified-intent (open verify-intent question)._

```mermaid
graph LR
  subgraph sg_CPYBUS["CPYBUS"]
    CPYBUS_AGG_001["Sequential aggregation — veto cascade, voice extraction, Report assembly<br><small>CPYBUS-AGG-001</small><br>unreviewed, unverified-intent"]
    CPYBUS_API_001["Public Python API — deliberate()<br><small>CPYBUS-API-001</small><br>unreviewed, untested, unverified-intent"]
    CPYBUS_CLI_001["CLI interface — deliberate and check commands<br><small>CPYBUS-CLI-001</small><br>unreviewed, untested, unverified-intent"]
    CPYBUS_VOI_001["Voice dispatch — prompt loading, API call, JSON extraction<br><small>CPYBUS-VOI-001</small><br>unreviewed, untested, unverified-intent"]
  end
  subgraph sg_CPYMOD["CPYMOD"]
    CPYMOD_DIA_001["Dialectic deliberation mode — Sequential + Skeptic challenger<br><small>CPYMOD-DIA-001</small><br>unreviewed, unverified-intent"]
    CPYMOD_SEQ_001["Sequential deliberation mode<br><small>CPYMOD-SEQ-001</small><br>unreviewed, unverified-intent"]
    CPYMOD_TRI_001["Trias deliberation mode — 3 parallel personalities with democratic vote<br><small>CPYMOD-TRI-001</small><br>unreviewed, unverified-intent"]
  end
  style CPYBUS_AGG_001 fill:#fff3cd,stroke:#a66,color:#630
  style CPYBUS_API_001 fill:#fff3cd,stroke:#a66,color:#630
  style CPYBUS_CLI_001 fill:#fff3cd,stroke:#a66,color:#630
  style CPYBUS_VOI_001 fill:#fff3cd,stroke:#a66,color:#630
  style CPYMOD_DIA_001 fill:#fff3cd,stroke:#a66,color:#630
  style CPYMOD_SEQ_001 fill:#fff3cd,stroke:#a66,color:#630
  style CPYMOD_TRI_001 fill:#fff3cd,stroke:#a66,color:#630
```

### Risk Table

| ID | status | members | dependents | risks | recommendation |
| --- | --- | --- | --- | --- | --- |
| CPYBUS-AGG-001 | baseline | 2 | 2 | unreviewed, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
| CPYBUS-API-001 | baseline | 1 | 1 | unreviewed, untested, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Implemented but no `tested-by` member: write an acceptance test and tag it `# tested-by: <ID>`, or set `test_exempt: <reason>` in the frontmatter to acknowledge it intentionally and silence this signal. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
| CPYBUS-CLI-001 | baseline | 1 | 0 | unreviewed, untested, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Implemented but no `tested-by` member: write an acceptance test and tag it `# tested-by: <ID>`, or set `test_exempt: <reason>` in the frontmatter to acknowledge it intentionally and silence this signal. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
| CPYBUS-VOI-001 | baseline | 1 | 4 | unreviewed, untested, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Implemented but no `tested-by` member: write an acceptance test and tag it `# tested-by: <ID>`, or set `test_exempt: <reason>` in the frontmatter to acknowledge it intentionally and silence this signal. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
| CPYMOD-DIA-001 | baseline | 2 | 1 | unreviewed, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
| CPYMOD-SEQ-001 | baseline | 2 | 2 | unreviewed, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
| CPYMOD-TRI-001 | baseline | 2 | 1 | unreviewed, unverified-intent | Draft/baseline, not yet validated: review the contract, wire its `tested-by` tests, then promote to `confirmed`. Until then it is tracked, not enforced. Has open `## WHAT — Verify intent` question(s): run `reqmap.py findings`, resolve each in `requirements/_findings.md`, then fold the answer into the Contract or delete the bullet. |
