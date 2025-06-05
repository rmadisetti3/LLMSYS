import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langgraph.graph import START, END, StateGraph
from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
import asyncio

from agents.exploration import exploration_node
from agents.supervisor import supervisor_node
from agents.task_agents.sqli import sqli_agent_node
from agents.task_agents.xss import xss_agent_node

class State(TypedDict):
    messages: Annotated[List[dict], add_messages]

builder = StateGraph(State)
builder.add_edge(START, "exploration")
builder.add_node("exploration", exploration_node)
builder.add_node("supervisor", supervisor_node)
builder.add_node("xss", xss_agent_node)
builder.add_node("sqli", sqli_agent_node)
graph = builder.compile()

async def run_astream():
    async for s in graph.astream({"messages": [("human", "http://testphp.vulnweb.com")]}, subgraphs=True):
        print(s)
        print("----")

asyncio.run(run_astream())
