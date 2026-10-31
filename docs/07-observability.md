# 7. Observability (Phase 7b, stages 1–2)

Goal: be able to debug an agent run — see every stage, every tool call, every LLM
call, how long each took, and group runs by login session and user.

## Two records, on purpose

| | What | Where | Use it for |
|---|---|---|---|
| **FR-19 event log** | `tool_call`, `llm_call`, `step` events with `stage`, `duration_ms`, args/results, prompt/output, token usage | Postgres `interaction_events` | The durable record. Survives MLflow being wiped. Joins on `run_id`. |
| **MLflow trace** | One trace per run: `discovery` → `LangGraph` → each node → each LLM / tool span | MLflow server, `http://localhost:5000` | Looking at a run. Tree view, inputs/outputs per span. |

MLflow is the inspection UI; Postgres is the source of truth. Don't rely on MLflow alone.

## How it is wired
- `observability/recorder.py` — a LangChain callback handler (`TraceRecorder`) attached once
  at the top of the graph. LangChain propagates it into the Retrieval agent's tool loop and
  every `run_structured` call, so agent code has no logging in it. Each call is written
  once, when it finishes. Payloads over 20k chars are stored as a marked preview.
- `current_stage` (a ContextVar, set at the top of each node) is how an LLM/tool event
  knows which stage made it.
- `observability/tracing.py` — `mlflow.langchain.autolog()` + `root_span()`. The root span
  gives each run one trace and tags it: `session_id` (from a new `sid` claim in the JWT),
  `user` (identity id), tag `run_id`.
- `stream_discovery` now runs the graph in its own task and passes chunks through a queue,
  because an MLflow span can't stay open across an async generator's `yield`s.
- `step done` events now carry `duration_ms`.
- MLflow off = leave `MLFLOW_TRACKING_URI` empty; the DB log still works.

## Running it
```
docker compose up -d            # adds the mlflow service (first start pip-installs; ~1 min)
# existing Postgres volume only, once:
docker exec orchestra-postgres psql -U orchestra -c "CREATE DATABASE mlflow"
# backend/.env: MLFLOW_TRACKING_URI=http://localhost:5000
```
Open `localhost:5000` → experiment `orchestra` → Traces. Filter by `tags.run_id = '<id>'`
(the id is in the result event and in History URLs).

Everything for a run, from SQL:
```sql
select event_type, payload->>'stage', payload->>'tool', payload->>'duration_ms'
from interaction_events where run_id = '<id>' order by created_at;
```

## Verified / not
✅ With real LangChain model/tool objects and scripted responses (no real LLM), through the
real streaming route: events recorded with stage + duration; MLflow trace has root +
nodes + LLM + tool spans, session/user metadata and `run_id` tag.
❌ Not yet seen with the **real** retrieval agent and Ollama — the first real run is the
true test. Token usage in `llm_call` depends on the model reporting it.

## Decisions
- **MLflow over Phoenix/Langfuse:** self-hosted, OTel-compatible, Postgres + artifact-store
  architecture that scales, and it has the eval tooling needed later. Trade-off: more
  infrastructure than one user strictly needs.
- **Separate DB event log:** keeps FR-19 independent of any tracing vendor.
- **Not done yet:** Prometheus/Grafana metrics and alerts, an in-app trace view, eval set.
