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

sqli_prompt = '''You are an expert in SQL Injection. 
Scan https://www.cve.org/CVERecord/SearchResults?query=sqli and learn the description and references of all entries to apply in the next step.
You will be given information such as an URL, description and recommended testing. Use Playwright and terminal tools to:  
1. Test SQLi payloads (e.g., `' OR 1=1--`, `" UNION SELECT null,version()--`) in login forms, search bars, and URL parameters.  
2. Check for database errors, unexpected responses, or data leaks.  
3. Escalate with time-based payloads (e.g., `'; IF (1=1) WAITFOR DELAY '0:0:5'--`).  
4. Report vulnerable endpoints and extracted data.'''

model=ChatOpenAI(model="gpt-4o-mini")

new_tools = browser_tools + [make_handoff_tool(agent_name="xss")] + [make_handoff_tool(agent_name="supervisor")]

sqli_agent = create_react_agent(
    model=model,
    tools=new_tools,
    name="sqli_expert",
    prompt=sqli_prompt
)

async def sqli_agent_node(state: State) -> Command[Literal["supervisor", "xss", "human"]]:
    result = await sqli_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    return Command(
        update={
            "messages": [
                HumanMessage(content=final_message, name="sqli")
            ]
        },
        goto="human",
    )