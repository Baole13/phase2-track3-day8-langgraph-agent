"""Node functions for the LangGraph workflow.

Each function receives AgentState and returns a partial state update dict.
Do NOT mutate input state — return new values only.

LLM REQUIREMENT:
- classify_node MUST use a real LLM call (structured output for intent classification)
- answer_node MUST use a real LLM call (grounded response generation)
- evaluate_node SHOULD use LLM-as-judge (bonus points; heuristic acceptable for base score)
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from .llm import get_llm
from .state import AgentState, ApprovalDecision, make_event


class ClassificationOutput(BaseModel):
    """Structured route selection from the classifier model."""

    route: Literal["simple", "tool", "missing_info", "risky", "error"] = Field(
        description="Best route for the support request."
    )
    rationale: str = Field(description="Short explanation for the chosen route.")


# ─── EXAMPLE: working node (provided for reference) ──────────────────
def intake_node(state: AgentState) -> dict:
    """Normalize raw query. This node is provided as a working example."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


# ─── TODO(student): implement ALL nodes below ────────────────────────


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using an LLM.

    *** MUST use a real LLM call — keyword-only heuristics will lose points. ***

    Use .with_structured_output() or equivalent to get reliable enum classification.
    The LLM should classify into one of: simple, tool, missing_info, risky, error.

    Hints:
    - See llm.py for the get_llm() helper
    - Use Pydantic model or TypedDict with .with_structured_output()
    - Set risk_level to "high" for risky routes, "low" otherwise
    - Priority guide: risky > tool > missing_info > error > simple

    Return: {"route": str, "risk_level": str, "events": [make_event(...)]}
    """
    query = state.get("query", "").strip()
    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(ClassificationOutput)
    prompt = (
        "You are a support-ticket router for a LangGraph workflow.\n"
        "Classify the user request into exactly one route.\n"
        "Available routes: simple, tool, missing_info, risky, error.\n"
        "Priority order when multiple categories could apply: "
        "risky > tool > missing_info > error > simple.\n"
        "Definitions:\n"
        "- risky: requests with side effects like refunding, deleting, "
        "cancelling, emailing, changing accounts\n"
        "- tool: requests requiring data lookup or system retrieval\n"
        "- missing_info: request is too vague or lacks identifiers/context to act\n"
        "- error: request reports failures, crashes, timeouts, or unrecoverable system issues\n"
        "- simple: general guidance answerable without a tool or side effect\n\n"
        f"User query: {query}"
    )
    result = structured_llm.invoke(prompt)
    route = result.route
    risk_level = "high" if route == "risky" else "low"
    return {
        "route": route,
        "risk_level": risk_level,
        "messages": [f"classify:{route}"],
        "events": [
            make_event(
                "classify",
                "completed",
                f"classified as {route}",
                rationale=result.rationale,
                risk_level=risk_level,
            )
        ],
    }


def tool_node(state: AgentState) -> dict:
    """Execute a mock tool call.

    Simulate transient failures for error-route scenarios to test retry loops.

    Requirements:
    - Read current attempt count from state
    - If route is "error" and attempt < 2: return error result (string containing "ERROR")
    - Otherwise: return a mock success result string
    - Append result to tool_results list

    Return: {"tool_results": [result_string], "events": [make_event(...)]}
    """
    route = state.get("route", "")
    attempt = int(state.get("attempt", 0))
    query = state.get("query", "").strip()

    if route == "error" and attempt < 2:
        result = (
            f"ERROR: transient backend failure while handling '{query}' "
            f"on attempt {attempt + 1}"
        )
    elif route == "tool":
        result = (
            f"Tool lookup succeeded for query '{query}'. "
            "Order status is in progress and the latest system record is available."
        )
    elif route == "risky":
        proposed_action = state.get("proposed_action") or "requested customer-impacting action"
        result = (
            f"Tool execution approved and completed for risky action: {proposed_action}. "
            "Confirmation has been prepared for the support record."
        )
    else:
        result = f"Tool execution succeeded for query '{query}'."

    return {
        "tool_results": [result],
        "events": [
            make_event(
                "tool",
                "completed",
                "tool executed",
                route=route,
                attempt=attempt,
                result=result,
            )
        ],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the retry-loop gate.

    Check whether the latest tool result is satisfactory or needs retry.

    SHOULD use LLM-as-judge for bonus points. Heuristic (e.g., check for "ERROR" substring)
    is acceptable for base score.

    Requirements:
    - Read the latest entry from tool_results
    - Set evaluation_result to "needs_retry" or "success"
    - This field drives route_after_evaluate conditional edge

    Note: You may need to add 'evaluation_result' to AgentState if not present.

    Return: {"evaluation_result": str, "events": [make_event(...)]}
    """
    latest_result = (state.get("tool_results") or [""])[-1]
    evaluation_result = "needs_retry" if "ERROR" in latest_result else "success"
    return {
        "evaluation_result": evaluation_result,
        "events": [
            make_event(
                "evaluate",
                "completed",
                "tool result evaluated",
                evaluation_result=evaluation_result,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Generate a final response using an LLM.

    *** MUST use a real LLM call — hardcoded strings will lose points. ***

    The LLM should generate a helpful response grounded in available context:
    - tool_results (if any)
    - approval decision (if risky route)
    - original query

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    query = state.get("query", "").strip()
    route = state.get("route", "")
    tool_results = state.get("tool_results") or []
    latest_tool_result = tool_results[-1] if tool_results else "No tool result available."
    approval = state.get("approval")
    proposed_action = state.get("proposed_action") or "None"

    llm = get_llm(temperature=0.2)
    prompt = (
        "You are a careful support agent.\n"
        "Write a concise, helpful final answer grounded only in the provided context.\n"
        "If a risky action was approved, mention that approval and the completed action.\n"
        "Do not invent tool details that are not present.\n\n"
        f"Route: {route}\n"
        f"Original query: {query}\n"
        f"Latest tool result: {latest_tool_result}\n"
        f"Proposed action: {proposed_action}\n"
        f"Approval: {approval}\n"
    )
    response = llm.invoke(prompt)
    final_answer = getattr(response, "content", str(response))
    return {
        "final_answer": final_answer,
        "events": [
            make_event(
                "answer",
                "completed",
                "final answer generated",
                route=route,
            )
        ],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Generate a specific clarification question based on the vague/incomplete query.

    Note: You may need to add 'pending_question' to AgentState if not present.

    Return: {"pending_question": str, "final_answer": str, "events": [make_event(...)]}
    """
    query = state.get("query", "").strip()
    pending_question = (
        f"I can help with '{query}', but I need a bit more detail first. "
        "What exact issue, account, or order should I work on?"
    )
    return {
        "pending_question": pending_question,
        "final_answer": pending_question,
        "events": [
            make_event("clarify", "completed", "clarification requested", query=query)
        ],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for human approval.

    Describe the proposed action and why it requires approval.

    Note: You may need to add 'proposed_action' to AgentState if not present.

    Return: {"proposed_action": str, "events": [make_event(...)]}
    """
    query = state.get("query", "").strip()
    proposed_action = (
        f"Proposed risky action based on user request: {query}. "
        "This may change customer data, issue a refund, or trigger outbound communication."
    )
    return {
        "proposed_action": proposed_action,
        "events": [
            make_event(
                "risky_action",
                "completed",
                "risky action prepared for approval",
                proposed_action=proposed_action,
            )
        ],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step.

    Default behavior: mock approval (approved=True) so tests and CI run offline.
    Extension: if env LANGGRAPH_INTERRUPT=true, use langgraph.types.interrupt() for real HITL.

    Return: {"approval": {"approved": bool, "reviewer": str, "comment": str},
             "events": [make_event(...)]}
    """
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        payload = interrupt(
            {
                "query": state.get("query"),
                "proposed_action": state.get("proposed_action"),
            }
        )
        decision = ApprovalDecision.model_validate(payload)
    else:
        decision = ApprovalDecision(
            approved=True,
            reviewer="mock-reviewer",
            comment="Auto-approved for lab execution.",
        )

    return {
        "approval": decision.model_dump(),
        "events": [
            make_event(
                "approval",
                "completed",
                "approval decision recorded",
                approved=decision.approved,
                reviewer=decision.reviewer,
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt.

    Increment the attempt counter and log the transient failure.

    Requirements:
    - Read current attempt from state, increment by 1
    - Add an error message to errors list
    - Return updated attempt count

    Return: {"attempt": int, "errors": [str], "events": [make_event(...)]}
    """
    next_attempt = int(state.get("attempt", 0)) + 1
    error_message = f"Retry attempt {next_attempt} after tool evaluation requested another try."
    return {
        "attempt": next_attempt,
        "errors": [error_message],
        "events": [
            make_event(
                "retry",
                "completed",
                "retry attempt recorded",
                attempt=next_attempt,
                max_attempts=state.get("max_attempts", 3),
            )
        ],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Handle unresolvable failures after max retries exceeded.

    This is the third layer: retry → fallback → dead letter.
    Log the failure and set a final_answer explaining that the request could not be completed.

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    final_answer = (
        "I could not complete this request after the allowed retry attempts. "
        "Please escalate it for manual investigation."
    )
    return {
        "final_answer": final_answer,
        "events": [
            make_event(
                "dead_letter",
                "completed",
                "workflow moved to dead letter after retry exhaustion",
                attempts=state.get("attempt", 0),
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Emit a final audit event. All routes must pass through here before END.

    Return: {"events": [make_event("finalize", "completed", "workflow finished")]}
    """
    return {
        "events": [make_event("finalize", "completed", "workflow finished")]
    }
