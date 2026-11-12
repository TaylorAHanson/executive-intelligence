"""App contexts: the instructions and tools the agent gets in each part of the client app.

One deployed agent serves every section of the Executive Intelligence app. The client sends the
section the user is in as ``input.context`` on each turn, and ``create_agent_graph`` (which runs per
turn) adds that context's prompt section to ``BASE_PROMPT`` and offers only the tools whose names
match its patterns. Memory tools are always offered, so what the agent learns about a user carries
across contexts.

Admins change a context's prompt and tools in the client's Settings page. The client stores them in
Unity Catalog and sends the current context's settings as ``input.settings`` on each turn; this
module merges them over the defaults below. Genie spaces come only from settings, because their ids
differ per workspace. The client is the only intended caller, but anyone with CAN USE on the agent
app could send their own settings. That gains them nothing: data tools run as the caller.

A context narrows what the model is offered; it is not an access-control boundary. Data tools run
as the signed-in user, so that user's Unity Catalog grants decide what is reachable. Add a context
here, then send its id from the client.
"""

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

BASE_PROMPT = """You are the Executive Intelligence agent, an analyst for a company's leadership team.
Answer with the evidence you used, and say plainly when the available tools cannot answer a question.
Prefer short answers that lead with the conclusion. Use your memory tools to recall the user's
preferences and prior findings, and to save durable facts they ask you to remember."""


@dataclass(frozen=True)
class AppContext:
    id: str
    label: str
    prompt: str
    #: fnmatch patterns over tool names as the model sees them. ("*",) offers every tool.
    tools: tuple[str, ...] = ("*",)

    def allows(self, tool_name: str) -> bool:
        return any(fnmatchcase(tool_name, pattern) for pattern in self.tools)


CONTEXTS: dict[str, AppContext] = {
    context.id: context
    for context in (
        AppContext(
            id="general",
            label="General",
            prompt="The user is on the home view. Help with any executive question across sources.",
        ),
        AppContext(
            id="executive",
            label="Executive Insights",
            prompt=(
                "The user is on the Executive Insights dashboard: revenue, OTIF (the share of "
                "shipments on time and in full), and design-win conversion (won / decided), each "
                "against the prior period of equal length, plus a top-customers table that flags "
                "customers at risk. Questions may end with the dashboard's active filters in "
                "parentheses; answer for that slice, and say which period each figure covers. "
                "Explain what would move each metric and which customers, regions, or segments to "
                "look at first."
            ),
            tools=("get_current_time",),
        ),
        AppContext(
            id="customer-intelligence",
            label="Customer Intelligence",
            prompt=(
                "The user is in Customer Intelligence, a briefing for sales and finance leadership on "
                "the top 10 accounts in four chapters: what they are focused on, how we are doing "
                "with them (revenue against plan, share of their new devices, lead-to-win "
                "conversion), where next quarter lands (commit and best case against plan, open "
                "deals, contract renewals), and what to do. A question may start with the account "
                "it is about. Answer as cause and effect: what changed, why, what it means for "
                "revenue, and what to do, in that order. When you cite market or account "
                "intelligence, name its source and date. The briefing's sentences come from "
                "templates over the data, so check a claim against the data before repeating it."
            ),
            tools=("get_current_time",),
        ),
        AppContext(
            id="market-intelligence",
            label="Market Intelligence",
            prompt=(
                "The user is in Market Intelligence. Focus on competitors, market share, pricing, and "
                "industry news. Combine structured market data with supporting documents, and cite "
                "the source of each claim."
            ),
            # market_* and mi_* are placeholders for market-intelligence MCP servers.
            tools=("get_current_time", "send_message", "market_*", "mi_*"),
        ),
        AppContext(
            id="signals",
            label="Signal Review",
            prompt=(
                "The user is reviewing signals the scheduled signal-finding loop surfaced. Explain why "
                "each signal fired, what evidence supports it, and what would confirm or dismiss it."
            ),
            tools=("get_current_time", "signal_*"),
        ),
    )
}

DEFAULT_CONTEXT = "general"

#: Genie tools are named <name>_ask, <name>_poll and <name>_query_result.
GENIE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
GENIE_SPACE_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_GENIE_SPACES = 10
MAX_PROMPT_CHARS = 8000


@dataclass(frozen=True)
class GenieSpace:
    name: str
    space_id: str
    title: str = ""
    description: str = ""


@dataclass(frozen=True)
class ContextSettings:
    """A context's admin settings. None means "use the default" for that part."""

    prompt: str | None = None
    #: Exact names of local tools to offer, replacing the context's patterns for local tools.
    builtin_tools: tuple[str, ...] | None = None
    genie_spaces: tuple[GenieSpace, ...] = ()


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def parse_settings(raw: Any) -> ContextSettings:
    """``input.settings`` as sent by the client, dropping anything malformed rather than failing.

    A bad entry is logged and skipped, so one mistyped space id does not take a context offline.
    """
    if not isinstance(raw, Mapping):
        if raw is not None:
            logger.warning("Ignoring settings that are not an object.")
        return ContextSettings()

    prompt = _text(raw.get("prompt"), MAX_PROMPT_CHARS) or None

    tools = raw.get("tools") if isinstance(raw.get("tools"), Mapping) else {}
    builtin = tools.get("builtin")
    builtin_tools = (
        tuple(name for name in builtin if isinstance(name, str)) if isinstance(builtin, list) else None
    )

    spaces: list[GenieSpace] = []
    names: set[str] = set()
    for entry in tools.get("genie") or []:
        if not isinstance(entry, Mapping):
            continue
        name, space_id = entry.get("name"), entry.get("space_id")
        if not (isinstance(name, str) and GENIE_NAME_RE.match(name)):
            logger.warning("Ignoring a Genie space with an invalid tool name: %r", name)
            continue
        if not (isinstance(space_id, str) and GENIE_SPACE_RE.match(space_id)):
            logger.warning("Ignoring Genie space %r: invalid space id.", name)
            continue
        if name in names or len(spaces) >= MAX_GENIE_SPACES:
            logger.warning("Ignoring Genie space %r: duplicate name or too many spaces.", name)
            continue
        names.add(name)
        spaces.append(
            GenieSpace(
                name=name,
                space_id=space_id,
                title=_text(entry.get("title"), 200),
                description=_text(entry.get("description"), 500),
            )
        )
    return ContextSettings(prompt=prompt, builtin_tools=builtin_tools, genie_spaces=tuple(spaces))


def resolve_context(context_id: str | None) -> AppContext:
    """The requested context, or the default when it is missing or unknown.

    Unknown ids fall back rather than fail so a client that ships a new section before the agent
    is redeployed still gets answers.
    """
    if context_id and context_id in CONTEXTS:
        return CONTEXTS[context_id]
    if context_id:
        logger.warning("Unknown app context %r; using %r.", context_id, DEFAULT_CONTEXT)
    return CONTEXTS[DEFAULT_CONTEXT]


def _data_tools_section(spaces: Iterable[GenieSpace]) -> str:
    spaces = list(spaces)
    if not spaces:
        return ""
    lines = [
        (
            "Data tools: each Genie space below answers questions over governed data, as the user. "
            "Use them for any figure you state: pass one focused question, including the period, "
            "filters, or account, to <name>_ask, and read rows with <name>_query_result. Ask "
            "follow-ups in the same conversation_id. Quote numbers only from their results."
        )
    ]
    for space in spaces:
        about = " - ".join(part for part in (space.title, space.description) if part)
        lines.append(f"- {space.name}: {about}" if about else f"- {space.name}")
    return "\n".join(lines)


def system_prompt(context: AppContext, settings: ContextSettings | None = None) -> str:
    settings = settings or ContextSettings()
    sections = [
        BASE_PROMPT,
        f"Current app context: {context.label}.\n{settings.prompt or context.prompt}",
        _data_tools_section(settings.genie_spaces),
    ]
    return "\n\n".join(section for section in sections if section)


def select_tools(
    context: AppContext,
    tools: list[BaseTool],
    settings: ContextSettings | None = None,
    *,
    local_names: Iterable[str] = (),
) -> list[BaseTool]:
    """The tools ``context`` offers. Settings' builtin list replaces the patterns for local tools."""
    builtin = settings.builtin_tools if settings else None
    if builtin is None:
        return [tool for tool in tools if context.allows(tool.name)]
    local = set(local_names)
    return [
        tool
        for tool in tools
        if (tool.name in builtin if tool.name in local else context.allows(tool.name))
    ]


def describe_contexts(local_tools: Iterable[BaseTool]) -> dict:
    """Every context's defaults, for the client's Settings page. Holds no credentials or data."""
    local_tools = list(local_tools)
    return {
        "base_prompt": BASE_PROMPT,
        "builtin_tools": [
            {"name": tool.name, "description": (tool.description or "").split("\n")[0]}
            for tool in local_tools
        ],
        "contexts": [
            {
                "id": context.id,
                "label": context.label,
                "prompt": context.prompt,
                "builtin_tools": [t.name for t in local_tools if context.allows(t.name)],
            }
            for context in CONTEXTS.values()
        ],
    }
