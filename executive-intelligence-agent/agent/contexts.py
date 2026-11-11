"""App contexts: the instructions and tools the agent gets in each part of the client app.

One deployed agent serves every section of the Executive Intelligence app. The client sends the
section the user is in as ``input.context`` on each turn, and ``create_agent_graph`` (which runs per
turn) adds that context's prompt section to ``BASE_PROMPT`` and offers only the tools whose names
match its patterns. Memory tools are always offered, so what the agent learns about a user carries
across contexts.

A context narrows what the model is offered; it is not an access-control boundary. Every tool still
runs with the identity it is bound to, so Unity Catalog grants on that identity decide what data is
reachable. Add a context here, then send its id from the client.
"""

import logging
from dataclasses import dataclass
from fnmatch import fnmatchcase

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
                "parentheses; answer for that slice. Explain what would move each metric and which "
                "customers, regions, or segments to look at first.\n"
                "The exec_data tools query the same data as the dashboard through a Genie space. "
                "Use them for any figure you state: pass one focused question, including the period "
                "and filters, to exec_data_ask, and read rows with exec_data_query_result. Ask "
                "follow-ups in the same conversation_id. Quote numbers only from their results, and "
                "say which period they cover."
            ),
            # exec_data_* are the Genie space over the contract views (data/genie.py).
            tools=("get_current_time", "exec_*"),
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
                "revenue, and what to do, in that order.\n"
                "The ci_data tools query the same data as the briefing through a Genie space. Use "
                "them for any figure you state: pass one focused question, including the account "
                "and period, to ci_data_ask, and read rows with ci_data_query_result. Ask follow-ups "
                "in the same conversation_id. Quote numbers only from their results. When you cite "
                "market or account intelligence, name its source and date. The briefing's sentences "
                "come from templates over this data, so check a claim against the data before "
                "repeating it."
            ),
            # ci_data_* are the Genie space over the Customer Intelligence views (data/genie/customer.json).
            tools=("get_current_time", "ci_*"),
        ),
        AppContext(
            id="market-intelligence",
            label="Market Intelligence",
            prompt=(
                "The user is in Market Intelligence. Focus on competitors, market share, pricing, and "
                "industry news. Combine structured market data with supporting documents, and cite "
                "the source of each claim."
            ),
            # Placeholders until the market-intelligence MCP servers and Genie spaces are bound;
            # list their tool names (or prefixes) here.
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


def system_prompt(context: AppContext) -> str:
    return f"{BASE_PROMPT}\n\nCurrent app context: {context.label}.\n{context.prompt}"


def select_tools(context: AppContext, tools: list[BaseTool]) -> list[BaseTool]:
    return [tool for tool in tools if context.allows(tool.name)]
