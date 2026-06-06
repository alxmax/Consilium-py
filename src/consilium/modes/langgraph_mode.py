"""LangGraph orchestration mode — Conservator→Generator→Control as a StateGraph.
# implements: CPYEXT-LG-001
"""
from __future__ import annotations

from typing import TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError:
    raise ImportError(
        "LangGraph mode requires langgraph. Install with: pip install 'consilium-py[langgraph]'"
    )

from consilium.aggregator import aggregate_sequential
from consilium.models import DeliberationInput, Report
from consilium.voices import call_voice, load_prompt


class DeliberationState(TypedDict):
    proposal: str
    context: str
    model: str
    conservator_out: str
    generator_out: str
    control_out: str


def _conservator_node(state: DeliberationState) -> DeliberationState:
    msg = f"PROPOSAL:\n{state['proposal']}"
    if state["context"]:
        msg += f"\n\nCONTEXT:\n{state['context']}"
    out = call_voice("conservator", load_prompt("conservator"), msg, state["model"])
    return {**state, "conservator_out": out}


def _generator_node(state: DeliberationState) -> DeliberationState:
    msg = f"PROPOSAL:\n{state['proposal']}"
    if state["context"]:
        msg += f"\n\nCONTEXT:\n{state['context']}"
    msg += f"\n\n--- CONSERVATOR OUTPUT ---\n{state['conservator_out']}"
    out = call_voice("generator", load_prompt("generator"), msg, state["model"])
    return {**state, "generator_out": out}


def _control_node(state: DeliberationState) -> DeliberationState:
    msg = f"PROPOSAL:\n{state['proposal']}"
    if state["context"]:
        msg += f"\n\nCONTEXT:\n{state['context']}"
    msg += f"\n\n--- CONSERVATOR OUTPUT ---\n{state['conservator_out']}"
    msg += f"\n\n--- GENERATOR OUTPUT ---\n{state['generator_out']}"
    out = call_voice("control", load_prompt("control"), msg, state["model"])
    return {**state, "control_out": out}


def _aggregate_node(state: DeliberationState) -> DeliberationState:
    # Final state is collected by run_langgraph; this node is a pass-through.
    return state


def _build_graph():
    g: StateGraph = StateGraph(DeliberationState)
    g.add_node("conservator_node", _conservator_node)
    g.add_node("generator_node", _generator_node)
    g.add_node("control_node", _control_node)
    g.add_node("aggregate_node", _aggregate_node)
    g.set_entry_point("conservator_node")
    g.add_edge("conservator_node", "generator_node")
    g.add_edge("generator_node", "control_node")
    g.add_edge("control_node", "aggregate_node")
    g.add_edge("aggregate_node", END)
    # To stream node outputs:    swap graph.invoke() for graph.astream_events()
    # To add human-in-the-loop:  compile(interrupt_after=["conservator_node"],
    #                                    checkpointer=MemorySaver())
    #                            then resume via graph.invoke(Command(resume=edit),
    #                                    config={"configurable": {"thread_id": tid}})
    return g.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_langgraph(inp: DeliberationInput) -> Report:
    """Run the Conservator→Generator→Control pipeline as a LangGraph StateGraph."""
    initial: DeliberationState = {
        "proposal": inp.proposal,
        "context": inp.context,
        "model": inp.model,
        "conservator_out": "",
        "generator_out": "",
        "control_out": "",
    }
    final = _get_graph().invoke(initial)
    report = aggregate_sequential(
        final["conservator_out"],
        final["generator_out"],
        final["control_out"],
        inp,
    )
    return Report(**{**report.model_dump(), "mode": "langgraph"})
