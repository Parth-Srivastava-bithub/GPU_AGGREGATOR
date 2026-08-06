from tkinter import Image
from typing import TypedDict, List, Dict, Any, Optional, Set, Annotated
import operator
import json
import re
import logging
from urllib import response
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
from prompts.showdown_v2 import endpoint_selection_prompt, router_to_endpoint_prompt, provider_selection_prompt
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

class Context(pydantic.BaseModel):
    gpus: Annotated[List[Dict[str, Any]], pydantic.Field(description="List of available GPUs with their specifications.")]
    top_k_gpus_matched: Annotated[List[Dict[str, Any]], pydantic.Field(description="List of top K GPUs that match the user's requirements.")]
    datacenters: Annotated[List[Dict[str, Any]], pydantic.Field(description="List of available datacenters with their specifications.")]
    datacenters_matched: Annotated[List[Dict[str, Any]], pydantic.Field(description="List of datacenters that match the user's requirements.")]
    

class MainState(pydantic.BaseModel):
    """
    The main state of the showdown graph.
    """
    user_input: Annotated[Optional[List[str]], pydantic.Field(description="The raw input provided by the user.")] = []
    endpoint_selection: Optional[EndpointSelectionSchema] = None
    total_endpoint_params: Annotated[Optional[List[str]], pydantic.Field(description="The parameters required for the selected endpoint, if any.")] = None
    available_params: Annotated[Optional[List[str]], pydantic.Field(description="The list of parameters that are available for the selected endpoint.")] = None
    endpoint_hit_flow: Annotated[Optional[List[str]], pydantic.Field(description="The flow of keys that lead to the selected endpoint, if reachable.")] = None
    current_endpoint_doc: Annotated[Optional[Dict[str, Any]], pydantic.Field(description="The documentation of the current endpoint being processed.")] = None
    provider: Annotated[Optional[str], pydantic.Field(description="The provider selected for the endpoint, if any.")] = None
    full_context: Annotated[Optional[Dict[str, Any]], pydantic.Field(description="The full context retrieved from the provider's API, if any.")] = None
    
def take_user(state: MainState) -> MainState:
    """
    Update the state with the user's input.
    """
    user_input = input("Enter your input: ")
    state.user_input.append(user_input)
    return state

def choosing_provider(state: MainState) -> MainState:
    class _ProviderSelectionSchema(pydantic.BaseModel):
        provider: Annotated[str, pydantic.Field(description="The provider selected for the endpoint.")]
    
    prompt = provider_selection_prompt.format(user_input=state.user_input[-1])
    _structured_llm = llm.with_structured_output(_ProviderSelectionSchema)
    response = _structured_llm.invoke(prompt)
    state.provider = response.provider
    return state

def hit_context_api(state: MainState) -> Dict[str, Any]:
    endpoint = f"/{state.provider.lower()}/context"
    url = f"{FASTAPI_BASE_URL}{endpoint}"
    response = requests.get(url)
    try:
        response.raise_for_status()
        output = response.json()
        state.full_context = output
        return state
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching context from {url}: {e}")
        return state



graph = StateGraph(MainState)
from langgraph.graph import START, END


# Adding nodes to the graph
graph.add_node("take_user", take_user)
graph.add_node("choosing_provider", choosing_provider)
graph.add_node("hit_context_api", hit_context_api)

graph.add_edge(START, "take_user")
graph.add_edge("take_user", "choosing_provider")
graph.add_edge("choosing_provider", "hit_context_api")
graph.add_edge("hit_context_api", END)

app = graph.compile()

if __name__ == "__main__":
    logger.info("Showdown v2 CLI started. Type 'exit' to quit.")
    state = MainState()
    output = app.invoke(state)
    print(output)