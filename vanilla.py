import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from typing import Literal

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import MessagesState, END, START, StateGraph
from langgraph.types import Command, interrupt
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from langchain_community.tools import ShellTool
# from langchain_community.agent_toolkits import PlayWrightBrowserToolkit
from tools.playwright_toolkit.custom_playwright_toolkit import PlayWrightBrowserToolkit
# from langchain_community.tools.playwright.utils import create_async_playwright_browser
from tools.playwright_toolkit.browser_session import get_browser_with_auto_state

from tools.handoff_tool import make_handoff_tool
from tools.get_image_tool import get_random_image

from vanilla_test.prompts.executor_prompt import executor_prompt
from vanilla_test.prompts.fuzzer_prompt import fuzzer_prompt
from vanilla_test.prompts.exploration_prompt import exploration_prompt
from vanilla_test.prompts.sqli_prompt import sqli_prompt
from vanilla_test.prompts.xss_prompt import xss_prompt

import asyncio
import nest_asyncio
nest_asyncio.apply()

model = ChatOpenAI(model="gpt-4o-mini")

shell_tool = ShellTool()
shell_tool.description = shell_tool.description + f"args {shell_tool.args}".replace("{", "{{").replace("}", "}}")

user_data_dir = "/Users/rajma/CS6727/LLMVULN/browser_session_state"
# async_browser = create_async_playwright_browser()
async_browser, context = asyncio.run(get_browser_with_auto_state(user_data_dir))

browser_toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=async_browser)
browser_tools = browser_toolkit.get_tools()
all_default_tools = browser_tools + [shell_tool]

exploration_agent = create_react_agent(
    model=model,
    tools=all_default_tools + [make_handoff_tool(agent_name="fuzzer")] + [make_handoff_tool(agent_name="executor")] + [make_handoff_tool(agent_name="xss")] + [make_handoff_tool(agent_name="sqli")] + [make_handoff_tool(agent_name="csrf")],
    name="exploration",
    prompt=exploration_prompt,
)

fuzz_agent = create_react_agent(
    model=model,
    tools= [make_handoff_tool(agent_name="exploration")] + [make_handoff_tool(agent_name="executor")],
    name="fuzzer",
    prompt=fuzzer_prompt
)

executor_agent = create_react_agent(
    model=model,
    tools=all_default_tools + [get_random_image] + [make_handoff_tool(agent_name="exploration")] + [make_handoff_tool(agent_name="fuzzer")],
    name="executor",
    prompt=executor_prompt
)

sqli_agent = create_react_agent(
    model=model,
    tools=all_default_tools + [make_handoff_tool(agent_name="xss")] + [make_handoff_tool(agent_name="exploration")] + [make_handoff_tool(agent_name="csrf")],
    name="sqli",
    prompt=sqli_prompt,
)

xss_agent = create_react_agent(
    model=model,
    tools=all_default_tools + [make_handoff_tool(agent_name="sqli")] + [make_handoff_tool(agent_name="exploration")] + [make_handoff_tool(agent_name="csrf")],
    name="xss",
    prompt=xss_prompt,
)

def get_next_node(last_message: BaseMessage, goto: str):
    if "FINAL ANSWER" in last_message.content:
        return END
    return goto

async def exploration_node(state: MessagesState) -> Command[Literal["exploration", "fuzzer", "executor", "xss", "sqli"]]:
    result = await exploration_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    goto = get_next_node(result["messages"][-1], "fuzzer")
    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="exploration")
            ]
        },
        goto=goto,
    )

async def fuzz_agent_node(state: MessagesState) -> Command[Literal["exploration", "fuzzer", "executor"]]:
    result = await fuzz_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    goto = get_next_node(result["messages"][-1], "executor")
    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="fuzzer")
            ]
        },
        goto=goto,
    )

async def fuzz_executor_node(state: MessagesState) -> Command[Literal["exploration", "fuzzer", "executor"]]:
    result = await executor_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    goto = get_next_node(result["messages"][-1], "fuzzer")
    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="executor")
            ]
        },
        goto=goto,
    )

async def sqli_agent_node(state: MessagesState) -> Command[Literal["exploration", "xss", "sqli"]]:
    result = await exploration_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    goto = get_next_node(result["messages"][-1], "exploration")
    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="sqli")
            ]
        },
        goto=goto,
    )

async def xss_agent_node(state: MessagesState) -> Command[Literal["exploration", "xss", "sqli"]]:
    result = await exploration_agent.ainvoke(state)
    final_message = result["messages"][-1].content
    goto = get_next_node(result["messages"][-1], "exploration")
    return Command(
        update={
            "messages": [
                AIMessage(content=final_message, name="xss")
            ]
        },
        goto=goto,
    )

checkpointer = MemorySaver()

builder = StateGraph(MessagesState)
builder.add_edge(START, "exploration")
builder.add_node("exploration", exploration_node)
builder.add_node("executor", fuzz_executor_node)
builder.add_node("fuzzer", fuzz_agent_node)
builder.add_node("sqli", sqli_agent_node)
builder.add_node("xss", xss_agent_node)


graph = builder.compile(checkpointer=checkpointer)

thread_config = {"configurable": {"thread_id": "vanilla"}}

async def main():
    count = 0
    async for s in graph.astream(
        {
            "messages": [
                ("human", "http://testphp.vulnweb.com/"),
            ]
        },
        config = thread_config,
    ):
        print(s)
        count +=1
        print("---")
        print(f"Steps completed: {count}")

if __name__ == "__main__":
    asyncio.run(main())
