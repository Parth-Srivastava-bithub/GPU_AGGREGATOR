# GPU Aggregate — Agent Architecture

## What This System Is

An **autonomous GPU orchestration agent** built on LangGraph that lets an ML engineer describe what they want in plain English and handles the entire workflow: finding the right GPU, collecting required parameters, confirming with the user, and executing the deployment — all through a conversational CLI.

---

## High-Level Architecture

```
User (CLI)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                  LangGraph Agent Graph                  │
│                                                         │
│  intent_parser → dependency_resolver ──────────────┐   │
│                         │                          │   │
│                    [create?]  [read/action?]        │   │
│                         │         │                │   │
│               create_planner  endpoint_selector    │   │
│                    │               │               │   │
│           create_api_resolver  router_executor     │   │
│                    │               │               │   │
│          create_user_clarifier result_extractor    │   │
│            (HITL interrupt)    selection_node      │   │
│                    │           (HITL interrupt)    │   │
│          create_payload_builder state_updater      │   │
│                    │               │               │   │
│          create_validator   ───────┘               │   │
│                    │                               │   │
│             confirmation_gate ◄───────────────────┘   │
│              (HITL interrupt)                          │
│                    │                                   │
│              router_executor                           │
│                    │                                   │
│              goal_reasoner  ←── (skipped for creates)  │
│                    │                                   │
│           response_formatter                           │
└─────────────────────────────────────────────────────────┘
```

---

## Two Distinct Workflows

### Read / Action Flow (e.g. "show me cheapest H100")
```
intent_parser
    → dependency_resolver (compute missing params)
    → endpoint_selector (pick resolver for missing param)
    → router_executor (HTTP call to FastAPI)
    → result_extractor (unbox response, check cardinality)
        → selection_node [HITL if ambiguous] → state_updater → loop back
        → state_updater (single result) → loop back
    → router_executor (execute goal endpoint when all params collected)
    → goal_reasoner (LLM: does raw result answer the goal? filter/rank if not)
    → response_formatter (LLM: write user-facing summary)
```

### Create Flow (e.g. "deploy RTX 4090 on runpod")
```
intent_parser
    → dependency_resolver (detects category=create)
    → create_planner (deterministic: classify each param into auto/user/default)
        ↓ pending_auto          ↓ pending_user    ↓ defaults
    create_api_resolver     create_user_clarifier  (injected at payload build)
    (call API, LLM filter)  [HITL interrupt]
        ↓ loop until all resolved
    create_payload_builder (merge collected + defaults)
    → create_validator (assert all required params present)
    → confirmation_gate [HITL interrupt]
    → router_executor (POST create_pod or create_volume)
    → response_formatter
```

---

## Component Responsibilities

| Component | Type | Role |
|-----------|------|------|
| `intent_parser` | LLM | Parse free-text → `goal_endpoint` + initial `collected_params` |
| `dependency_resolver` | Deterministic | Diff `requires` vs `collected_params` → `missing_params` |
| `endpoint_selector` | Deterministic | Pick the right resolver endpoint for each missing param |
| `router_executor` | Deterministic | Single HTTP dispatch engine used by all paths |
| `result_extractor` | Deterministic | Unbox API response, detect single vs multi result |
| `selection_node` | HITL | Pause for human to pick from numbered list |
| `state_updater` | Deterministic | Merge resolved value into collected_params, loop back |
| `create_planner` | Hybrid | Deterministic param classification + LLM question generation |
| `create_api_resolver` | Hybrid | Deterministic API call + LLM filter for multi-result sets |
| `create_user_clarifier` | HITL | Pause for human answer to a clarification question |
| `create_payload_builder` | Deterministic | Merge collected + well-known defaults |
| `create_validator` | Deterministic | Guard-rail before confirmation |
| `confirmation_gate` | HITL | Pause for explicit yes/no before destructive/costly ops |
| `goal_reasoner` | LLM | Two-phase: evaluate → transform raw data to answer user goal |
| `response_formatter` | LLM | Write user-facing summary in natural language |

---

## HITL (Human-in-the-Loop) Points

Three interrupt points where the graph physically pauses and waits for user input:

1. **`selection_node`** — when a resolver returns multiple candidates (e.g. 2 providers) and the LLM can't auto-narrow
2. **`create_user_clarifier`** — when a required param has no API resolver and no default (currently only `name`)
3. **`confirmation_gate`** — before any `cost_incurring` or `destructive` operation

Implemented via `interrupt_before` in LangGraph with `MemorySaver` checkpointer. Resume is done by injecting a `HumanMessage` and calling `app.invoke(None, config)`.

---

## FastAPI Connector Layer

The connector (`connector.py`) acts as a provider-agnostic HTTP bridge:

```
showdown.py (agent) ──HTTP──► connector.py (FastAPI :8001) ──► RunPod REST API
                                                          └──► Novita REST API
                                                          └──► SQLite (gpu_catalog)
                                                          └──► MongoDB (datacenters)
```

Key endpoints used by the agent:

| Endpoint | Purpose |
|----------|---------|
| `GET /gpu_catalog?provider=X&available_only=true` | API-ready gpu_ids for create workflow |
| `GET /pod_context/{provider}` | All-in-one: GPUs + volumes + defaults |
| `GET /{provider}/user_pods` | Resolve pod_id for start/stop/delete |
| `GET /{provider}/datacenters` | Resolve datacenter_id for create_volume |
| `POST /{provider}/create_pod` | Deploy a new GPU pod |

---

## LangGraph State Schema

```python
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]  # full conversation history
    flow_category: str          # "create" | "action" | "resolver"
    goal_endpoint: str          # which REGISTRY entry to execute
    collected_params: Dict      # params accumulated across the workflow
    missing_params: List[str]   # diff of requires vs collected
    pending_selection: Dict     # candidates waiting for human pick
    create_plan: Dict           # {pending_auto, pending_user, defaults} for create flows
    confirmation_payload: Dict  # final params shown to user at confirmation
    execution_history: List     # append-only log of every HTTP call
    final_result: Any           # the goal endpoint's response
    error_state: str            # propagated to formatter if anything fails
    user_goal: str              # original free-text goal (kept for goal_reasoner)
    reasoning_notes: str        # goal_reasoner's chain-of-thought
```

---

## Data Flow for "deploy RTX 4090 on runpod"

```
User types: "deploy RTX 4090 on runpod"
    │
    ▼ intent_parser (LLM)
    collected = {provider: "runpod"}   ← gpu_id BLOCKED (api_lookup_only)
    goal = create_pod
    │
    ▼ create_planner (deterministic)
    pending_auto = [{param: gpu_id, resolver: get_pod_context, filter_hint: "RTX 4090 on runpod"}]
    pending_user = []   ← name already inferred from context
    defaults = {image_name: "runpod/pytorch:...", gpu_count: 1, container_disk_gb: 20, ...}
    │
    ▼ create_api_resolver
    GET /pod_context/runpod → 29 deployable GPUs
    LLM filter: "RTX 4090 on runpod" → gpu_id = "NVIDIA GeForce RTX 4090"
    │
    ▼ create_payload_builder
    payload = {provider: runpod, name: "...", gpu_id: "NVIDIA GeForce RTX 4090",
               image_name: "runpod/pytorch:...", gpu_count: 1, ...}
    │
    ▼ create_validator ✓
    │
    ▼ confirmation_gate [HITL — user sees full params, types yes/no]
    │
    ▼ router_executor
    POST http://localhost:8001/runpod/create_pod?name=...&gpu_id=NVIDIA+GeForce+RTX+4090&...
    │
    ▼ response_formatter → "Pod deployed successfully..."
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph (StateGraph, MemorySaver checkpointer) |
| LLM | Groq `llama-3.3-70b-versatile` / OpenAI GPT |
| LangChain | ChatGroq / ChatOpenAI, Message types |
| Backend API | FastAPI + Uvicorn |
| GPU data store | SQLite (`gpu_catalog.db`) |
| Datacenter data | MongoDB (`gpu_aggregator.datacenters`) |
| Data ingestion | Playwright (CDP scraping) + GraphQL (RunPod API) |
| Scheduling | APScheduler (catalog refresh every hour) |
| Output | `rich` library for formatted terminal output |
