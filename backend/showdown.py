from typing import TypedDict, List, Dict, Any, Optional, Set, Annotated
import operator
import json
import re
import logging
import uuid
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, SystemMessage
import urllib.parse
import requests
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os
from rich import print

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY. Set it in your .env file.")

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=GROQ_API_KEY,
    temperature=0
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("showdown")

# --- State Definition ---
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    flow_category: str                    # "create", "action", "resolver"
    goal_endpoint: Optional[str]
    current_resolver: Optional[str]
    collected_params: Dict[str, Any]
    missing_params: List[str]
    pending_selection: Optional[Dict[str, Any]] # {field, candidates[], resolver_id}
    visited_endpoints: Annotated[List[str], operator.add] 
    execution_history: Annotated[List[Dict[str, Any]], operator.add]
    iteration_count: int
    confirmation_pending: bool
    confirmation_payload: Optional[Dict[str, Any]]
    error_state: Optional[str]
    final_result: Optional[Dict[str, Any]]
    raw_api_response: Optional[Dict[str, Any]]
    last_executed_endpoint: Optional[str]
    last_endpoint_response: Optional[Dict[str, Any]]
    extracted_value: Optional[Any]
    user_goal: Optional[str]           # original semantic goal captured at intent parse
    reasoning_notes: Optional[str]     # accumulated goal_reasoner explanations
    create_plan: Optional[Dict[str, Any]]  # structured resolution plan for create workflows

# --- Mock Metadata Registry ---
# In production, this would be loaded from your FastAPI connector definitions.
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8001")

REGISTRY = {
    # --- Catalog & Metadata Resolvers ---
    "get_providers": {
        "description": "List all available GPU cloud providers (e.g. runpod, novita). Use to discover or resolve the provider param.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/providers",
        "path_params": [],
        "query_params": [],
        "requires": [],
        "produces": ["providers"],
        "resolver_for": ["provider"],
        "response_list_key": "providers",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_all_gpus": {
        "description": "List ALL GPUs across every provider with prices. Use when user asks for best/cheapest/recommended GPU or compares across providers. The reasoning node filters/ranks the result.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/gpus",
        "path_params": [],
        "query_params": [],
        "requires": [],
        "produces": ["gpus"],
        "resolver_for": ["gpu_name", "gpu_id", "hourly_price"],
        "response_list_key": "gpus",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_provider_gpus": {
        "description": "List GPUs for ONE specific provider. Use when provider is explicitly stated. Returns real gpu_id values needed for create_pod.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/gpus/{provider}",
        "path_params": ["provider"],
        "query_params": [],
        "requires": ["provider"],
        "produces": ["gpus"],
        "resolver_for": ["gpu_name", "gpu_id"],
        "response_list_key": "gpus",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_provider_gpu_availability": {
        "description": "List real-time GPU availability slots for a provider. Returns product_id / gpu_id values suitable for pod creation on Novita.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/{provider}/gpu_availability",
        "path_params": ["provider"],
        "query_params": [],
        "requires": ["provider"],
        "produces": ["gpu_availability"],
        "resolver_for": ["gpu_id", "product_id"],
        "response_list_key": "gpu_availability",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_gpu_metadata": {
        "description": "Fetch detailed metadata for ONE specific GPU by its exact gpu_id. Only use when gpu_id is already known from a previous lookup.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/{provider}/gpu_metadata",
        "path_params": ["provider"],
        "query_params": ["gpu_id"],
        "requires": ["provider", "gpu_id"],
        "produces": ["gpu"],
        "response_list_key": None,
        "selection_strategy": "single",
        "cost_incurring": False,
        "destructive": False,
    },

    # --- Pod Operations ---
    "get_user_pods": {
        "description": "List all running/stopped pods owned by the user for a given provider. Used to resolve pod_id before start/stop/delete operations.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/{provider}/user_pods",
        "path_params": ["provider"],
        "query_params": [],
        "requires": ["provider"],
        "produces": ["pods"],
        "resolver_for": ["pod_id"],
        "response_list_key": "pods",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_user_pod": {
        "description": "Fetch details of ONE specific pod by its exact pod_id.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/{provider}/user_pod/{pod_id}",
        "path_params": ["provider", "pod_id"],
        "query_params": [],
        "requires": ["provider", "pod_id"],
        "produces": ["pod"],
        "response_list_key": None,
        "selection_strategy": "single",
        "cost_incurring": False,
        "destructive": False,
    },
    "create_pod": {
        "description": (
            "Deploy / create / launch / spin up a new GPU pod. Trigger words: deploy, create, launch, spin up, start a pod. "
            "Requires provider, a user-chosen name, and a real gpu_id. "
            "ALWAYS resolve gpu_id via get_gpu_catalog or get_pod_context — never accept a raw model name."
        ),
        "category": "create",
        "method": "POST",
        "path_template": "/{provider}/create_pod",
        "path_params": ["provider"],
        "query_params": [
            "name", "gpu_id", "image_name", "gpu_count",
            "container_disk_gb", "volume_gb", "volume_mount_path",
            "network_volume_id", "vcpu_count"
        ],
        "requires": ["provider", "name", "gpu_id"],
        "produces": ["pod"],
        "cost_incurring": True,
        "destructive": False,
        # gpu_id must be resolved from get_gpu_catalog — user text is never a valid api gpu_id
        "api_lookup_params": ["gpu_id"],
    },
    "start_pod": {
        "description": "Start (resume) an existing stopped pod. Requires the real pod_id from get_user_pods.",
        "category": "action",
        "method": "POST",
        "path_template": "/{provider}/start_pod/{pod_id}",
        "path_params": ["provider", "pod_id"],
        "query_params": [],
        "requires": ["provider", "pod_id"],
        "produces": ["result"],
        "cost_incurring": True,
        "destructive": False,
    },
    "stop_pod": {
        "description": "Stop a running pod (keeps it billed at storage rate). Requires the real pod_id.",
        "category": "action",
        "method": "POST",
        "path_template": "/{provider}/stop_pod/{pod_id}",
        "path_params": ["provider", "pod_id"],
        "query_params": [],
        "requires": ["provider", "pod_id"],
        "produces": ["result"],
        "cost_incurring": False,
        "destructive": True,
    },
    "delete_pod": {
        "description": "Permanently delete a pod. Requires the real pod_id from get_user_pods. This is irreversible.",
        "category": "action",
        "method": "DELETE",
        "path_template": "/{provider}/delete_pod/{pod_id}",
        "path_params": ["provider", "pod_id"],
        "query_params": [],
        "requires": ["provider", "pod_id"],
        "produces": ["result"],
        "cost_incurring": False,
        "destructive": True,
    },

    # --- Volume Operations ---
    "get_user_volumes": {
        "description": "List all network volumes owned by the user for a provider. Used to resolve volume_id before delete operations.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/{provider}/user_volumes",
        "path_params": ["provider"],
        "query_params": [],
        "requires": ["provider"],
        "produces": ["volumes"],
        "resolver_for": ["volume_id"],
        "response_list_key": "volumes",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "create_volume": {
        "description": "Create a new persistent network volume. Requires provider, datacenter_id (from get_datacenters), a name, and size in GB.",
        "category": "create",
        "method": "POST",
        "path_template": "/{provider}/create_volume",
        "path_params": ["provider"],
        "body_params": ["datacenter_id", "name", "size"],  # Pydantic JSON Body
        "requires": ["provider", "datacenter_id", "name", "size"],
        "produces": ["result"],
        "cost_incurring": True,
        "destructive": False,
        "api_lookup_params": ["datacenter_id"],
    },
    "delete_volume": {
        "description": "Permanently delete a network volume by its real volume_id. Irreversible.",
        "category": "action",
        "method": "DELETE",
        "path_template": "/{provider}/delete_volume/{volume_id}",
        "path_params": ["provider", "volume_id"],
        "query_params": [],
        "requires": ["provider", "volume_id"],
        "produces": ["result"],
        "cost_incurring": False,
        "destructive": True,
    },

    # --- Comprehensive Catalog (preferred for create workflows) ---
    "get_gpu_catalog": {
        "description": (
            "PREFERRED resolver for gpu_id. Returns ALL GPUs from all providers with API-ready gpu_id values "
            "(no provider prefix — plug directly into create_pod). Supports optional ?provider=runpod and "
            "?available_only=true query params. The LLM should use filter_hint to pick the best match."
        ),
        "category": "resolver",
        "method": "GET",
        "path_template": "/gpu_catalog",
        "path_params": [],
        "query_params": ["provider", "available_only"],
        "requires": [],
        "produces": ["gpus"],
        "resolver_for": ["gpu_id"],
        "response_list_key": "gpus",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_pod_context": {
        "description": (
            "Returns available deployable GPUs (API-ready gpu_ids) + user volumes + default params "
            "for ONE provider. Use to get everything needed for create_pod in one call."
        ),
        "category": "resolver",
        "method": "GET",
        "path_template": "/pod_context/{provider}",
        "path_params": ["provider"],
        "query_params": [],
        "requires": ["provider"],
        "produces": ["available_gpus", "user_volumes", "defaults"],
        "resolver_for": ["gpu_id"],
        "response_list_key": "available_gpus",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
    "get_datacenters": {
        "description": "List all datacenter IDs for a provider. Use to resolve datacenter_id for create_volume.",
        "category": "resolver",
        "method": "GET",
        "path_template": "/{provider}/datacenters",
        "path_params": ["provider"],
        "query_params": [],
        "requires": ["provider"],
        "produces": ["datacenters"],
        "resolver_for": ["datacenter_id"],
        "response_list_key": "datacenters",
        "selection_strategy": "requires_selection",
        "cost_incurring": False,
        "destructive": False,
    },
}


def _safe_json_loads(raw_text: str) -> Optional[Dict[str, Any]]:
    """Parses strict JSON, with a fallback to the first JSON object block if needed."""
    if not raw_text:
        return None

    try:
        data = json.loads(raw_text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", raw_text)
    if not match:
        return None

    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None

def _call_endpoint(endpoint_id: str, source_params: Dict[str, Any]) -> Dict[str, Any]:
    """Shared low-level HTTP dispatch. Returns {ok, data, status, url} or {ok, error}."""
    if endpoint_id not in REGISTRY:
        return {"ok": False, "error": f"Unknown endpoint: {endpoint_id}"}
    meta = REGISTRY[endpoint_id]
    method = meta["method"].upper()
    path_args = {}
    for p in meta.get("path_params", []):
        val = source_params.get(p)
        if val is None:
            return {"ok": False, "error": f"Missing path param '{p}' for {endpoint_id}"}
        path_args[p] = urllib.parse.quote(str(val), safe="")
    full_url = f"{FASTAPI_BASE_URL}{meta['path_template'].format(**path_args)}"
    query_args = {p: source_params[p] for p in meta.get("query_params", []) if source_params.get(p) is not None}
    json_body = None
    if "body_params" in meta:
        json_body = {p: source_params[p] for p in meta["body_params"] if source_params.get(p) is not None}
    try:
        resp = requests.request(
            method=method, url=full_url,
            params=query_args or None, json=json_body or None,
            headers={"Content-Type": "application/json"}, timeout=15.0
        )
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text}
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {data.get('message', resp.text)}", "data": data}
        return {"ok": True, "data": data, "status": resp.status_code, "url": full_url, "method": method}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": str(e)}


def _summarize_data(data: Any, max_items: int = 5) -> Any:
    """Returns a compact preview so large arrays don't flood LLM eval context."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if isinstance(v, list) and len(v) > max_items:
                out[k] = v[:max_items] + [{"_truncated": f"{len(v) - max_items} more items"}]
            else:
                out[k] = v
        return out
    if isinstance(data, list) and len(data) > max_items:
        return data[:max_items] + [{"_truncated": f"{len(data) - max_items} more items"}]
    return data


def intent_parser(state: AgentState):
    """LLM: Parses user intent into a goal endpoint and initial params via strict JSON."""
    logger.info("intent_parser: started")
    user_message = str(state["messages"][-1].content)
    existing_collected = dict(state.get("collected_params", {}))
    allowed_endpoints = list(REGISTRY.keys())

    # Build endpoint hints dynamically from registry descriptions
    endpoint_hints = "\n".join(
        f"  {eid}: {meta['description']}"
        for eid, meta in REGISTRY.items()
        if meta.get("description")
    )

    # Params that are internal API identifiers — must NEVER be extracted from user text
    api_lookup_only = {"gpu_id", "pod_id", "volume_id", "product_id", "datacenter_id"}

    system_prompt = (
        "You are an intent parser for a GPU orchestration graph. "
        "Return ONLY valid JSON with this exact schema: "
        '{"goal_endpoint":"","flow_category":"","collected_params":{}}. '
        "No markdown, no explanation, no extra keys. "
        f"goal_endpoint must be one of: {allowed_endpoints}. "
        "flow_category must be one of: ['create','action','resolver']. "
        "Extract only explicitly stated parameters from the user request. "
        f"NEVER put these params in collected_params — they require API lookup: {sorted(api_lookup_only)}. "
        "Safe to extract: provider (e.g. 'runpod'), name (user-chosen label), size (number), image_name (docker image string). "
        "Intent disambiguation (use these FIRST before endpoint descriptions):\n"
        "  deploy/create/launch/spin up/start new pod → create_pod, flow_category=create\n"
        "  create volume/storage → create_volume, flow_category=create\n"
        "  stop/terminate pod → stop_pod, flow_category=action\n"
        "  delete pod → delete_pod, flow_category=action\n"
        "  list/show/find/compare gpus (no create intent) → get_all_gpus or get_gpu_catalog, flow_category=resolver\n"
        "  show my pods/list pods → get_user_pods, flow_category=resolver\n"
        "Endpoint descriptions:\n" + endpoint_hints
    )

    parse_prompt = (
        f"User request: {user_message}\n"
        f"Existing collected_params: {json.dumps(existing_collected)}"
    )

    parsed: Optional[Dict[str, Any]] = None
    parser_warning: Optional[str] = None

    try:
        llm_response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=parse_prompt)
        ])
        parsed = _safe_json_loads(str(llm_response.content))
    except Exception as e:
        parser_warning = f"LLM intent parse failed: {str(e)}"

    if parsed is None and parser_warning is None:
        parser_warning = "LLM returned non-JSON or invalid JSON for intent parsing"

    goal = parsed.get("goal_endpoint") if isinstance(parsed, dict) else None
    flow_category = parsed.get("flow_category") if isinstance(parsed, dict) else None
    parsed_collected = parsed.get("collected_params") if isinstance(parsed, dict) else {}

    if not isinstance(parsed_collected, dict):
        parsed_collected = {}

    collected = {**existing_collected, **parsed_collected}

    if not isinstance(goal, str) or goal not in REGISTRY:
        goal = "get_providers"
        flow_category = "resolver"
        collected.setdefault("intent_parse_warning", "Fallback endpoint used due to invalid LLM goal_endpoint")

    if flow_category not in {"create", "action", "resolver"}:
        flow_category = str(REGISTRY[goal].get("category", "action"))

    if parser_warning:
        collected.setdefault("intent_parse_warning", parser_warning)

    result: Dict[str, Any] = {
        "goal_endpoint": goal,
        "flow_category": flow_category,
        "collected_params": collected,
        "iteration_count": 0,
        "user_goal": user_message,
    }

    logger.info(
        "intent_parser: goal=%s flow_category=%s collected_keys=%s",
        goal,
        flow_category,
        sorted(list(collected.keys()))
    )

    return result

def dependency_resolver(state: AgentState):
    """Deterministic: Computes missing = requires - collected."""
    logger.info("dependency_resolver: started for goal=%s", state.get("goal_endpoint"))
    goal = state["goal_endpoint"]
    requires = REGISTRY[goal]["requires"]
    collected = state["collected_params"]
    
    missing = [req for req in requires if req not in collected]
    
    # Progress/Cycle Safety Check
    if state["iteration_count"] > 10:
        return {"error_state": "Max iterations reached"}
        
    return {
        "missing_params": missing,
        "iteration_count": state["iteration_count"] + 1
    }

def endpoint_selector(state: AgentState):
    """Deterministic: Picks the best resolver for the first missing param."""
    logger.info("endpoint_selector: started")
    target_field = state["missing_params"][0]
    
    # Find endpoints that resolve this field
    resolvers = [
        eid for eid, meta in REGISTRY.items() 
        if target_field in meta.get("resolver_for", [])
    ]
    
    if not resolvers:
        return {"error_state": f"No resolver found for {target_field}"}
        
    # Simplified selection: just pick the first one
    logger.info("endpoint_selector: target_field=%s selected_resolver=%s", target_field, resolvers[0])
    return {"current_resolver": resolvers[0]}



def router_executor(state: Dict[str, Any]) -> Dict[str, Any]:
    """Universal HTTP execution engine for both resolver and goal endpoints."""
    if state.get("error_state"):
        logger.warning("router_executor: skipped due to existing error_state")
        return {}

    endpoint_id = state.get("current_resolver") or state.get("goal_endpoint")
    logger.info("router_executor: started endpoint=%s", endpoint_id)

    if not endpoint_id or endpoint_id not in REGISTRY:
        return {"error_state": f"Invalid or unregistered endpoint: {endpoint_id}"}

    source_params = state.get("confirmation_payload") or state.get("collected_params", {})
    result = _call_endpoint(endpoint_id, source_params)
    logger.info("router_executor: %s %s", REGISTRY[endpoint_id]["method"].upper(), result.get("url", ""))

    if not result["ok"]:
        logger.error("router_executor: error endpoint=%s error=%s", endpoint_id, result["error"])
        return {
            "error_state": f"Backend API Error: {result['error']}",
            "last_endpoint_response": result.get("data")
        }

    response_json = result["data"]
    result_key = "final_result" if endpoint_id == state.get("goal_endpoint") else "raw_api_response"
    out = {
        result_key: response_json,
        "last_executed_endpoint": endpoint_id,
        "visited_endpoints": [endpoint_id],
        "execution_history": [{
            "endpoint": endpoint_id,
            "url": result.get("url", ""),
            "method": result.get("method", ""),
            "status": result.get("status"),
            "response": response_json
        }]
    }
    if result_key == "final_result":
        out["raw_api_response"] = None
    logger.info("router_executor: success endpoint=%s status=%s result_key=%s", endpoint_id, result.get("status"), result_key)
    return out
    
    
def result_extractor(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses real JSON output from the FastAPI backend.
    Extracts nested candidate arrays (e.g. response['pods']) and decides whether
    the result is single-valued or requires narrowing via candidate selection.
    """
    endpoint_id = state.get("current_resolver") or state.get("goal_endpoint")
    logger.info("result_extractor: started endpoint=%s", endpoint_id)
    raw_response = state.get("raw_api_response", {})
    
    if not endpoint_id or endpoint_id not in REGISTRY:
        return {"error_state": "No endpoint metadata available for response extraction"}
        
    meta = REGISTRY[endpoint_id]
    list_key = meta.get("response_list_key")
    
    # 1. Unbox list response if wrapped under a key (e.g. {"pods": [...]})
    items = []
    if list_key and isinstance(raw_response, dict) and list_key in raw_response:
        items = raw_response[list_key]
    elif isinstance(raw_response, list):
        items = raw_response
    elif isinstance(raw_response, dict):
        items = [raw_response]

    target_field = state["missing_params"][0] if state.get("missing_params") else None

    # 2. Evaluate Cardinality
    if len(items) > 1:
        # Multiple candidates returned -> Requires auto-narrowing or user choice
        logger.info("result_extractor: multiple candidates count=%s target_field=%s", len(items), target_field)
        return {
            "pending_selection": {
                "field": target_field,
                "candidates": items,
                "resolver_endpoint": endpoint_id
            }
        }
    elif len(items) == 1:
        # Single candidate -> Automatically extract resolved field
        item = items[0]
        extracted_val = item.get(target_field) if isinstance(item, dict) and target_field in item else item
        logger.info("result_extractor: single candidate resolved target_field=%s", target_field)
        return {"extracted_value": extracted_val}
    else:
        logger.warning("result_extractor: zero results endpoint=%s", endpoint_id)
        return {"error_state": f"Endpoint '{endpoint_id}' returned 0 results for required parameter target."}

def selection_node(state: AgentState):
    """HITL: Halts for human input if LLM cannot auto-narrow."""
    # The graph will physically pause BEFORE this node via interrupt_before.
    # When resumed, the user's choice should be in the messages array.
    last_msg = state["messages"][-1].content
    
    # Process the user's manual selection
    pending = state["pending_selection"]
    chosen_val = last_msg # Simplified extraction of user choice
    logger.info("selection_node: user provided selection for field=%s", pending.get("field") if pending else None)
    
    return {
        "extracted_value": chosen_val,
        "pending_selection": None
    }

def state_updater(state: AgentState):
    """Deterministic: Merges resolved value, clears temp states."""
    logger.info("state_updater: started")
    collected = state["collected_params"]
    field = state["missing_params"][0]
    
    collected[field] = state.get("extracted_value")
    
    return {
        "collected_params": collected,
        "current_resolver": None,
        "raw_api_response": None,
    }

def payload_assembler(state: AgentState):
    """Deterministic: Applies defaults for CREATE endpoints."""
    logger.info("payload_assembler: started for goal=%s", state.get("goal_endpoint"))
    collected = state["collected_params"]
    
    # Inject defaults based on the provider/endpoint
    if state["goal_endpoint"] == "create_pod":
        if "container_disk_gb" not in collected:
            collected["container_disk_gb"] = 20
        if "image_name" not in collected:
            collected["image_name"] = "runpod/pytorch:default"
            
    return {"confirmation_payload": collected}

def confirmation_gate(state: AgentState):
    """HITL: Pauses for explicit user approval."""
    logger.info("confirmation_gate: evaluating user approval")
    # Graph pauses BEFORE this node. User responds "yes" or "no".
    last_msg = state["messages"][-1].content.lower()
    
    if "yes" in last_msg or "approve" in last_msg:
        return {"confirmation_pending": False}
    else:
        return {"error_state": "User rejected execution"}

def goal_reasoner(state: AgentState) -> Dict[str, Any]:
    """LLM: Determines if user goal is satisfied; filters/ranks data when needed."""
    logger.info("goal_reasoner: started")
    user_goal = str(state.get("user_goal") or state["messages"][0].content)
    raw_data = state.get("final_result") or state.get("raw_api_response") or {}

    # Phase 1 — evaluate whether the raw API data already answers the goal
    eval_system = (
        "You are a goal evaluator for a GPU orchestration agent. "
        "Determine whether the user's goal is fully answered by the raw API result, "
        "or whether the data needs filtering, ranking, or selection first. "
        "Return ONLY valid JSON: "
        '{"needs_transform": true/false, "transform_instruction": "string", "reasoning": "string"}. '
        "needs_transform=false: raw data already fully answers the goal. "
        "needs_transform=true: data must be filtered, ranked, or selected. "
        "  transform_instruction: a precise actionable instruction for the transformation."
    )
    eval_input = json.dumps({
        "user_goal": user_goal,
        "goal_endpoint": state.get("goal_endpoint"),
        "data_preview": _summarize_data(raw_data),
    }, default=str)

    eval_parsed: Optional[Dict[str, Any]] = None
    try:
        r = llm.invoke([SystemMessage(content=eval_system), HumanMessage(content=eval_input)])
        eval_parsed = _safe_json_loads(str(r.content))
    except Exception:
        logger.exception("goal_reasoner: eval phase LLM failed")
        return {}

    if not isinstance(eval_parsed, dict):
        logger.warning("goal_reasoner: eval returned non-dict, skipping transform")
        return {}

    needs_transform = bool(eval_parsed.get("needs_transform"))
    reasoning = str(eval_parsed.get("reasoning", ""))
    logger.info("goal_reasoner: needs_transform=%s reasoning=%s", needs_transform, reasoning)

    if not needs_transform:
        return {"reasoning_notes": reasoning}

    # Phase 2 — apply the transformation the LLM prescribed
    transform_instruction = str(eval_parsed.get("transform_instruction", "Filter and rank the data."))
    transform_system = (
        "You are a data analyst for a GPU orchestration agent. "
        "Apply the given transformation instruction to the dataset. "
        "Return ONLY valid JSON: "
        '{"transformed_result": <filtered/ranked/selected data>, "explanation": "string"}. '
        "transformed_result must be the minimal answer to the user goal — "
        "a single item, a short ranked list, or a summary dict. "
        "Use only data present in the input. Do not fabricate values."
    )
    transform_input = json.dumps({
        "user_goal": user_goal,
        "transform_instruction": transform_instruction,
        "data": raw_data,
    }, default=str)

    transform_parsed: Optional[Dict[str, Any]] = None
    try:
        r2 = llm.invoke([SystemMessage(content=transform_system), HumanMessage(content=transform_input)])
        transform_parsed = _safe_json_loads(str(r2.content))
    except Exception:
        logger.exception("goal_reasoner: transform phase LLM failed")
        return {"reasoning_notes": reasoning}

    if not isinstance(transform_parsed, dict):
        logger.warning("goal_reasoner: transform returned non-dict")
        return {"reasoning_notes": reasoning}

    transformed = transform_parsed.get("transformed_result")
    explanation = str(transform_parsed.get("explanation", ""))
    logger.info("goal_reasoner: transform applied explanation=%s", explanation)

    return {
        "final_result": transformed if transformed is not None else raw_data,
        "reasoning_notes": f"{reasoning} | Transform: {explanation}",
    }


def response_formatter(state: AgentState):
    """LLM: Turns execution state into a concise natural language response."""
    logger.info("response_formatter: started")
    summary_payload = {
        "error_state": state.get("error_state"),
        "user_goal": state.get("user_goal"),
        "reasoning_notes": state.get("reasoning_notes"),
        "goal_endpoint": state.get("goal_endpoint"),
        "last_executed_endpoint": state.get("last_executed_endpoint"),
        "final_result": state.get("final_result"),
        "last_endpoint_response": state.get("last_endpoint_response"),
        "execution_history": state.get("execution_history", [])[-3:]
    }

    system_prompt = (
        "You are a response formatter for a GPU orchestration assistant. "
        "Write a clear, concise user-facing summary of the operation outcome. "
        "If there is an error_state, explain failure plainly and suggest a practical next step. "
        "If successful, summarize what was executed and the key result fields."
    )

    try:
        llm_response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=json.dumps(summary_payload, default=str))
        ])
        msg = str(llm_response.content).strip()
        if not msg:
            msg = "Operation completed, but no response text was generated."
    except Exception as e:
        logger.exception("response_formatter: formatter LLM failed")
        if state.get("error_state"):
            msg = f"Task failed: {state['error_state']}"
        else:
            msg = f"Task completed successfully. Result: {state.get('final_result')}"
        msg = f"{msg} (Formatter fallback due to LLM error: {str(e)})"

    return {"messages": [AIMessage(content=msg)]}

def route_after_dependency(state: AgentState):
    """Decides where to go after calculating missing parameters."""
    if state.get("error_state"):
        return "response_formatter"

    goal = state["goal_endpoint"]
    meta = REGISTRY[goal]

    # Create operations bypass generic resolver and use the dedicated create workflow
    if meta["category"] == "create":
        return "create_planner"

    if len(state["missing_params"]) > 0:
        return "endpoint_selector"

    if meta.get("destructive") or meta.get("cost_incurring"):
        return "confirmation_gate"
    else:
        return "router_executor"

def route_after_extraction(state: AgentState):
    if state.get("pending_selection"):
        return "selection_node"
    return "state_updater"


# ── Create Workflow Nodes ──────────────────────────────────────────────────────

# Well-known defaults so optional params never bubble up as user questions
_CREATE_DEFAULTS: Dict[str, Any] = {
    "image_name": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
    "gpu_count": 1,
    "container_disk_gb": 20,
    "volume_gb": 20,
    "volume_mount_path": "/workspace",
    "network_volume_id": None,
    "vcpu_count": None,
}

# Preferred resolver order for each api_lookup_param (first available match wins)
_RESOLVER_PRIORITY = {
    "gpu_id": ["get_pod_context", "get_gpu_catalog", "get_provider_gpus", "get_provider_gpu_availability"],
    "datacenter_id": ["get_datacenters"],
    "pod_id": ["get_user_pods"],
    "volume_id": ["get_user_volumes"],
}


def create_planner(state: AgentState) -> Dict[str, Any]:
    """Deterministic planner: api_lookup_params → auto-resolve; known optionals → defaults; only truly required unknowns → user questions."""
    logger.info("create_planner: started for goal=%s", state.get("goal_endpoint"))
    goal = state.get("goal_endpoint", "")
    meta = REGISTRY.get(goal, {})
    user_goal = str(state.get("user_goal") or state["messages"][0].content)
    collected = dict(state.get("collected_params", {}))

    # Strip any user-typed text for params that require API lookup
    api_lookup_params = set(meta.get("api_lookup_params", []))
    for p in list(api_lookup_params):
        if p in collected:
            logger.info("create_planner: stripping api_lookup_param '%s'; will auto-resolve", p)
            del collected[p]

    required_params = meta.get("requires", [])
    all_params = meta.get("query_params", []) + meta.get("body_params", [])

    # ── Step 1: Deterministic pending_auto for api_lookup_params ──────────────
    pending_auto = []
    for param in api_lookup_params:
        if param in collected:
            continue
        priority = _RESOLVER_PRIORITY.get(param, [])
        resolver_id = next(
            (eid for eid in priority if eid in REGISTRY),
            next(
                (eid for eid, m in REGISTRY.items() if param in m.get("resolver_for", [])),
                None,
            ),
        )
        if not resolver_id:
            continue
        resolver_meta = REGISTRY[resolver_id]
        resolver_params = {
            p: collected[p]
            for p in resolver_meta.get("path_params", []) + resolver_meta.get("query_params", [])
            if p in collected
        }
        pending_auto.append({
            "param": param,
            "resolver_endpoint": resolver_id,
            "filter_hint": user_goal,
            "resolver_params": resolver_params,
        })

    # ── Step 2: Well-known defaults for optional params (no user question) ────
    defaults = {
        p: _CREATE_DEFAULTS[p]
        for p in all_params
        if p in _CREATE_DEFAULTS and p not in collected and p not in required_params
    }

    # ── Step 3: LLM generates friendly questions only for missing required params
    missing_required = [
        p for p in required_params
        if p not in collected and p not in api_lookup_params
    ]

    pending_user = []
    if missing_required:
        system_prompt = (
            "You are a GPU orchestration assistant. Generate a short, friendly question for each missing required parameter. "
            "Return ONLY valid JSON: {\"questions\": [{\"param\": str, \"question\": str, \"default\": str_or_null}, ...]}. "
            "For 'name' ask for a short pod/volume name. Keep questions to one sentence."
        )
        try:
            r = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps({
                    "goal_endpoint": goal,
                    "user_goal": user_goal,
                    "missing_params": missing_required,
                }, default=str)),
            ])
            llm_parsed = _safe_json_loads(str(r.content))
            if isinstance(llm_parsed, dict) and isinstance(llm_parsed.get("questions"), list):
                pending_user = [
                    q for q in llm_parsed["questions"]
                    if isinstance(q, dict) and q.get("param") and q.get("question")
                ]
        except Exception:
            logger.exception("create_planner: LLM questions call failed")

        # Fallback if LLM failed or returned nothing
        asked = {q["param"] for q in pending_user}
        for p in missing_required:
            if p not in asked:
                pending_user.append({"param": p, "question": f"Please provide a value for '{p}':", "default": None})

    plan = {"pending_auto": pending_auto, "pending_user": pending_user, "defaults": defaults}
    logger.info(
        "create_planner: pending_auto=%s pending_user=%s defaults_keys=%s",
        [p.get("param") for p in pending_auto],
        [p.get("param") for p in pending_user],
        sorted(list(defaults.keys()))
    )
    return {"create_plan": plan}


def create_api_resolver(state: AgentState) -> Dict[str, Any]:
    """Deterministic: Resolves one param via API; falls back to LLM filter for multiple results."""
    plan = dict(state.get("create_plan") or {})
    pending_auto = list(plan.get("pending_auto", []))
    collected = dict(state.get("collected_params", {}))

    if not pending_auto:
        return {}

    item = pending_auto[0]
    param = item.get("param", "")
    resolver_endpoint = item.get("resolver_endpoint", "")
    filter_hint = item.get("filter_hint", "")
    resolver_params = {**collected, **dict(item.get("resolver_params", {}))}

    logger.info("create_api_resolver: resolving param=%s via %s", param, resolver_endpoint)
    result = _call_endpoint(resolver_endpoint, resolver_params)

    def _move_to_user(question: str):
        pending_auto.pop(0)
        plan["pending_auto"] = pending_auto
        plan.setdefault("pending_user", []).insert(0, {
            "param": param, "question": question, "default": None
        })

    if not result["ok"]:
        logger.warning("create_api_resolver: resolver failed param=%s error=%s", param, result["error"])
        _move_to_user(f"Could not auto-resolve '{param}'. Please provide a value:")
        return {"create_plan": plan}

    data = result["data"]
    list_key = REGISTRY.get(resolver_endpoint, {}).get("response_list_key")
    if list_key and isinstance(data, dict) and list_key in data:
        candidates = data[list_key]
    elif isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = [data]
    else:
        candidates = []

    if not candidates:
        _move_to_user(f"No results found for '{param}'. Please provide a value:")
        return {"create_plan": plan}

    resolved_value = None

    if len(candidates) == 1:
        c = candidates[0]
        resolved_value = c.get(param) if isinstance(c, dict) and param in c else c
        logger.info("create_api_resolver: single result param=%s value=%s", param, resolved_value)
    else:
        # Use LLM to narrow by filter_hint
        filter_system = (
            "You are a parameter resolver for a GPU orchestration agent. "
            "Select the single best candidate matching the filter hint. "
            "Return ONLY JSON: {\"resolved_value\": <value of the '" + param + "' field>, \"found\": true/false, \"explanation\": \"...\"}. "
            "resolved_value must be the value of the '" + param + "' field from the best matching item. "
            "found=false if no item clearly matches."
        )
        filter_input = json.dumps({
            "param": param, "filter_hint": filter_hint,
            "candidates": _summarize_data({"items": candidates}, max_items=30)["items"],
        }, default=str)
        filter_parsed: Optional[Dict[str, Any]] = None
        try:
            r = llm.invoke([SystemMessage(content=filter_system), HumanMessage(content=filter_input)])
            filter_parsed = _safe_json_loads(str(r.content))
        except Exception:
            logger.exception("create_api_resolver: filter LLM failed param=%s", param)

        if isinstance(filter_parsed, dict) and filter_parsed.get("found") and filter_parsed.get("resolved_value") is not None:
            resolved_value = filter_parsed["resolved_value"]
            logger.info("create_api_resolver: LLM filtered param=%s value=%s", param, resolved_value)
        else:
            # Still ambiguous — present numbered list to user
            display_vals = [
                (c.get(param) if isinstance(c, dict) and param in c else str(c))
                for c in candidates[:30]
            ]
            _move_to_user(
                f"Multiple options for '{param}' — please pick one:"
            )
            plan["pending_user"][0]["candidates"] = display_vals
            return {"create_plan": plan}

    pending_auto.pop(0)
    plan["pending_auto"] = pending_auto
    collected[param] = resolved_value
    return {"create_plan": plan, "collected_params": collected}


def create_user_clarifier(state: AgentState) -> Dict[str, Any]:
    """HITL: Captures user's answer to a clarification question; graph pauses before this via interrupt_before."""
    plan = dict(state.get("create_plan") or {})
    pending_user = list(plan.get("pending_user", []))
    collected = dict(state.get("collected_params", {}))

    if not pending_user:
        return {}

    item = pending_user[0]
    param = item.get("param", "")
    default = item.get("default")
    answer = str(state["messages"][-1].content).strip()

    # Accept default if user typed nothing meaningful
    if (not answer or answer.lower() in {"default", "yes", "ok", "sure"}) and default is not None:
        answer = str(default)

    logger.info("create_user_clarifier: param=%s value=%r", param, answer)
    pending_user.pop(0)
    plan["pending_user"] = pending_user
    collected[param] = answer
    return {"create_plan": plan, "collected_params": collected}


def create_payload_builder(state: AgentState) -> Dict[str, Any]:
    """Deterministic: Merges collected params with intelligent defaults into confirmation_payload."""
    logger.info("create_payload_builder: started")
    plan = state.get("create_plan") or {}
    defaults = dict(plan.get("defaults", {}))
    collected = dict(state.get("collected_params", {}))
    payload = {**defaults, **collected}  # collected overrides defaults
    logger.info("create_payload_builder: payload_keys=%s", sorted(list(payload.keys())))
    return {"confirmation_payload": payload}


def create_validator(state: AgentState) -> Dict[str, Any]:
    """Deterministic: Ensures all required params exist before confirmation."""
    logger.info("create_validator: started")
    goal = state.get("goal_endpoint", "")
    required = REGISTRY.get(goal, {}).get("requires", [])
    payload = state.get("confirmation_payload") or {}
    missing = [r for r in required if not payload.get(r)]
    if missing:
        logger.warning("create_validator: missing params=%s", missing)
        return {"error_state": f"Cannot create {goal}: missing required params {missing}"}
    logger.info("create_validator: payload valid")
    return {}

def route_after_router(state: AgentState):
    if state.get("error_state"):
        return "response_formatter"
    if state.get("last_executed_endpoint") == state.get("goal_endpoint"):
        # Creates don't need semantic reasoning — the deployment result IS the answer
        goal_meta = REGISTRY.get(state.get("goal_endpoint") or "", {})
        if goal_meta.get("category") == "create":
            return "response_formatter"
        return "goal_reasoner"
    return "result_extractor"


def route_create_step(state: AgentState) -> str:
    """Routes the create loop: auto-resolve → ask user → build payload."""
    if state.get("error_state"):
        return "response_formatter"
    plan = state.get("create_plan") or {}
    if plan.get("pending_auto"):
        return "create_api_resolver"
    if plan.get("pending_user"):
        return "create_user_clarifier"
    return "create_payload_builder"


def route_create_validator(state: AgentState) -> str:
    if state.get("error_state"):
        return "response_formatter"
    return "confirmation_gate"


# --- Graph Construction ---
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("intent_parser", intent_parser)
workflow.add_node("dependency_resolver", dependency_resolver)
workflow.add_node("endpoint_selector", endpoint_selector)
workflow.add_node("router_executor", router_executor)
workflow.add_node("result_extractor", result_extractor)
workflow.add_node("selection_node", selection_node)
workflow.add_node("state_updater", state_updater)
workflow.add_node("confirmation_gate", confirmation_gate)
workflow.add_node("goal_reasoner", goal_reasoner)
workflow.add_node("response_formatter", response_formatter)
workflow.add_node("create_planner", create_planner)
workflow.add_node("create_api_resolver", create_api_resolver)
workflow.add_node("create_user_clarifier", create_user_clarifier)
workflow.add_node("create_payload_builder", create_payload_builder)
workflow.add_node("create_validator", create_validator)

# Set Entry
workflow.set_entry_point("intent_parser")

# Add Edges
workflow.add_edge("intent_parser", "dependency_resolver")

workflow.add_conditional_edges(
    "dependency_resolver",
    route_after_dependency,
    {
        "endpoint_selector": "endpoint_selector",
        "create_planner": "create_planner",
        "confirmation_gate": "confirmation_gate",
        "router_executor": "router_executor",
        "response_formatter": "response_formatter"
    }
)

workflow.add_edge("endpoint_selector", "router_executor")
workflow.add_conditional_edges(
    "router_executor",
    route_after_router,
    {
        "result_extractor": "result_extractor",
        "goal_reasoner": "goal_reasoner",
        "response_formatter": "response_formatter",
    }
)

workflow.add_edge("goal_reasoner", "response_formatter")

workflow.add_conditional_edges(
    "result_extractor",
    route_after_extraction,
    {
        "selection_node": "selection_node",
        "state_updater": "state_updater"
    }
)

# Read-only loop: selection/update → dependency resolver
workflow.add_edge("selection_node", "state_updater")
workflow.add_edge("state_updater", "dependency_resolver")

# Create workflow loop: planner → resolve/ask → build → validate → confirm → execute
_create_step_edges = {
    "create_api_resolver": "create_api_resolver",
    "create_user_clarifier": "create_user_clarifier",
    "create_payload_builder": "create_payload_builder",
    "response_formatter": "response_formatter",
}
workflow.add_conditional_edges("create_planner", route_create_step, _create_step_edges)
workflow.add_conditional_edges("create_api_resolver", route_create_step, _create_step_edges)
workflow.add_conditional_edges("create_user_clarifier", route_create_step, _create_step_edges)
workflow.add_edge("create_payload_builder", "create_validator")
workflow.add_conditional_edges(
    "create_validator",
    route_create_validator,
    {"confirmation_gate": "confirmation_gate", "response_formatter": "response_formatter"}
)

workflow.add_edge("confirmation_gate", "router_executor")
workflow.add_edge("response_formatter", END)

# --- Compile with HITL Checkpointer ---
memory = MemorySaver()

# The graph will physically pause BEFORE executing these nodes
app = workflow.compile(
    checkpointer=memory,
    interrupt_before=["selection_node", "confirmation_gate", "create_user_clarifier"]
)


if __name__ == "__main__":
    logger.info("CLI started. Type 'exit' to quit.")

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in {"exit", "quit", "q"}:
            logger.info("CLI exiting by user request")
            break
        if not user_input:
            continue

        thread_id = f"showdown-{uuid.uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}

        logger.info("New request thread_id=%s", thread_id)
        result = app.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "collected_params": {},
                "visited_endpoints": [],
                "execution_history": [],
                "iteration_count": 0,
            },
            config=config
        )

        # Resume loop: check graph_state.next to detect real LangGraph interrupts
        while True:
            graph_state = app.get_state(config)
            next_nodes = list(graph_state.next) if graph_state.next else []

            if not next_nodes:
                break

            current_vals = graph_state.values
            logger.info("Graph interrupted at nodes=%s", next_nodes)

            if "selection_node" in next_nodes:
                pending = current_vals.get("pending_selection") or {}
                candidates = pending.get("candidates", [])
                field = pending.get("field", "value")

                print(f"\n[Select {field}] — {len(candidates)} options available:")
                for i, c in enumerate(candidates):
                    if isinstance(c, dict):
                        display = c.get(field) or c.get("name") or c.get("id") or json.dumps(c)
                    else:
                        display = str(c)
                    print(f"  {i + 1}. {display}")

                raw = input(f"\nPick a {field} (number or exact value): ").strip()

                # Resolve numeric pick to actual value
                resume_text = raw
                try:
                    idx = int(raw) - 1
                    if 0 <= idx < len(candidates):
                        c = candidates[idx]
                        resume_text = (
                            c.get(field) if isinstance(c, dict) and field in c
                            else c.get("name") if isinstance(c, dict)
                            else str(c)
                        )
                except (ValueError, TypeError):
                    pass

            elif "create_user_clarifier" in next_nodes:
                plan = current_vals.get("create_plan") or {}
                pending_user = plan.get("pending_user", [])
                if pending_user:
                    item = pending_user[0]
                    question = item.get("question", f"Please provide a value for '{item.get('param', '?')}'")
                    default = item.get("default")
                    candidates = item.get("candidates", [])
                    print(f"\n[Create] {question}")
                    if candidates:
                        for i, c in enumerate(candidates[:30]):
                            print(f"  {i + 1}. {c}")
                    if default is not None:
                        resume_text = input(f"  Your answer [default: {default}]: ").strip() or str(default)
                    else:
                        resume_text = input("  Your answer: ").strip()
                else:
                    resume_text = ""

            elif "confirmation_gate" in next_nodes:
                payload = current_vals.get("confirmation_payload") or current_vals.get("collected_params", {})
                goal = current_vals.get("goal_endpoint", "")
                print(f"\n[Confirm] About to execute: {goal}")
                print(f"  Params: {json.dumps(payload, indent=2, default=str)}")
                resume_text = input("Approve? (yes/no): ").strip() or "no"

            else:
                # Unknown interrupt node — skip to avoid infinite loop
                logger.warning("Unhandled interrupt nodes=%s, skipping resume", next_nodes)
                break

            logger.info("Resuming graph with input=%r", resume_text)
            app.update_state(config, {"messages": [HumanMessage(content=resume_text)]})
            result = app.invoke(None, config=config)

        final_messages = result.get("messages", [])
        if final_messages:
            print(f"\nAssistant: {final_messages[-1].content}")
        else:
            print("\nAssistant: No response message returned.")