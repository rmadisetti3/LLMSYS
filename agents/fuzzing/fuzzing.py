import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain_community.tools import ShellTool
from tools.playwright_toolkit.custom_playwright_toolkit import PlayWrightBrowserToolkit
from langchain_community.tools.playwright.utils import create_async_playwright_browser

from typing import Literal

from langgraph.graph import MessagesState
from langgraph.types import Command
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from tools.handoff_tool import make_handoff_tool

import nest_asyncio
nest_asyncio.apply()

class State(MessagesState):
    next: str

shell_tool = ShellTool()
shell_tool.description = shell_tool.description + f"args {shell_tool.args}".replace("{", "{{").replace("}", "}}")

async_browser = create_async_playwright_browser()
browser_toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=async_browser)
browser_tools = browser_toolkit.get_tools()
all_default_tools = browser_tools + [shell_tool]

fuzz_prompt = '''You are an advanced fuzzing agent. 
Your goal is to discover unknown or hidden vulnerabilities by generating novel or random payloads. 
You will receive URLs, forms, or parameter names. 
Steps:
1. Generate random or mutated payloads (including unusual characters, encodings, or lengths).
2. Inject these payloads into any discovered input (forms, query params, headers).
3. Monitor for unexpected responses, errors, or unusual behavior.
4. Report any possible vulnerabilities or anomalies.'''

model = ChatOpenAI(model="gpt-4o-mini")

fuzz_agent = create_react_agent(
    model=model,
    tools=all_default_tools,
    name="fuzz_expert",
    prompt=fuzz_prompt
)

async def fuzz_agent_node(state: State) -> Command[Literal["supervisor", "xss", "human"]]:
    result = await fuzz_agent.ainvoke(state)
    final_message = result["messages"][-1].content

    return Command(
        update={
            "messages": [
                HumanMessage(content=final_message, name="fuzzer")
            ]
        },
        goto="human",
    )
