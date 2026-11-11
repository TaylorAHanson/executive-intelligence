"""App-context routing: one agent, prompt and tools chosen per request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.contexts import (
    CONTEXTS,
    DEFAULT_CONTEXT,
    resolve_context,
    select_tools,
    system_prompt,
)
from langchain_core.tools import tool


@tool
def market_share(company: str) -> str:
    """Market share for a company."""
    return company


@tool
def signal_lookup(signal_id: str) -> str:
    """Look up a surfaced signal."""
    return signal_id


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return "now"


TOOLS = [market_share, signal_lookup, get_current_time]


def test_unknown_or_missing_context_falls_back_to_default():
    assert resolve_context(None).id == DEFAULT_CONTEXT
    assert resolve_context("").id == DEFAULT_CONTEXT
    assert resolve_context("no-such-section").id == DEFAULT_CONTEXT


def test_default_context_offers_every_tool():
    assert select_tools(CONTEXTS[DEFAULT_CONTEXT], TOOLS) == TOOLS


def test_context_filters_tools_by_name_pattern():
    names = {t.name for t in select_tools(CONTEXTS["market-intelligence"], TOOLS)}
    assert names == {"market_share", "get_current_time"}
    names = {t.name for t in select_tools(CONTEXTS["signals"], TOOLS)}
    assert names == {"signal_lookup", "get_current_time"}
    names = {t.name for t in select_tools(CONTEXTS["executive"], TOOLS)}
    assert names == {"get_current_time"}


def test_each_dashboard_context_gets_only_its_own_genie_space():
    """The Genie bindings in agent.toml produce tool names that each dashboard's pattern matches."""
    from databricks_agentkit.langgraph import genie_tools

    tools = genie_tools()
    exec_names = {"exec_data_ask", "exec_data_poll", "exec_data_query_result"}
    ci_names = {"ci_data_ask", "ci_data_poll", "ci_data_query_result"}
    assert {t.name for t in tools} == exec_names | ci_names
    assert {t.name for t in select_tools(CONTEXTS["executive"], tools)} == exec_names
    assert {t.name for t in select_tools(CONTEXTS["customer-intelligence"], tools)} == ci_names
    assert not select_tools(CONTEXTS["market-intelligence"], tools)
    assert not select_tools(CONTEXTS["signals"], tools)


def test_client_context_ids_exist_in_the_agent():
    """Every id in the client's agentContexts.ts must be a context here, or it silently falls back."""
    import re
    from pathlib import Path

    client = Path(__file__).resolve().parents[2] / "executive-intelligence-app" / "src" / "agentContexts.ts"
    ids = set(re.findall(r"\{ id: '([^']+)'", client.read_text()))
    assert ids and ids <= set(CONTEXTS)


def test_system_prompt_includes_context_section():
    prompt = system_prompt(CONTEXTS["market-intelligence"])
    assert "Executive Intelligence agent" in prompt
    assert "Market Intelligence" in prompt


@pytest.mark.asyncio
async def test_adapter_passes_context_to_graph_and_run(monkeypatch):
    import runtime.adapter as adapter

    seen = {}

    async def fake_run_agent(agent_input, **kwargs):
        seen.update(kwargs)
        if False:
            yield None

    monkeypatch.setattr(adapter, "run_agent", fake_run_agent)
    context = SimpleNamespace(invocation_id="inv-1", session_id="s-1", emit=AsyncMock())
    payload = {"messages": [{"role": "user", "content": "hi"}], "context": "signals"}

    await adapter.invoke(payload, context)

    assert seen["context"] == "signals"
