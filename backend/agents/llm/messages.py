"""The single seam between LangChain message lists and the CLI backends.

HTTP backends consume `list[BaseMessage]` natively; the CLI backends need a
`(system_str, user_str)` pair, so this is the ONLY place that flattens.
"""
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage


def _as_text(content) -> str:
    return content if isinstance(content, str) else str(content)


def flatten_messages(messages: list[BaseMessage]) -> tuple[str, str]:
    """Split a message list into (system_str, user_str).

    All SystemMessages are concatenated into system_str. The remaining
    Human/AI turns are rendered as a labeled transcript into user_str, with the
    trailing Human message last (natural for a single-shot CLI prompt).
    """
    system_parts: list[str] = []
    transcript: list[str] = []
    for m in messages:
        text = _as_text(m.content)
        if isinstance(m, SystemMessage):
            system_parts.append(text)
        elif isinstance(m, AIMessage):
            transcript.append(f"Assistant: {text}")
        else:  # HumanMessage (or any other) is treated as user input
            transcript.append(f"Human: {text}")
    return "\n\n".join(system_parts), "\n\n".join(transcript)
