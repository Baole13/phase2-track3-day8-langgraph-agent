"""Report generation helper.

TODO(student): implement report rendering using MetricsReport data
and the template in reports/lab_report_template.md.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from .metrics import MetricsReport


def render_report(metrics: MetricsReport) -> str:
    """Render a complete lab report from metrics data.

    TODO(student): Generate a report that includes:
    1. Metrics summary table (total scenarios, success rate, retries, interrupts)
    2. Per-scenario results table
    3. Architecture explanation (your graph design, state schema, reducers)
    4. Failure analysis (at least two failure modes you considered)
    5. Improvement plan

    Use reports/lab_report_template.md as your guide.

    Return: formatted markdown string
    """
    scenario_rows = "\n".join(
        (
            f"| {item.scenario_id} | {item.expected_route} | {item.actual_route or '-'} | "
            f"{'Yes' if item.success else 'No'} | {item.retry_count} | {item.interrupt_count} |"
        )
        for item in metrics.scenario_metrics
    )

    return dedent(
        f"""\
        # Day 08 Lab Report

        ## 1. Team / student

        - Name:
        - Repo/commit:
        - Date:

        ## 2. Architecture

        The workflow uses a LangGraph `StateGraph` with the path
        `START -> intake -> classify` and then conditional routing into
        `answer`, `tool`, `clarify`, `risky_action`, or `retry`.
        All branches terminate through `finalize -> END`, including retry
        exhaustion via `dead_letter`.

        Classification and final response generation use a real LLM through
        `get_llm()`. Risky requests go through `risky_action -> approval`
        before any tool execution. Error routes use
        `retry -> tool -> evaluate` with a bounded loop controlled by
        `attempt < max_attempts`.

        ## 3. State schema

        | Field | Reducer | Why |
        |---|---|---|
        | messages | append | audit and trace node progress |
        | tool_results | append | retain tool history across retries |
        | errors | append | preserve retry and failure evidence |
        | events | append | grading and metrics rely on node audit trail |
        | route | overwrite | current workflow decision |
        | evaluation_result | overwrite | retry gate after evaluation |
        | pending_question | overwrite | clarification output |
        | proposed_action | overwrite | approval payload for risky actions |
        | approval | overwrite | latest approval decision |

        ## 4. Scenario results

        | Scenario | Expected route | Actual route | Success | Retries | Interrupts |
        |---|---|---|---:|---:|---:|
        {scenario_rows}

        ### Metrics summary

        | Metric | Value |
        |---|---:|
        | Total scenarios | {metrics.total_scenarios} |
        | Success rate | {metrics.success_rate:.2%} |
        | Average nodes visited | {metrics.avg_nodes_visited:.2f} |
        | Total retries | {metrics.total_retries} |
        | Total interrupts | {metrics.total_interrupts} |
        | Resume success | {"Yes" if metrics.resume_success else "No"} |

        ## 5. Failure analysis

        1. Retry or tool failure: transient tool failures are converted into
        `evaluation_result="needs_retry"`, routed through `retry`, and stopped
        safely by `max_attempts`.
        2. Risky action without approval: destructive or customer-impacting
        requests are isolated into a separate approval path before tool
        execution, preventing side effects from bypassing review.

        ## 6. Persistence / recovery evidence

        The workflow supports LangGraph checkpointers keyed by `thread_id`.
        The SQLite option uses `SqliteSaver` with WAL mode so scenario runs
        can be replayed or resumed from a durable checkpoint database.

        ## 7. Extension work

        Implemented extension: SQLite persistence via
        `build_checkpointer("sqlite", database_url=...)`.
        This complements the base in-memory saver and creates a concrete
        recovery path for report/demo evidence.

        ## 8. Improvement plan

        If given one more day, the next production upgrade would be a real
        human approval loop using `LANGGRAPH_INTERRUPT=true`, plus richer
        evaluation with LLM-as-judge and checkpoint history replay
        screenshots.
        """
    ).strip()


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    """Write the rendered report to a file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(metrics), encoding="utf-8")
