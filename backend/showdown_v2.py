from tkinter import Image
from typing import TypedDict, List, Dict, Any, Optional, Set, Annotated
import operator
import json
import re
import logging
import typing
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


