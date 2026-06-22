---
generated: 2026-06-23 00:13
nodes: 11
edges: 22
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
    CPYBUS_SKEPTIC_001["Shared Skeptic challenge<br><small>CPYBUS-SKEPTIC-001</small>"]
    CPYBUS_VOI_001["Voice dispatch — prompt loading, API call, JSON extraction<br><small>CPYBUS-VOI-001</small>"]
  end
  subgraph sg_CPYEXT["CPYEXT"]
    CPYEXT_LG_001["LangGraph orchestration mode<br><small>CPYEXT-LG-001</small>"]
    CPYEXT_LTL_001["Provider-agnostic voice dispatch via LiteLLM<br><small>CPYEXT-LTL-001</small>"]
    CPYEXT_RAG_001["RAG context injection from past deliberation runs<br><small>CPYEXT-RAG-001</small>"]
  end
  subgraph sg_CPYMOD["CPYMOD"]
    CPYMOD_DIA_001["Dialectic deliberation mode — Sequential + Skeptic challenger<br><small>CPYMOD-DIA-001</small>"]
    CPYMOD_SEQ_001["Sequential deliberation mode<br><small>CPYMOD-SEQ-001</small>"]
    CPYMOD_TRI_001["Trias deliberation mode — 3 parallel personalities + post-vote Skeptic<br><small>CPYMOD-TRI-001</small>"]
  end
  CPYBUS_API_001 --> CPYMOD_SEQ_001
  CPYBUS_API_001 --> CPYMOD_DIA_001
  CPYBUS_API_001 --> CPYMOD_TRI_001
  CPYMOD_DIA_001 --> CPYMOD_SEQ_001
  style CPYBUS_AGG_001 stroke-width:3px
  style CPYBUS_API_001 stroke-width:3px
  style CPYBUS_CLI_001 stroke-width:3px
  style CPYBUS_SKEPTIC_001 stroke-width:3px
  style CPYBUS_VOI_001 stroke-width:3px
```

## Requirement-to-Code

_Each requirement → its code; arrow label = role (`implements` / `tested-by`). Red = confirmed but no code linked (a gap); grey = baseline/draft, not linked yet (expected)._

```mermaid
graph LR
  CPYBUS_AGG_001["Sequential aggregation — veto cascade, voice extraction, Report assembly<br><small>CPYBUS-AGG-001</small>"]
  f_src_consilium_aggregator_py_6["src/consilium/aggregator.py:6"]
  CPYBUS_AGG_001 -->|implements| f_src_consilium_aggregator_py_6
  f_tests_test_sequential_py_3["tests/test_sequential.py:3"]
  CPYBUS_AGG_001 -->|tested-by| f_tests_test_sequential_py_3
  CPYBUS_API_001["Public Python API — deliberate()<br><small>CPYBUS-API-001</small>"]
  f_src_consilium___init___py_1["src/consilium/__init__.py:1"]
  CPYBUS_API_001 -->|implements| f_src_consilium___init___py_1
  f_tests_test_api_py_2["tests/test_api.py:2"]
  CPYBUS_API_001 -->|tested-by| f_tests_test_api_py_2
  CPYBUS_CLI_001["CLI interface — deliberate and check commands<br><small>CPYBUS-CLI-001</small>"]
  f_src_consilium_cli_py_2["src/consilium/cli.py:2"]
  CPYBUS_CLI_001 -->|implements| f_src_consilium_cli_py_2
  f_tests_test_cli_py_2["tests/test_cli.py:2"]
  CPYBUS_CLI_001 -->|tested-by| f_tests_test_cli_py_2
  f_tests_test_cli_io_py_4["tests/test_cli_io.py:4"]
  CPYBUS_CLI_001 -->|tested-by| f_tests_test_cli_io_py_4
  CPYBUS_SKEPTIC_001["Shared Skeptic challenge<br><small>CPYBUS-SKEPTIC-001</small>"]
  f_src_consilium_skeptic_py_7["src/consilium/skeptic.py:7"]
  CPYBUS_SKEPTIC_001 -->|implements| f_src_consilium_skeptic_py_7
  f_tests_test_skeptic_py_2["tests/test_skeptic.py:2"]
  CPYBUS_SKEPTIC_001 -->|tested-by| f_tests_test_skeptic_py_2
  CPYBUS_VOI_001["Voice dispatch — prompt loading, API call, JSON extraction<br><small>CPYBUS-VOI-001</small>"]
  f_src_consilium_voices_py_2["src/consilium/voices.py:2"]
  CPYBUS_VOI_001 -->|implements| f_src_consilium_voices_py_2
  f_tests_test_voices_py_2["tests/test_voices.py:2"]
  CPYBUS_VOI_001 -->|tested-by| f_tests_test_voices_py_2
  CPYEXT_LG_001["LangGraph orchestration mode<br><small>CPYEXT-LG-001</small>"]
  f_src_consilium_modes_langgraph_mode_py_2["src/consilium/modes/langgraph_mode.py:2"]
  CPYEXT_LG_001 -->|implements| f_src_consilium_modes_langgraph_mode_py_2
  f_tests_test_langgraph_py_2["tests/test_langgraph.py:2"]
  CPYEXT_LG_001 -->|tested-by| f_tests_test_langgraph_py_2
  CPYEXT_LTL_001["Provider-agnostic voice dispatch via LiteLLM<br><small>CPYEXT-LTL-001</small>"]
  f_src_consilium___init___py_2["src/consilium/__init__.py:2"]
  CPYEXT_LTL_001 -->|implements| f_src_consilium___init___py_2
  f_src_consilium_cli_py_3["src/consilium/cli.py:3"]
  CPYEXT_LTL_001 -->|implements| f_src_consilium_cli_py_3
  f_src_consilium_voices_py_3["src/consilium/voices.py:3"]
  CPYEXT_LTL_001 -->|implements| f_src_consilium_voices_py_3
  f_tests_test_api_py_3["tests/test_api.py:3"]
  CPYEXT_LTL_001 -->|tested-by| f_tests_test_api_py_3
  f_tests_test_voices_py_3["tests/test_voices.py:3"]
  CPYEXT_LTL_001 -->|tested-by| f_tests_test_voices_py_3
  CPYEXT_RAG_001["RAG context injection from past deliberation runs<br><small>CPYEXT-RAG-001</small>"]
  f_src_consilium_rag_py_2["src/consilium/rag.py:2"]
  CPYEXT_RAG_001 -->|implements| f_src_consilium_rag_py_2
  f_tests_test_rag_py_2["tests/test_rag.py:2"]
  CPYEXT_RAG_001 -->|tested-by| f_tests_test_rag_py_2
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
  CPYMOD_TRI_001["Trias deliberation mode — 3 parallel personalities + post-vote Skeptic<br><small>CPYMOD-TRI-001</small>"]
  f_src_consilium_modes_trias_py_7["src/consilium/modes/trias.py:7"]
  CPYMOD_TRI_001 -->|implements| f_src_consilium_modes_trias_py_7
  f_tests_test_trias_py_2["tests/test_trias.py:2"]
  CPYMOD_TRI_001 -->|tested-by| f_tests_test_trias_py_2
```

## Dependency Map

_Area-level coupling: one box per area (N caps), arrow A->B = some capability in A depends on one in B. The System Map has the per-capability detail._

```mermaid
graph LR
  a_CPYBUS["CPYBUS<br><small>5 caps</small>"]
  a_CPYEXT["CPYEXT<br><small>3 caps</small>"]
  a_CPYMOD["CPYMOD<br><small>3 caps</small>"]
  a_CPYBUS --> a_CPYMOD
  a_CPYEXT --> a_CPYBUS
  a_CPYMOD --> a_CPYBUS
  style a_CPYBUS stroke-width:3px
```

## Risk & Unknowns

_Requirements needing attention: red = unimplemented (confirmed, no code); orange = unreviewed (promote after review); yellow = untested (implemented but no tested-by — set `test_exempt` to silence), or unverified-intent (open verify-intent question)._

```mermaid
graph LR
  ok["No risk signals detected"]
```
