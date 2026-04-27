"""ChatService: builds legislative-analyst system prompt and delegates to LLMClient."""

from app.chat.llm import LLMClient

_SYSTEM_PROMPT = """\
You are an expert non-partisan Legislative Analyst. \
Answer questions about the bill below based solely on its text. \
Cite the specific section or provision for every claim. \
If the bill does not address a topic, state: \
"The provided text does not cover this topic." \
Use plain English and neutral tone.

BILL TEXT:
{bill_text}\
"""


class ChatService:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def chat(self, bill_text: str, messages: list[dict]) -> str:
        """Build system prompt from bill text and call the LLM with conversation messages."""
        system = _SYSTEM_PROMPT.format(bill_text=bill_text)
        return self.llm.complete(system=system, messages=messages)
