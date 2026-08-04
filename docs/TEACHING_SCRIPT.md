# 15-Minute Teaching Video — Script

**Topic:** Building a Real LangGraph Agent that Orchestrates Cloud GPU Deployments
**Audience:** Developers with Python experience, new to LangGraph / agentic AI
**Goal:** By the end, viewers understand how to build a stateful multi-step agent with HITL, not just a single tool-calling LLM

---

## Minute 0:00–1:00 — Hook: The Problem

> "Imagine you're an ML engineer and you need to spin up a GPU pod to run a training job. You go to RunPod, scroll through 49 GPU options, compare prices, pick one, fill out a form with 12 fields, wait. Tomorrow you do the same thing on Novita. You're spending 20–30 minutes just on infrastructure admin."

> "What if you could just say: `deploy RTX 4090 on runpod` — and an AI handles everything, asks only what it needs, shows you a confirmation, and deploys it?"

> "That's what I built — and today I'm going to show you how it works and how you can build something like it."

**Show on screen:** The CLI prompt. Type: `deploy RTX 4090 on runpod`. Let it run to the confirmation gate. Hold at the yes/no prompt.

---

## Minute 1:00–2:30 — What Is LangGraph (The Concept)

> "Before we look at the code, let me explain the key idea behind LangGraph."

> "In most LLM apps, you have a chain: prompt in → LLM → output. That's fine for simple Q&A."

> "But for an agent that needs to call APIs, collect information across multiple steps, wait for user input, and then execute — you need a **graph** with **state**."

Draw on whiteboard (or show diagram):
```
[Node A] → [Node B] → [HUMAN INPUT] → [Node C] → [Execute]
```

> "LangGraph lets you define nodes as Python functions, connect them with edges, and persist a state dictionary across all of them — including across pauses where you wait for the user."

> "The breakthrough is `interrupt_before`. You can tell LangGraph: pause here, wait for human input, then resume exactly where you left off."

---

## Minute 2:30–5:00 — Live Demo (Full Walkthrough)

Continue from the paused CLI at the confirmation gate.

> "Here's where we paused — the agent collected all the parameters automatically. It resolved the GPU ID from the live RunPod catalog — the user said 'RTX 4090', the agent found `NVIDIA GeForce RTX 4090` which is the actual API identifier."

> "I'm going to type `yes` and we'll see it deploy."

Type `yes`. Wait for response. Show pod ID returned.

> "That's a real deployment — $0.74/hr on a real RunPod account."

Now demo a query:
> "Let me show you the other side — asking questions."

Type: `show me cheapest H100`

> "Notice — no forms, no filters, no browser. The agent calls the catalog API, finds all H100 variants, ranks them by price, and tells me the cheapest one."

> "It also checked whether the raw data actually answered my question using a `goal_reasoner` node — we'll talk about that."

---

## Minute 5:00–7:30 — Architecture Deep Dive

Switch to architecture diagram (show `docs/ARCHITECTURE.md`).

> "Let me walk you through how this actually works."

> "There are two main paths through the graph. When you ask a **question or trigger an action**, the agent goes through the read/action path — it figures out what endpoint to call, collects any missing parameters by calling other endpoints, then calls the goal and reasons over the result."

> "When you want to **create something** — deploy a pod, create a volume — it takes the create path. This is a dedicated sub-workflow with its own nodes."

**Point to each node as you explain:**

`intent_parser`: *"LLM parses your sentence into a structured intent — what endpoint, what params. Critically, it knows NOT to extract GPU IDs from user text because those need to be API-validated."*

`create_planner`: *"Deterministic classifier — no LLM here. It sorts every parameter into one of three buckets: auto-resolve via API, ask user, or use a default value. This avoids over-asking the user for things like image name or disk size that have sensible defaults."*

`create_api_resolver`: *"Calls the GPU catalog, gets 49 results, passes them to the LLM with the user's original phrase as a filter hint. The LLM picks the closest match — `RTX 4090` → `NVIDIA GeForce RTX 4090`."*

`confirmation_gate`: *"LangGraph interrupt. The graph literally pauses here. The full payload is shown, the user types yes or no. If no, the flow ends — no accidental charges."*

---

## Minute 7:30–9:30 — Key LangGraph Concepts in Code

Show code snippets (have showdown.py open, jump to key sections):

**1. Defining the graph with interrupt points:**
```python
app = workflow.compile(
    checkpointer=MemorySaver(),
    interrupt_before=["selection_node", "confirmation_gate", "create_user_clarifier"]
)
```

> "Three nodes are interrupt points. When the graph reaches any of them, it pauses and waits."

**2. The resume pattern:**
```python
# User typed their response — inject it and resume
app.update_state(config, {"messages": [HumanMessage(content=user_input)]})
result = app.invoke(None, config=config)
```

> "This is the key pattern. You inject the human's message into the state, then call invoke with `None` as input — that tells LangGraph to resume from the checkpoint, not start over."

**3. State as the single source of truth:**
```python
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    collected_params: Dict[str, Any]
    pending_selection: Optional[Dict[str, Any]]
    create_plan: Optional[Dict[str, Any]]
    # ... 15 more fields
```

> "Every piece of information flows through this state dict. Every node reads from it and writes to it. This is what makes the graph resumable — the entire context is serialized."

---

## Minute 9:30–11:00 — The REGISTRY Pattern (Key Design Insight)

> "The most important architectural decision was the REGISTRY."

Show the REGISTRY dict in showdown.py:

```python
REGISTRY = {
    "create_pod": {
        "description": "Deploy a new GPU pod ...",
        "requires": ["provider", "name", "gpu_id"],
        "api_lookup_params": ["gpu_id"],
        "cost_incurring": True,
        "resolver_for": [],
    },
    "get_gpu_catalog": {
        "resolver_for": ["gpu_id"],
        ...
    }
}
```

> "Every endpoint in the system is described in this registry. The agent's routing logic reads from here — it doesn't have hardcoded rules about which endpoint to call for what."

> "When the agent needs a `gpu_id`, it looks up `_RESOLVER_PRIORITY['gpu_id']` and finds `get_pod_context` first, then `get_gpu_catalog`. It tries them in order."

> "When you add a new provider endpoint, you add one dict entry. The agent handles it automatically."

---

## Minute 11:00–12:30 — Current Limitations (Honest Assessment)

> "I want to be honest about where this project is today."

> "**Memory doesn't persist across sessions.** Each CLI run starts fresh. The LangGraph MemorySaver is in-process only. Production fix: use SqliteSaver."

> "**Error recovery is minimal.** If the API returns a 429 or 503 mid-flow, the agent fails gracefully but doesn't retry. Production fix: exponential backoff + retry state."

> "**The LLM can still misroute.** I've added explicit rules for `deploy` → `create_pod`, but edge cases still trip up the intent parser. The fix is better few-shot examples and tighter structured output."

> "These are all engineering problems with known solutions — not design flaws. The architecture is correct."

---

## Minute 12:30–14:00 — What This Teaches You About Agentic AI

> "Let me pull out the generalizable lessons."

**Lesson 1: Design for HITL from the start.**
> "Don't build an agent that tries to do everything autonomously. Build in explicit pause points where the human stays in control of high-stakes decisions."

**Lesson 2: Be explicit about what the LLM does and doesn't do.**
> "I have 15 nodes. Only 4 make LLM calls. The rest are pure Python. This makes the system fast, cheap, and debuggable."

**Lesson 3: State is the agent's memory.**
> "A stateful agent is just a function that reads and writes to a dict, connected to other functions that do the same. LangGraph manages the transitions. Don't over-architect it."

**Lesson 4: The REGISTRY pattern scales.**
> "If you're building an agent with more than 3 tools, encode your tools as data, not code. The agent's routing logic becomes generic, and adding a tool is just adding a config entry."

---

## Minute 14:00–15:00 — Wrap-Up + What's Next

> "To recap: we built a LangGraph agent that takes natural language, resolves all required parameters through API calls, applies smart defaults, gets human confirmation before spending money, and executes the deployment."

> "The agent is live. RunPod and Novita are real providers. The pods it deploys are real."

> "Where this goes next: multi-provider real-time price arbitrage, persistent user profiles, batch deployments, cost monitoring and alerting. The foundation supports all of it."

> "The code is fully open source. Readme is in the repo. If you have questions, the issues tab is open."

---

## Technical Demo Checklist (Pre-Recording)

- [ ] Backend connector running: `uvicorn connector:app --reload --port 8001`
- [ ] .env has valid RUNPOD_API_KEY, GROQ_API_KEY
- [ ] Chrome CDP running on port 9222 (for Playwright scrapers if needed)
- [ ] RunPod account has sufficient credits (>$5 buffer)
- [ ] Test `deploy RTX 4090 on runpod` dry run, confirm to pod creation, then stop/delete immediately after recording
- [ ] Test `show me cheapest H100` confirms goal_reasoner is working
- [ ] Terminal font size 16pt or larger for screen visibility
- [ ] Kill any background processes that might print to terminal during recording

## Backup Demo (If API is Down)

Show the `execution_history` from a previous session — paste a pre-recorded JSON trace. Walk through the same architecture explanation against the trace. The architecture explanation is the valuable part, not the live API.
