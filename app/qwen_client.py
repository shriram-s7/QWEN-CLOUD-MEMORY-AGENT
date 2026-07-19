"""
Thin wrapper around Qwen Cloud's OpenAI-compatible chat completion endpoint.

Base URL: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
Docs: https://bit.ly/qwencloud-first-api
"""

import os
from openai import OpenAI

QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")


def get_client() -> OpenAI:
    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "QWEN_API_KEY is not set. Export it before starting the server: "
            "export QWEN_API_KEY=your_key_here"
        )
    return OpenAI(api_key=api_key, base_url=QWEN_BASE_URL)


# A single extraction call also asks the model to flag any durable
# preference/fact worth remembering, so we don't need a second round trip.
EXTRACTION_INSTRUCTIONS = (
    "After your reply, on a new line starting with 'MEMORY:' write a short "
    "third-person fact worth remembering long-term about the user's stable "
    "preferences (e.g. 'MEMORY: User prefers concise, no-fluff answers.'). "
    "Only include it if the message actually reveals a durable preference "
    "or fact. If nothing is worth remembering, write 'MEMORY: none'."
)


def chat_with_memory(user_message: str, recalled_memories: list, history: list) -> dict:
    """
    Sends a chat turn to Qwen with recalled memories injected as context.
    Returns {"reply": str, "new_memory": str | None}.
    """
    client = get_client()

    memory_context = (
        "\n".join(f"- {m}" for m in recalled_memories)
        if recalled_memories
        else "(no relevant memories yet)"
    )

    system_prompt = (
        "You are a helpful personal assistant with persistent memory across "
        "sessions. Use the following remembered facts about this user when "
        "relevant, but don't force them in if irrelevant.\n\n"
        f"Remembered facts:\n{memory_context}\n\n{EXTRACTION_INSTRUCTIONS}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=QWEN_MODEL,
        messages=messages,
        temperature=0.7,
    )

    raw = response.choices[0].message.content or ""

    reply = raw
    new_memory = None
    if "MEMORY:" in raw:
        reply, mem_part = raw.split("MEMORY:", 1)
        reply = reply.strip()
        mem_part = mem_part.strip()
        if mem_part and mem_part.lower() != "none":
            new_memory = mem_part

    return {"reply": reply, "new_memory": new_memory}
