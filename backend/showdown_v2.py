from tkinter import Image
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
import pydantic
import requests
import logging
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os
from rich import print
from prompts.showdown_v2 import endpoint_selection_prompt, router_to_endpoint_prompt
from prompts.registry import REGISTRY

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


# --- Mock Metadata Registry ---
# In production, this would be loaded from your FastAPI connector definitions.
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8001")


class EndpointSelectionSchema(pydantic.BaseModel):
    final_key: Annotated[str, pydantic.Field(description="The final key selected based on the user's input and the LLM's reasoning.")]
    reasoning: Annotated[str, pydantic.Field(description="The reasoning behind the selection of the final key, explaining why it was chosen over other options, by max 5 to 10 words")]

class MainState(pydantic.BaseModel):
    """
    The main state of the showdown graph.
    """
    user_input: Annotated[Optional[str], pydantic.Field(description="The raw input provided by the user.")] = None
    endpoint_selection: Optional[EndpointSelectionSchema] = None
    total_endpoint_params: Annotated[Optional[List[str]], pydantic.Field(description="The parameters required for the selected endpoint, if any.")] = None
    available_params: Annotated[Optional[List[str]], pydantic.Field(description="The list of parameters that are available for the selected endpoint.")] = None
    endpoint_hit_flow: Annotated[Optional[List[str]], pydantic.Field(description="The flow of keys that lead to the selected endpoint, if reachable.")] = None
    current_endpoint_doc: Annotated[Optional[Dict[str, Any]], pydantic.Field(description="The documentation of the current endpoint being processed.")] = None
    
def take_user(state: MainState) -> MainState:
    """
    Update the state with the user's input.
    """
    state.user_input = input("Enter your input: ")
    return state

def endpoint_selection(state: MainState):
    """
    Use the LLM to select the appropriate endpoint based on the user's input.
    """
    endpoints = []
    for key, value in REGISTRY.items():
        endpoints.append(f"{key}: {value['description']}")
    prompt = endpoint_selection_prompt.format(endpoints=endpoints, user_query=state.user_input)
    _structured_model = llm.with_structured_output(EndpointSelectionSchema)
    response = _structured_model.invoke(prompt)
    print(f"LLM Response: {response}")
    state.endpoint_selection = response
    return state

def params_decision_taker(state: MainState) -> MainState:
    """
    Placeholder for the next step in the graph where parameters would be decided based on the selected endpoint.
    """
    key = state.endpoint_selection.final_key if state.endpoint_selection else None
    if key is None:
        print("No endpoint selected. Exiting.")
        return state
    
    key_info = REGISTRY.get(key)
    params_needed = key_info.get("requires", []) if key_info else []
    if len(params_needed) > 0:
        print(f"Parameters needed for {key}: {params_needed}")
        state.total_endpoint_params = params_needed
    else:
        print(f"No parameters needed for {key}.")
        state.total_endpoint_params = []

    return state

def router_to_endpoint(state: MainState) -> MainState:
    """
    Placeholder for routing to the selected endpoint.
    """
    params = state.total_endpoint_params if state.total_endpoint_params else []
    params_we_have = state.available_params if state.available_params else []
    endpoints = {}
    for key, value in REGISTRY.items():
        endpoints[key] = {
            "description": value["description"],
            "requires": value.get("requires", []),
            "produces": value.get("produces", [])
        }
    prompt = router_to_endpoint_prompt.format(
        user_input=state.user_input,
        endpoint_selected=state.endpoint_selection.final_key if state.endpoint_selection else "None",
        params_needed=params,
        endpoints=endpoints
    )
    class FlowSchema(pydantic.BaseModel):
        flow: Annotated[List[str], pydantic.Field(description="The flow of keys leading to the selected endpoint.")]
        
    _structured_model = llm.with_structured_output(FlowSchema)
    response = _structured_model.invoke(prompt)
    print(f"Router to Endpoint LLM Response: {response}")
    
    state.endpoint_hit_flow = response.flow
    return state

# def hit_api_for_resolver(state: MainState) -> MainState:
#     dict_info = state.current_endpoint_doc if state.current_endpoint_doc else {}
#     if dict_info:
#         url = urllib.parse.urljoin(FASTAPI_BASE_URL, dict_info.get("path", ""))
#         params = 

    
def runner_flow(state: MainState) -> MainState:
    """
    Placeholder for executing the flow to reach the selected endpoint.
    """
    endpoint_flow = state.endpoint_hit_flow if state.endpoint_hit_flow else []
    if not endpoint_flow:
        print("No flow to execute. Exiting.")
        return state
    for endpoint in endpoint_flow:
        print(f"Executing endpoint: {endpoint}")
        # Here you would add the logic to actually call the endpoint.



graph = StateGraph(MainState)
from langgraph.graph import START, END


# Adding nodes to the graph
graph.add_node("take_user", take_user)
graph.add_node("endpoint_selection", endpoint_selection)
graph.add_node("params_decision_taker", params_decision_taker)
graph.add_node("router_to_endpoint", router_to_endpoint)
# Adding edges
graph.add_edge(START, "take_user")
graph.add_edge("take_user", "endpoint_selection")
graph.add_edge("endpoint_selection", "params_decision_taker")
graph.add_edge("params_decision_taker", "router_to_endpoint")
graph.add_edge("router_to_endpoint", END)

app = graph.compile()

if __name__ == "__main__":
    logger.info("Showdown v2 CLI started. Type 'exit' to quit.")
    state = MainState(endpoint_selection=None)
    output = app.invoke(state)
    print(output)