import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langgraph.types import interrupt

from langgraph.graph import MessagesState
import nest_asyncio
nest_asyncio.apply()

class State(MessagesState):
    next: str
    input: str
    user_feedback: str

def human_editing(state: State):
    ...
    result = interrupt(
        {
            "task": "Review the output from the LLM and make any necessary edits.",
            "llm_generated_summary": state["llm_generated_summary"]
        }
    )

    return {
        "llm_generated_summary": result["edited_text"] 
    }