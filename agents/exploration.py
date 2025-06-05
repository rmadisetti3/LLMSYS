import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import MessagesState, END
from langgraph.types import Command
from langchain_core.messages import HumanMessage

from typing import Literal
from typing import List, Optional
from pydantic import BaseModel, Field

from dotenv import load_dotenv
load_dotenv()

from langchain_community.tools import ShellTool
# from langchain_community.agent_toolkits import PlayWrightBrowserToolkit
from tools.playwright_toolkit.custom_playwright_toolkit import PlayWrightBrowserToolkit
from langchain_community.tools.playwright.utils import create_async_playwright_browser

import nest_asyncio
nest_asyncio.apply()

model = ChatOpenAI(model="gpt-4o-mini")

shell_tool = ShellTool()
shell_tool.description = shell_tool.description + f"args {shell_tool.args}".replace("{", "{{").replace("}", "}}")

async_browser = create_async_playwright_browser()
browser_toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=async_browser)
browser_tools = browser_toolkit.get_tools()
all_default_tools = browser_tools + [shell_tool]

prompt = '''You are a website exploration agent focused on mapping interactive elements. For EACH INTERNAL PAGE (same domain only):

1. Execution sequence per page:
   a. navigate_to(full_url)
   b. extract_hyperlinks(absolute_urls=True, same_domain_only=True)
   c. get_page_content()
   
2. Element testing priority:
   - <input> fields (all types)
   - <form> elements
   - <textarea> elements
   - <select> dropdowns
   - Clickable elements with [onclick] handlers
   - <a> tags with JavaScript navigation

3. For each target element:
   a. click_element(css_selector)
   b. extract_text(response_content)
   c. Record:
      - Element type
      - Attributes (name, id, type)
      - Associated form validation
      - Network requests triggered
      - Sensitive parameter patterns

4. Required output format per page:
   Page: [full_url]
   Elements: 
   - [element_type] | Selector: [css_path] | Attributes: [name:id:type]
     - Parameters: [observed_parameters]
     - Security Notes: [autocomplete, password_visibility, error_messages]
   Links: [list_of_internal_urls_found]

Never analyze external domains. Focus on element discovery, not vulnerability classification.'''

class PotentialVulnerabilityItem(BaseModel):
    absolute_url: str = Field(
        ...,
        description="The unique URL of the page or endpoint where a potential vulnerability is suspected."
    )
    suspicion_type: str = Field(
        ...,
        description=(
            "A short label describing the nature of the potential vulnerability. "
            "For example: 'Unvalidated Input', 'Suspicious Error Response', 'Unusual Parameter Handling', etc."
        )
    )
    confidence_level: str = Field(
        ...,
        description=(
            "Your internal rating of how likely this is to be a serious issue. "
            "Can be something like 'Low', 'Medium', 'High', or numeric."
        )
    )
    description: Optional[str] = Field(
        None,
        description=(
            "Additional details explaining what led you to suspect a vulnerability. "
            "E.g., unusual server error patterns, partial sanitization, or unclear input validation steps."
        )
    )
    parameters_or_inputs: Optional[List[str]] = Field(
        default_factory=list,
        description=(
            "List of parameters or input fields that could be implicated in the potential vulnerability. "
            "For instance, ['search_query', 'username_field', 'file_upload']. "
            "Useful for later targeted testing."
        )
    )
    evidence: Optional[str] = Field(
        None,
        description=(
            "Any raw data, payload, or response snippet that supports the suspicion. "
            "This can be used later when attempting to replicate or confirm the issue."
        )
    )
    recommended_further_testing: Optional[str] = Field(
        None,
        description=(
            "Optional guidance or placeholder describing how you plan to investigate further. "
            "For example, 'Attempt fuzzing with special characters', 'Check server logs for anomalies', etc."
        )
    )

class PotentialVulnerabilityReport(BaseModel):
    items: List[PotentialVulnerabilityItem] = Field(
        ...,
        description="A list of all identified potential vulnerabilities or suspicious indicators."
    )


class State(MessagesState):
    next: str

exploration_agent = create_react_agent(
    model=model,
    tools=all_default_tools,
    name="exploration_agent",
    prompt=prompt,
    response_format=PotentialVulnerabilityReport
)

async def exploration_node(state: State) -> Command[Literal["supervisor"]]:
    result = await exploration_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    return Command(
        update={
            "messages": [
                HumanMessage(content=final_message, name="exploration")
            ]
        },
        goto="supervisor",
    )
