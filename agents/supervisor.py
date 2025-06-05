import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


from typing import Literal
from typing_extensions import TypedDict

from langgraph.graph import MessagesState, END
from langgraph.types import Command

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

members = ["xss", "sqli"]
options = members + ["FINISH"]

system_prompt = (
    "You are a team supervisor managing different types of cybersecurity expert agents which include: {members}"
    "For SQLi attacks or database, use sqli_agent. "
    "For XSS attacks or general attacks, use xss_agent"
    "Provide only the one specific link which is give without any vague instructions"
    "When finished respond with FINISH."
)


class Router(TypedDict):
    next: Literal[*options]


llm = ChatOpenAI(model="gpt-4o-mini")


class State(MessagesState):
    next: str


def supervisor_node(state: State) -> Command[Literal[*members, "__end__"]]:
    messages = [
        {"role": "system", "content": system_prompt},
    ] + state["messages"]
    response = llm.with_structured_output(Router).invoke(messages)
    goto = response["next"]
    if goto == "FINISH":
        goto = END

    return Command(goto=goto, update={"next": goto})