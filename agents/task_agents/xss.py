import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


from langchain_community.tools import ShellTool
from tools.playwright_toolkit.custom_playwright_toolkit import PlayWrightBrowserToolkit
from langchain_community.tools.playwright.utils import create_async_playwright_browser
from typing import Literal

from langgraph.graph import MessagesState, END
from langgraph.types import Command
from langchain_core.messages import HumanMessage

from tools.handoff_tool import make_handoff_tool

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
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

xss_prompt = '''You are an expert in Cross-Site Scripting (XSS). Scan https://www.cve.org/CVERecord/SearchResults?query=xss and learn the description and references of all entries to apply in the next step.
You will be given information such as an URL, description and recommended testing. Utilise Playwright and terminal tools to:  
1. Identify all user-input fields (e.g., search bars, comment forms).  
2. Test payloads like `<script>alert('XSS')</script>` or `<img src=x onerror=alert(1)>` or generate custom payload based on recommendations or your knowledge.  
3. Check if scripts execute (e.g., pop-up alerts, DOM changes).  
4. Report successful payloads and affected pages.  
Do not use external tools; focus on manual injection.'''

model=ChatOpenAI(model="gpt-4o-mini")

new_tools = browser_tools + [make_handoff_tool(agent_name="sqli")] + [make_handoff_tool(agent_name="supervisor")]

xss_agent = create_react_agent(
    model=model,
    tools=new_tools,
    name="xss_expert",
    prompt=xss_prompt
)

async def xss_agent_node(state: State) -> Command[Literal["supervisor", "sqli", "human"]]:
    result = await xss_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    return Command(
        update={
            "messages": [
                HumanMessage(content=final_message, name="xss")
            ]
        },
        goto="human",
    )