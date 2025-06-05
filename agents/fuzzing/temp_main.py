import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import MessagesState, END
from langgraph.types import Command
from langgraph.types import interrupt
from langchain_core.messages import HumanMessage, AIMessage

from langgraph.graph import START, StateGraph
from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
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

from tools.handoff_tool import make_handoff_tool

from langchain_openai import ChatOpenAI

from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_handoff_tool, create_swarm

import asyncio

import nest_asyncio
nest_asyncio.apply()

model = ChatOpenAI(model="gpt-4o-mini")

shell_tool = ShellTool()
shell_tool.description = shell_tool.description + f"args {shell_tool.args}".replace("{", "{{").replace("}", "}}")

async_browser = create_async_playwright_browser()
browser_toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=async_browser)
browser_tools = browser_toolkit.get_tools()
all_default_tools = browser_tools + [shell_tool]

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Dict, Optional

class CrawledElement(BaseModel):
    element_type: str = Field(
        ...,
        description="Interactive element type: text_input, password_input, file_upload, submit_button, etc."
    )
    name: Optional[str] = Field(
        None,
        description="HTML name attribute if available"
    )
    selector: str = Field(
        ...,
        description="Full CSS selector path for reliable targeting"
    )
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        description="Key HTML attributes like type, maxlength, etc."
    )

class PageMap(BaseModel):
    target_url: str = Field(
        ...,
        description="Absolute URL of the crawled page"
    )
    elements: List[CrawledElement] = Field(
        ...,
        description="List of interactive elements found"
    )
    form_dependencies: List[str] = Field(
        default_factory=list,
        description="Required hidden fields/tokens like csrf_token"
    )

exploration_prompt = (
    "Analyze ONE target page URL and meticulously map all interactive elements. Follow these steps:\n"
    "1. **Precision Crawling**:\n"
    "   - Use Playwright/Selenium to fully render the page\n"
    "   - Identify all forms, inputs, buttons, and API endpoints\n"
    "   - Record element positions in DOM hierarchy\n"
    "2. **Technical Analysis**:\n"
    "   - Note input types (text, file, hidden), validation patterns, and max lengths\n"
    "   - Detect submission handlers (XHR endpoints, form actions)\n"
    "   - Map dependencies (CSRF tokens, session cookies)\n"
    "3. **Structural Mapping**:\n"
    "   - Create reliable CSS selectors for each element\n"
    "   - Note JavaScript event handlers (onSubmit, onClick)\n"
    "   - Identify framework-specific patterns (React controlled inputs)\n"
    "4. **Output Requirements**:\n"
    "   - Only analyze ONE page - NO recursive crawling\n"
    "   - Prioritize elements accepting user input\n"
    "   - Include technical metadata needed for fuzzing\n"
    "5. **Handoff Protocol**:\n"
    "   - Validate selectors against live DOM before reporting\n"
    "   - Flag elements with client-side validation\n"
    "   - Pass complete page context to fuzzer agent in one batch\n"
    "6. **Error Handling**:\n"
    "   - If page cannot be loaded, return error state with screenshot\n"
    "   - If dynamic elements fail to render, note required interactions\n"
    "\nReport format MUST use a logical schema. No vulnerability speculation - pure technical mapping."
    "Once done transfer the findings to Fuzzer agent. Make sure you put the element tags clearly without any additional element."
    "Verify the findings via human Before transferring them to fuzzer agent."
    "Remember: Do not add additional backslash (\) character to any field tag."
)


fuzz_prompt = """You are Fuzzer Agent.
Your goal: Generate random and mutated payloads that can expose unknown or hidden vulnerabilities.

1. Receive input from ExplorationAgent or other agents (target URLs, form fields, parameter names).
2. For each parameter or field, produce varied payloads:
   - Random ASCII, Unicode extremes, binary data
   - Known injection patterns (quotes, angle brackets, etc.)
   - Encoded variations (URL-encoded, HTML-encoded, Base64, double-encoded)
   - Boundary tests (very short vs. very long inputs, null bytes)
3. If re-queried for the same target, ensure newly generated payloads differ from previously generated ones.

Collaboration Details:
- Primary Output: A structured dataset of fuzz payloads keyed by parameter name or form field.
- After generating, call ExecutionAgent to perform actual injections:
- Club all payloads in a single agent call:
  Example call:
    Call: ExecutionAgent
    Data: {
      "targetUrl": "...",
      "parameterMapping": {
        "param1": ["payload1", "payload2", ...],
        "param2": ["payloadA", "payloadB", ...]
      }
    }
- You may be called again by ExecutionAgent if additional or more specific payloads are needed.
- Do not execute the payloads on your own, delegate the task to the executor agent.
"""

execute_prompt = (  
    "You are a payload execution agent, you will recieve context of the target item from fuzzer agent along with previous attached context of the target field from exploration agent."
    "Strictly follow the below steps:"
    "Your task is to **safely inject fuzz inputs (payloads)** into the target system and **detect novel anomalies**."
    "Follow these steps strictly:\n"  
    "1. **Pre-Injection Validation**:\n"  
    "   - Use the available tools to verify input field/button identifiers (IDs, XPath, CSS selectors) match the target's input field tag\n"  
    "   - The selectors might have an escape character \ which might be because of new line, so remove those completely from the selector tags if you cannot perform your action."
    "   - If identifiers are incorrect, pause and request updated UI context from the exploration agent.\n"  
    "2. **Payload Injection**:\n"  
    "   - For **web apps**: Inject payloads into selected form fields, headers, cookies, or API endpoints using browser automation or direct HTTP requests, only use the items given by the exploration agent.\n"  
    "   - For **CLI tools**: Feed inputs via stdin, arguments, or file uploads (e.g., `./target --input <PAYLOAD>`).\n"  
    "   - For **network protocols**: Replay payloads over raw sockets or protocol-specific clients (e.g., gRPC, MQTT).\n"  
    "3. **Anomaly Detection**:\n"  
    "   - Monitor for:\n"  
    "     - Process crashes (segfaults, exceptions, exit codes ≠ 0).\n"  
    "     - Unusual responses (HTTP 500, garbage output, memory leaks).\n"  
    "     - Resource exhaustion (CPU >90%, OOM kills, hung threads).\n"  
    "     - Silent failures (no response, delayed timeouts >10s).\n"  
    "   - Instrument the target with debugging tools (GDB, ASAN, strace, Wireshark) to capture stack traces, heap state, or network traffic.\n"  
    "4. **Logging & Reporting**:\n"  
    "   - For **crashes**: Log the payload, stack trace, memory dump offset (e.g., `rip=0x41414141`), and OS context (CPU, memory).\n"  
    "   - For **errors**: Record HTTP status codes, error messages, and response body snippets (redact sensitive data).\n"  
    "   - For **successful-but-unexpected behavior**: Flag deviations from baseline (e.g., altered DB state, unexpected redirects).\n"  
    "5. **Feedback Loop**:\n"  
    "   - If a payload fails to execute (e.g., UI element not found), send a structured error to the fuzzer agent with:\n"  
    "     - Failure type (e.g., 'Invalid selector', 'Protocol mismatch').\n"  
    "     - Target context snapshot (e.g., current HTML DOM, API schema).\n"  
    "   - If a payload triggers an anomaly, send:\n"  
    "     - Payload ID, anomaly type, and debug artifacts (logs, PCAPs).\n"  
    "     - A minimal reproducer (simplified payload + steps).\n"  
    "6. **Rules**:\n"  
    "   - Never retry a failed payload unless the fuzzer agent provides a modified version.\n"  
    "   - Prioritize payloads that maximize code coverage (use AFL-like edge counters if available).\n"  
    "Remember: You can ask the fuzzer agent to generate more payload by directing a query to the fuzzer agent."

    "Response format:\n"  
    "{\n"  
    "  'status': 'success' | 'crash' | 'error' | 'retry',\n"  
    "  'payload_id': 'uuid',\n"  
    "  'observations': {'type': 'heap_overflow', 'offset': '0xdeadbeef', ...},\n"  
    "  'next_action': 'proceed' | 'halt' | 'refine_payload'\n"  
    "}"  
)  

exploration_agent = create_react_agent(
    model=model,
    tools=browser_tools + [make_handoff_tool(agent_name="fuzzer")] + [make_handoff_tool(agent_name="executor")],
    name="exploration",
    prompt=exploration_prompt,
    # response_format=PageMap
)

fuzz_agent = create_react_agent(
    model=model,
    tools= [make_handoff_tool(agent_name="exploration")] + [make_handoff_tool(agent_name="executor")],
    name="fuzzer",
    prompt=fuzz_prompt
)

executor_agent = create_react_agent(
    model=model,
    tools=all_default_tools + [make_handoff_tool(agent_name="exploration")] + [make_handoff_tool(agent_name="fuzzer")] + [make_handoff_tool(agent_name="executor")],
    name="executor",
    prompt=execute_prompt
)

async def exploration_node(state: MessagesState) -> Command[Literal["exploration", "fuzzer", "human", "executor"]]:
    result = await exploration_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="exploration")
            ]
        },
        goto="human",
    )

async def fuzz_agent_node(state: MessagesState) -> Command[Literal["exploration", "fuzzer", "human", "executor"]]:
    result = await fuzz_agent.ainvoke(state)
    final_message = result["messages"][-1].content

    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="fuzzer")
            ]
        },
        goto="human",
    )

async def fuzz_executor_node(state: MessagesState) -> Command[Literal["exploration", "fuzzer", "human", "executor"]]:
    result = await executor_agent.ainvoke(state)
    final_message = result["messages"][-1].content

    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="executor")
            ]
        },
        goto="human",
    )

def human_node(
    state: MessagesState, config
) -> Command[Literal["exploration", "fuzzer", "human", "executor"]]:

    user_input = interrupt(value="Ready for user input.")

    langgraph_triggers = config["metadata"]["langgraph_triggers"]
    if len(langgraph_triggers) != 1:
        raise AssertionError("Expected exactly 1 trigger in human node")

    active_agent = langgraph_triggers[0].split(":")[1]

    return Command(
        update={
            "messages": [
                {
                    "role": "human",
                    "content": user_input,
                }
            ]
        },
        goto=active_agent,
    )

checkpointer = InMemorySaver()

class State(TypedDict):
    messages: Annotated[List[dict], add_messages]

builder = StateGraph(State)
builder.add_edge(START, "exploration")
builder.add_node("exploration", exploration_node)
builder.add_node("human", human_node)
builder.add_node("executor", fuzz_executor_node)
builder.add_node("fuzzer", fuzz_agent_node)

graph = builder.compile(checkpointer=checkpointer)

thread_config = {"configurable": {"thread_id": "12"}}

async def run_astream(graph, thread_config):
    stream_message = {"messages": [("human", "http://testphp.vulnweb.com/guestbook.php")]}

    while True:
        command_required = False
        async for update in graph.astream(
            stream_message, 
            config=thread_config, 
            stream_mode="updates",
            subgraphs=True
        ):
            print(update)
            print()

            if not isinstance(update, dict):
                continue

            for node_id, value in update.items():
                if node_id == "__interrupt__":
                    command_required = True
                    continue

                # if isinstance(value, dict) and value.get("messages", []):
                #     last_message = value["messages"][-1]
                #     if not isinstance(last_message, dict):
                #         print(f"{node_id}: {last_message.content}")

        if command_required:
            user_input = input("Please enter an input: ")
            stream_message = Command(resume=user_input)
        else:
            user_input = input("Worflow has ended! Enter a new command to begin again: ")
            stream_message = {"messages": HumanMessage(user_input)}

asyncio.run(run_astream(graph, thread_config))
