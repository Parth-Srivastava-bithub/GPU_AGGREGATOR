# GPU Aggregate Agent — Deep Dive

## What Makes This Agent Different

Most demo agents call one tool and return an answer. This agent orchestrates a **multi-step stateful workflow** across real cloud provider APIs with human approval gates, auto-resolution loops, and semantic reasoning over live data. Every design decision has a production rationale.

---

## Core Design Philosophy

### 1. Deterministic Where Possible, LLM Where Necessary

The agent follows a hybrid design principle:

| Decision | Handled by |
|----------|-----------|
| What endpoint to call | LLM (intent_parser) |
| Which params are missing | Pure code (`dependency_resolver`) |
| Which resolver endpoint to call for each param | Pure code (`endpoint_selector`, `_RESOLVER_PRIORITY`) |
| Which GPU to pick from 49 results | LLM with structured output |
| Whether raw API data answers the user goal | LLM (goal_reasoner) |
| What message to show the user | LLM (response_formatter) |

This matters because:
- Deterministic code is fast, free, and testable
- LLM calls cost money and add latency — use them only where reasoning is genuinely needed
- Failures are easier to trace when you know which layer failed

### 2. The REGISTRY as a Self-Describing API Contract

Every endpoint is registered with a schema that drives the entire agent:

```python
"create_pod": {
    "description": "Deploy / create / launch a new GPU pod ...",
    "category": "create",
    "method": "POST",
    "path_template": "/{provider}/create_pod",
    "path_params": ["provider"],
    "query_params": ["name", "gpu_id", "image_name", ...],
    "requires": ["provider", "name", "gpu_id"],        # hard requirements
    "api_lookup_params": ["gpu_id"],                   # must be API-resolved, never user-typed
    "cost_incurring": True,                            # triggers confirmation gate
    "resolver_for": [],
}
```

The agent derives its entire behavior from this registry:
- Which params are needed (`requires`)
- Which params can't come from user text (`api_lookup_params`)
- Whether to show a confirmation gate (`cost_incurring` / `destructive`)
- Which endpoints help resolve other endpoints (`resolver_for`)
- What context to give the LLM (`description` → `endpoint_hints`)

Adding a new provider endpoint = adding one dict entry. No code changes needed elsewhere.

### 3. The `api_lookup_params` Guard

A critical correctness mechanism. When a user says "deploy RTX 4090", the intent_parser might extract `gpu_id: "RTX 4090"`. But `"RTX 4090"` is not a valid API identifier — the real ID is `"NVIDIA GeForce RTX 4090"`.

The guard works in two places:
1. **intent_parser system prompt** — explicitly tells the LLM never to extract `gpu_id`, `pod_id`, `volume_id`, `datacenter_id`
2. **create_planner** — strips any collected value for `api_lookup_params` before building the resolution plan

This makes the system robust even if the LLM ignores the first instruction.

---

## The `goal_reasoner` Node

This is the most sophisticated node. It handles a fundamental mismatch: the API returns raw data, but the user asked a semantic question.

**Example:** User asks "show me cheapest H100". The API returns all 49 GPUs. The raw data doesn't answer "cheapest H100" — it needs filtering.

**Two-phase design:**

**Phase 1 — Evaluate:** Ask the LLM with a *preview* of the data (5 items, not all 49):
```
Input:  {user_goal: "cheapest H100", data_preview: [first 5 GPUs]}
Output: {needs_transform: true, transform_instruction: "filter by H100, sort by hourly_price asc, return cheapest"}
```

Why use preview here? Because the LLM only needs to *decide* whether transformation is needed, not execute it. Preview is enough for that decision, and it's 10x cheaper.

**Phase 2 — Transform:** Send the *full data* to the LLM with the instruction:
```
Input:  {user_goal: "cheapest H100", transform_instruction: "...", data: [all 49 GPUs]}
Output: {transformed_result: {gpu: H100 SXM, price: $3.39}, explanation: "..."}
```

This two-phase design prevents context overflow on phase 1 while giving the full dataset for phase 2.

---

## The Create Workflow in Detail

### Why a Dedicated Create Workflow?

Generic dependency resolution (the read/action flow) works by: compute missing → call resolver → extract value → loop. This fails for creates because:
- Creates have many optional params that should get defaults, not be asked from the user
- `gpu_id` needs API resolution from a catalog, not from a simple dependency resolver
- After resolution, params need validation before confirmation
- The confirmation shows the full payload, not just a single resolved value

The dedicated create workflow handles all of this.

### `create_planner` — Deterministic Classification

Three buckets, filled deterministically:

```
api_lookup_params (from REGISTRY) → always pending_auto
    ↓ find resolver from _RESOLVER_PRIORITY dict
    ↓ build resolver_params from already-known params

optional params (not in requires) → check _CREATE_DEFAULTS dict
    ↓ if default exists → add to defaults bucket (never ask user)

remaining required params (not collected, not api_lookup) → pending_user
    ↓ LLM generates ONE friendly question per param
```

The LLM is only called to write the question text — not to decide which bucket a param goes in. This is reliable because classification is deterministic.

### `create_api_resolver` — Automatic GPU Lookup

```
1. Take first item from pending_auto
2. Call the resolver endpoint (e.g. GET /pod_context/runpod)
3. If 0 results → move to pending_user, ask human
4. If 1 result → auto-accept, no question
5. If N results → call LLM with {candidates, filter_hint}
   - LLM picks best match (e.g. "NVIDIA GeForce RTX 4090")
   - If LLM is uncertain (found=false) → move to pending_user with numbered list
6. Loop back (route_create_step) until pending_auto is empty
```

The LLM filter receives the full candidate list (up to 30 items) with the user's original goal as the filter hint. This is where the "RTX 4090" in the user's message actually gets used — as a semantic search hint against real API data.

---

## Known Issues and Current Limitations

### 1. No Conversation Memory Across Sessions
Each CLI session creates a new `thread_id`. When the user exits and reopens, all context is lost. The `MemorySaver` only persists within a single process run.

**Impact:** User has to re-specify provider, preferences, etc. every session.
**Fix path:** Replace `MemorySaver` with `SqliteSaver` or `PostgresSaver`. Thread IDs could be stored in a user profile.

### 2. `name` Inference from Context
When user says "deploy RTX 4090 on runpod", the intent_parser sometimes infers `name: "RTX 4090"` from the phrase — using the GPU model name as the pod name. This is wrong but not harmful (user can change it at confirmation).

**Root cause:** The LLM extracts `name` (a safe-to-extract param) from the same phrase it associates with the GPU.
**Fix path:** Block `name` from intent_parser extraction for create_pod, force it to pending_user always.

### 3. Novita `gpu_id` Format Mismatch
RunPod's `create_pod` uses `gpu_id` as a type identifier (e.g. `"NVIDIA GeForce RTX 4090"`). Novita's `create_pod` uses `product_id` which is a different format (e.g. `"4090.16c62g.os"`). The REGISTRY uses `gpu_id` for both, and the connector maps `gpu_id` → `product_id` for Novita. This works but is confusing.

**Fix path:** Add a `provider_param_map` field to REGISTRY entries that remaps generic param names to provider-specific names.

### 4. `network_volume_id` Bloat
The create_pod confirmation still shows `network_volume_id: null` in the payload. This adds noise and confuses users who don't know what it is.

**Fix path:** Filter out `None`-valued optional params before the confirmation display.

### 5. Error Recovery is Primitive
If `create_api_resolver` gets a 429 rate limit or 503 from the backend, it shows an error message and ends the flow. There's no retry logic, no fallback provider, no partial state recovery.

**Fix path:** Add retry with exponential backoff in `_call_endpoint`. Add a `retry_plan` field to state for mid-flow recovery.

### 6. Single-Threaded HTTP Calls
When `create_planner` has multiple items in `pending_auto` (e.g. both `gpu_id` and `datacenter_id`), it resolves them sequentially. These could be parallelized.

**Fix path:** Use `asyncio` + `httpx` for the connector, run independent resolver calls concurrently.

### 7. No Auth / Multi-User Isolation
The connector has no authentication. Any process that can reach `localhost:8001` can trigger pod creation. The `MemorySaver` is shared in-process.

**Fix path:** Add API key middleware to FastAPI. Use per-user thread namespaces in LangGraph state.

---

## Why This Architecture Will Scale

### Adding a New Provider
1. Implement `CompoundProviderX` with `.pods.create_pod()`, `.volume.get_user_volume()`, etc.
2. Add to `providers = {"providerx": CompoundProviderX()}` in connector.py
3. Add the scheduler job to sync its GPU catalog
4. Zero changes to showdown.py — the REGISTRY + LangGraph graph are provider-agnostic

### Adding a New Operation
1. Add a REGISTRY entry with correct `category`, `requires`, `cost_incurring`, etc.
2. Add the FastAPI endpoint in connector.py
3. The LangGraph graph handles it automatically — no new nodes needed for standard CRUD

### Upgrading the LLM
The LLM is injected as `llm = ChatGroq(...)` at the top. Swap to GPT-4, Claude 3.5, or a local Ollama model by changing one line. All nodes use the same `llm` object.

---

## What Makes This Production-Worthy vs. a Demo

| Demo Agent | This Agent |
|-----------|-----------|
| Hardcoded tool list | Self-describing REGISTRY, dynamic endpoint hints |
| Single LLM call | 3-6 LLM calls per workflow with specialized prompts |
| No human oversight | 3 explicit HITL interrupt points |
| No error handling | Error propagated to `error_state`, formatted for user |
| No state persistence | LangGraph checkpointer with thread isolation |
| Mock API calls | Real HTTP calls to live cloud provider APIs |
| One-shot execution | Iterative resolution loop with cycle protection |
| No cost protection | Confirmation gate before every cost-incurring operation |
