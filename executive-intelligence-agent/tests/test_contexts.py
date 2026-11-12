"""App-context routing: one agent, prompt and tools chosen per request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.contexts import (
    CONTEXTS,
    DEFAULT_CONTEXT,
    ContextSettings,
    describe_contexts,
    parse_settings,
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


SPACE = "0123456789abcdef0123456789abcdef"


def test_agent_toml_binds_no_genie_spaces():
    """Genie spaces come from each context's settings, since their ids differ per workspace."""
    from databricks_agentkit.langgraph import genie_tools

    assert genie_tools() == []


def test_settings_genie_spaces_become_named_tools():
    from agent.agent import settings_genie_tools

    settings = parse_settings({"tools": {"genie": [{"name": "ci_data", "space_id": SPACE}]}})
    names = {t.name for t in settings_genie_tools(settings, workspace_client_for=None)}
    assert names == {"ci_data_ask", "ci_data_poll", "ci_data_query_result"}


def test_settings_genie_tools_refuse_app_credentials_when_deployed(monkeypatch):
    from agent.agent import settings_genie_tools

    from databricks_agentkit.runtime.auth import AuthError

    monkeypatch.setenv("DATABRICKS_APP_NAME", "agent-bricks-exec-intel-agent")
    settings = parse_settings({"tools": {"genie": [{"name": "ci_data", "space_id": SPACE}]}})
    with pytest.raises(AuthError):
        settings_genie_tools(settings, workspace_client_for=None)


def test_parse_settings_drops_malformed_entries():
    settings = parse_settings({
        "prompt": "  Custom section.  ",
        "tools": {
            "builtin": ["get_current_time", 7],
            "genie": [
                {"name": "ok_space", "space_id": SPACE, "title": "T", "description": "D"},
                {"name": "Bad-Name", "space_id": SPACE},
                {"name": "bad_id", "space_id": "../../etc"},
                {"name": "ok_space", "space_id": SPACE},
                "not an object",
            ],
        },
    })
    assert settings.prompt == "Custom section."
    assert settings.builtin_tools == ("get_current_time",)
    assert [s.name for s in settings.genie_spaces] == ["ok_space"]
    assert parse_settings(None) == ContextSettings()
    assert parse_settings("nonsense") == ContextSettings()


def test_settings_replace_prompt_and_describe_data_tools():
    settings = parse_settings({
        "prompt": "Focus on renewals.",
        "tools": {"genie": [{"name": "ci_data", "space_id": SPACE, "title": "Customer Intelligence data"}]},
    })
    prompt = system_prompt(CONTEXTS["customer-intelligence"], settings)
    assert "Focus on renewals." in prompt
    assert CONTEXTS["customer-intelligence"].prompt not in prompt
    assert "- ci_data: Customer Intelligence data" in prompt
    assert "Data tools" not in system_prompt(CONTEXTS["customer-intelligence"])


def test_settings_builtin_list_replaces_patterns_for_local_tools_only():
    settings = parse_settings({"tools": {"builtin": []}})
    names = {
        t.name
        for t in select_tools(CONTEXTS["market-intelligence"], TOOLS, settings, local_names=["get_current_time"])
    }
    assert names == {"market_share"}


def test_describe_contexts_lists_defaults_for_settings_page():
    described = describe_contexts([get_current_time, market_share])
    by_id = {c["id"]: c for c in described["contexts"]}
    assert set(by_id) == set(CONTEXTS)
    assert by_id["executive"]["builtin_tools"] == ["get_current_time"]
    assert by_id["executive"]["prompt"] == CONTEXTS["executive"].prompt
    assert {t["name"] for t in described["builtin_tools"]} == {"get_current_time", "market_share"}


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
    settings = {"prompt": "Custom."}
    payload = {"messages": [{"role": "user", "content": "hi"}], "context": "signals", "settings": settings}

    await adapter.invoke(payload, context)

    assert seen["context"] == "signals"
    assert seen["settings"] == settings
