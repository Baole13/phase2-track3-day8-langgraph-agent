# Day 08 Lab - LangGraph Agentic Orchestration

Production-style support-ticket workflow built with LangGraph. The project now includes:

- Typed graph state with append-only audit fields
- LLM-based intent classification and grounded answer generation
- Conditional routing for `simple`, `tool`, `missing_info`, `risky`, and `error`
- Bounded retry loop with dead-letter fallback
- Mock human approval for risky actions
- SQLite checkpointer support
- Metrics and report generation

## Architecture

Target graph:

```text
START -> intake -> classify -> route

simple       -> answer -> finalize -> END
tool         -> tool -> evaluate -> answer -> finalize -> END
tool retry   -> tool -> evaluate -> retry -> tool -> ...
missing_info -> clarify -> finalize -> END
risky        -> risky_action -> approval -> tool -> evaluate -> answer -> finalize -> END
error        -> retry -> tool -> evaluate -> retry -> ...
max retry    -> retry -> dead_letter -> finalize -> END
```

Core implementation lives in:

- `src/langgraph_agent_lab/state.py`: state schema, events, scenarios
- `src/langgraph_agent_lab/nodes.py`: all workflow nodes
- `src/langgraph_agent_lab/routing.py`: conditional edge decisions
- `src/langgraph_agent_lab/graph.py`: graph construction and compilation
- `src/langgraph_agent_lab/persistence.py`: memory and SQLite checkpointers
- `src/langgraph_agent_lab/report.py`: markdown report rendering

## State Design

Overwrite fields:

- `route`
- `risk_level`
- `attempt`
- `max_attempts`
- `evaluation_result`
- `final_answer`
- `pending_question`
- `proposed_action`
- `approval`

Append-only fields:

- `messages`
- `tool_results`
- `errors`
- `events`

This split keeps the workflow serializable while preserving enough audit data for grading, retry analysis, and reporting.

## Route Semantics

- `simple`: general support guidance without tool usage
- `tool`: information lookup such as order status
- `missing_info`: vague request that requires clarification
- `risky`: refund, delete, email, or other side-effecting action
- `error`: failure report that should enter the retry loop

Classification uses an LLM with structured output and the priority:

```text
risky > tool > missing_info > error > simple
```

## Setup

### 1. Create environment

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -e ".[dev]"
pip install langchain-google-genai
pip install langgraph-checkpoint-sqlite
```

### 3. Configure `.env`

Copy the sample file:

```powershell
Copy-Item .env.example .env
```

Then update at least:

```env
GEMINI_API_KEY=your_real_key_here
# Optional
# LLM_MODEL=gemini-2.5-flash
# LANGGRAPH_INTERRUPT=true
```

## Run

### Unit tests

```powershell
pytest -q
```

### Lint

```powershell
ruff check src
```

### Run scenarios

```powershell
python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json
```

Or:

```powershell
make run-scenarios
```

### Validate metrics

```powershell
python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json
```

Or:

```powershell
make grade-local
```

## Current Validation Status

Validated locally:

- `pytest -q` passes when LLM-backed smoke tests are skipped because no valid provider key is available
- `ruff check src` passes
- Graph logic was validated with a local fake-LLM smoke harness:
  - `S01_simple` -> `simple`
  - `S02_tool` -> `tool`
  - `S03_missing` -> `missing_info`
  - `S04_risky` -> `risky`
  - `S05_error` -> `error` with retry recovery
  - `S06_delete` -> `risky` with approval observed
  - `S07_dead_letter` -> `error` with dead-letter after retry limit

Not yet validated end-to-end in this environment:

- Real Gemini API calls, because the current environment key returned `API_KEY_INVALID`
- Final `outputs/metrics.json` generated from actual LLM execution

## SQLite Persistence Note

The project is configured to use SQLite in `configs/lab.yaml`.

On this machine, the workspace path contains non-ASCII characters. Some SQLite operations can fail with `disk I/O error` in that case. The implementation handles this by falling back to a temp-directory SQLite file when needed, while preserving the same checkpointer behavior.

## Example Workflow Behavior

### Risky request

Input:

```text
Refund this customer and send confirmation email
```

Expected path:

```text
intake -> classify(risky) -> risky_action -> approval -> tool -> evaluate -> answer -> finalize
```

### Error request

Input:

```text
Timeout failure while processing request
```

Expected path:

```text
intake -> classify(error) -> retry -> tool -> evaluate -> retry ...
```

If retries exceed `max_attempts`, the workflow moves to `dead_letter`.

## Deliverables

- `outputs/metrics.json`
- `reports/lab_report.md`
- Passing tests
- Explanation of one successful route and one failure route during demo

## Next Step Before Submission

Set a valid `GEMINI_API_KEY`, then run:

```powershell
pytest tests/test_graph_smoke.py -q
make run-scenarios
make grade-local
```

After that, update `reports/lab_report.md` with the final metrics if they differ from the current implementation notes.
