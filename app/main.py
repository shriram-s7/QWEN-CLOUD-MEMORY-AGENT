"""
MemoryAgent - FastAPI backend.

Endpoints:
  POST /chat            -> send a message, get a reply informed by recalled memories
  GET  /memories/{uid}  -> inspect all stored memories for a user (debug/demo)
  DELETE /memories/{id} -> manually forget a specific memory
  POST /maintenance/decay -> trigger confidence decay + forgetting sweep

Run:
  export QWEN_API_KEY=your_key
  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.memory import MemoryStore
from app.qwen_client import chat_with_memory

app = FastAPI(title="MemoryAgent", version="1.0.0")
store = MemoryStore()

# very small in-process session cache: user_id -> list of {role, content}
# (kept short so it doesn't defeat the purpose of the persistent memory layer)
_SESSION_HISTORY = {}
MAX_TURNS_IN_CONTEXT = 4


class ChatRequest(BaseModel):
    user_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    recalled_memories: List[str]
    new_memory_stored: Optional[str] = None


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    # lightweight forgetting sweep on session start (cheap, keeps store small)
    store.decay_and_forget(user_id=req.user_id)

    recalled = store.recall(req.user_id, req.message, top_k=5)
    recalled_texts = [m.content for m in recalled]

    history = _SESSION_HISTORY.get(req.user_id, [])

    result = chat_with_memory(req.message, recalled_texts, history)

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": result["reply"]})
    _SESSION_HISTORY[req.user_id] = history[-(MAX_TURNS_IN_CONTEXT * 2):]

    stored = None
    if result["new_memory"]:
        store.add_memory(req.user_id, result["new_memory"], category="preference")
        stored = result["new_memory"]

    return ChatResponse(
        reply=result["reply"],
        recalled_memories=recalled_texts,
        new_memory_stored=stored,
    )


@app.get("/memories/{user_id}")
def list_memories(user_id: str):
    memories = store.all_memories(user_id)
    return [
        {
            "id": m.id,
            "content": m.content,
            "category": m.category,
            "confidence": round(m.confidence, 3),
            "access_count": m.access_count,
        }
        for m in memories
    ]


@app.delete("/memories/{mem_id}")
def delete_memory(mem_id: int):
    store.forget(mem_id)
    return {"status": "deleted", "id": mem_id}


@app.post("/maintenance/decay")
def run_decay():
    deleted = store.decay_and_forget()
    return {"status": "ok", "deleted": deleted}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Static frontend ────────────────────────────────────────────────────────
# Mounted AFTER all API routes so that /chat, /memories, /health, etc.
# are matched first, and only unmatched paths fall through to the SPA.
from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/", StaticFiles(directory="static", html=True), name="static")
