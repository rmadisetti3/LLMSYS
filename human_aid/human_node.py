import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langgraph.types import Command
from langgraph.graph import MessagesState
from langgraph.types import interrupt

from typing import Literal

def human_node(
    state: MessagesState, config
) -> Command[Literal["exploration", "xss", "sqli", "human"]]:

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