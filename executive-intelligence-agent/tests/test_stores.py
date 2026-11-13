"""Tests for agent/stores.py: the agent keeps answering when its managed stores are unavailable.

Hermetic: the store checks and the package's memory tools are replaced, so nothing calls a
workspace. These pin the decisions (what is offered, when, and what the model is told); that a real
Session or Memory Store answers needs a deployed agent.
"""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent import stores
from agent.contexts import CONTEXTS, MEMORY_UNAVAILABLE_PROMPT, system_prompt
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

DURABLE = object()  # stands in for the managed Session Store saver


class PreviewOff(Exception):
    """What the managed store APIs raise in a workspace without the preview."""

    error_code = "FEATURE_DISABLED"

    def __init__(self):
        super().__init__("Agent Memory Sessions is not enabled")


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Every test starts unchecked, with both stores configured and a clock it controls."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(stores, "_status", stores.Status())
    monkeypatch.setattr(stores, "_fallback_saver", InMemorySaver())
    monkeypatch.setattr(stores, "_now", lambda: clock.now)
    monkeypatch.setattr(stores, "checkpointer", lambda: DURABLE)
    monkeypatch.setenv("AGENT_SESSION_STORE", "sessions")
    monkeypatch.setenv("AGENT_MEMORY_STORE", "memory")
    return clock


def stub_probes(monkeypatch, *, session=None, memory=None):
    """Replace the two checks; each raises what it is given, or passes. Returns the call log."""
    calls = []

    def probe(kind, failure):
        def run(name):
            calls.append((kind, name))
            if failure is not None:
                raise failure

        return run

    monkeypatch.setattr(stores, "_probe_session", probe("session", session))
    monkeypatch.setattr(stores, "_probe_memory", probe("memory", memory))
    return calls


def fake_memory_tools(monkeypatch, *, failure=None):
    """Stand-ins for the package's tools. Returns the actors they were built for."""
    built = []

    def build(actor):
        built.append(actor)

        @tool
        def remember(fact: str, topic: str) -> str:
            """Persist a durable fact about the user."""
            if failure is not None:
                raise failure
            return f"Remembered {fact} for {actor}."

        return [remember]

    monkeypatch.setattr(stores, "memory_tools", build)
    return built


# --- Errors ------------------------------------------------------------------------------------


def test_the_preview_gate_is_recognised_by_code_or_by_message():
    assert stores.is_preview_error(PreviewOff())
    assert stores.is_preview_error(RuntimeError("API returned FEATURE_DISABLED for this workspace"))
    assert not stores.is_preview_error(ValueError("boom"))


def test_an_error_code_is_found_through_the_chain_it_was_raised_from():
    try:
        try:
            raise PreviewOff()
        except PreviewOff as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert stores.error_code(outer) == "FEATURE_DISABLED"
        assert stores.is_preview_error(outer)


def test_a_reason_names_the_preview_when_it_is_the_cause():
    assert "preview is not enabled" in stores.describe(PreviewOff())
    assert stores.describe(ValueError("disk full")) == "ValueError: disk full"


# --- Checking ----------------------------------------------------------------------------------


async def test_working_stores_are_used(monkeypatch):
    calls = stub_probes(monkeypatch)
    status = await stores.refresh()

    assert status.session and status.memory and not status.degraded
    assert calls == [("session", "sessions"), ("memory", "memory")]
    assert stores.session_saver() is DURABLE


async def test_working_stores_are_not_checked_again(monkeypatch, clean_state):
    calls = stub_probes(monkeypatch)
    await stores.refresh()
    clean_state.now += 3600
    await stores.refresh()

    assert len(calls) == 2


async def test_without_the_preview_the_agent_runs_on_process_memory(monkeypatch):
    stub_probes(monkeypatch, session=PreviewOff(), memory=PreviewOff())
    built = fake_memory_tools(monkeypatch)
    status = await stores.refresh()

    assert status.degraded and not status.session and not status.memory
    assert "preview is not enabled" in status.session_reason
    assert "preview is not enabled" in status.memory_reason
    saver = stores.session_saver()
    assert isinstance(saver, InMemorySaver) and saver is not DURABLE
    assert saver is stores.session_saver()  # one per process, so a conversation keeps its history
    assert stores.memory_tools_for("alice") == []
    assert built == []  # the package's tools are never built when memory is off


async def test_one_store_failing_does_not_take_the_other_down(monkeypatch):
    stub_probes(monkeypatch, memory=PreviewOff())
    fake_memory_tools(monkeypatch)
    status = await stores.refresh()

    assert status.session and not status.memory
    assert stores.session_saver() is DURABLE
    assert stores.memory_tools_for("alice") == []


async def test_a_store_that_fails_for_any_other_reason_is_unavailable_too(monkeypatch):
    stub_probes(monkeypatch, session=RuntimeError("session store sessions does not exist"))
    status = await stores.refresh()

    assert not status.session and "does not exist" in status.session_reason
    assert stores.session_saver() is stores._fallback_saver


async def test_stores_that_are_not_configured_are_not_an_error(monkeypatch):
    monkeypatch.delenv("AGENT_SESSION_STORE")
    monkeypatch.delenv("AGENT_MEMORY_STORE")
    calls = stub_probes(monkeypatch)
    status = await stores.refresh()

    assert calls == []
    assert not status.degraded and not status.session and not status.memory
    assert stores.session_saver() is DURABLE  # the package's own in-process default
    assert stores.memory_tools_for("alice") == []


def test_before_the_first_check_the_managed_saver_is_used():
    assert stores.session_saver() is DURABLE


async def test_a_failed_store_is_checked_again_after_a_minute_and_recovers(monkeypatch, clean_state, caplog):
    calls = stub_probes(monkeypatch, session=PreviewOff(), memory=PreviewOff())
    fake_memory_tools(monkeypatch)
    await stores.refresh()
    assert len(calls) == 2

    clean_state.now += stores.RECHECK_SECONDS - 1
    await stores.refresh()
    assert len(calls) == 2  # too soon

    calls = stub_probes(monkeypatch)  # an admin has enabled the preview
    clean_state.now += 2
    with caplog.at_level("INFO", logger=stores.logger.name):
        status = await stores.refresh()

    assert status.session and status.memory and not status.degraded
    assert stores.session_saver() is DURABLE
    assert [t.name for t in stores.memory_tools_for("alice")] == ["remember"]
    assert "available again" in caplog.text


async def test_the_reason_is_logged_once_not_on_every_check(monkeypatch, clean_state, caplog):
    stub_probes(monkeypatch, session=PreviewOff())
    with caplog.at_level("WARNING", logger=stores.logger.name):
        await stores.refresh()
        clean_state.now += 120
        await stores.refresh()

    assert caplog.text.count("Session Store unavailable") == 1


async def test_a_check_that_hangs_is_treated_as_unavailable(monkeypatch):
    release = threading.Event()

    def hangs(name):
        release.wait(5)

    monkeypatch.setattr(stores, "_probe_session", hangs)
    monkeypatch.setattr(stores, "_probe_memory", lambda name: None)
    monkeypatch.setattr(stores, "CHECK_TIMEOUT_SECONDS", 0.05)
    status = await stores.refresh()
    release.set()  # let the thread finish inside this test, not after it

    assert not status.session and "no answer" in status.session_reason
    assert stores.session_saver() is stores._fallback_saver


# --- Memory tools ------------------------------------------------------------------------------


async def test_memory_tools_are_built_for_the_actor_asked_for(monkeypatch):
    stub_probes(monkeypatch)
    built = fake_memory_tools(monkeypatch)
    await stores.refresh()

    [remember] = stores.memory_tools_for("alice")
    assert built == ["alice"]
    assert remember.invoke({"fact": "likes email", "topic": "preferences"}) == "Remembered likes email for alice."
    assert remember.description == "Persist a durable fact about the user."
    assert set(remember.args) == {"fact", "topic"}


async def test_a_memory_tool_that_fails_answers_instead_of_raising(monkeypatch):
    stub_probes(monkeypatch)
    fake_memory_tools(monkeypatch, failure=ValueError("store timed out"))
    await stores.refresh()

    [remember] = stores.memory_tools_for("alice")
    reply = remember.invoke({"fact": "x", "topic": "y"})

    assert reply == stores.MEMORY_TOOL_UNAVAILABLE
    assert stores.status().memory  # an ordinary failure does not switch memory off


async def test_a_memory_tool_hitting_the_preview_gate_switches_memory_off(monkeypatch, clean_state):
    stub_probes(monkeypatch)
    fake_memory_tools(monkeypatch, failure=PreviewOff())
    await stores.refresh()

    [remember] = stores.memory_tools_for("alice")
    assert remember.invoke({"fact": "x", "topic": "y"}) == stores.MEMORY_TOOL_UNAVAILABLE

    assert not stores.status().memory and "preview" in stores.status().memory_reason
    assert stores.memory_tools_for("alice") == []
    # and it is looked at again in a minute, like any store that failed
    stub_probes(monkeypatch)
    clean_state.now += stores.RECHECK_SECONDS + 1
    assert (await stores.refresh()).memory


# --- What the model is told, and what the graph is built from ---------------------------------


def test_the_prompt_says_so_only_when_memory_is_off():
    context = CONTEXTS["customer-intelligence"]
    assert MEMORY_UNAVAILABLE_PROMPT in system_prompt(context, memory=False)
    assert MEMORY_UNAVAILABLE_PROMPT not in system_prompt(context)
    assert MEMORY_UNAVAILABLE_PROMPT not in system_prompt(context, memory=True)


@pytest.fixture
def graph_inputs(monkeypatch):
    """Replace what building the graph would call out for, and capture what it is built from."""
    import agent.agent as agent_module

    built = {}
    monkeypatch.setattr(agent_module, "mcp_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent_module, "_app_workspace_client", lambda: object())
    monkeypatch.setattr(agent_module, "_RoutedChatDatabricks", lambda **kwargs: object())
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: built.update(kwargs) or kwargs)
    return agent_module, built


async def test_the_graph_is_built_without_memory_when_the_stores_are_off(monkeypatch, graph_inputs):
    agent_module, built = graph_inputs
    stub_probes(monkeypatch, session=PreviewOff(), memory=PreviewOff())
    fake_memory_tools(monkeypatch)

    await agent_module.create_agent_graph("alice", context="customer-intelligence")

    assert built["checkpointer"] is stores._fallback_saver
    assert "remember" not in {t.name for t in built["tools"]}
    assert MEMORY_UNAVAILABLE_PROMPT in built["system_prompt"]


async def test_the_graph_is_built_with_memory_when_the_stores_work(monkeypatch, graph_inputs):
    agent_module, built = graph_inputs
    stub_probes(monkeypatch)
    fake_memory_tools(monkeypatch)

    await agent_module.create_agent_graph("alice", context="customer-intelligence")

    assert built["checkpointer"] is DURABLE
    assert "remember" in {t.name for t in built["tools"]}
    assert MEMORY_UNAVAILABLE_PROMPT not in built["system_prompt"]
