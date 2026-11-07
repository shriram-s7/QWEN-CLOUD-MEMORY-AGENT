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

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import List, Optional

from app.memory import MemoryStore
from app.qwen_client import (
    chat_with_memory,
    get_provider_and_model,
    set_runtime_provider_and_model,
    extract_memory_from_pasted_text,
    derive_user_constraints_for_goal,
    negotiate_team_goal,
    negotiate_team_chat_turn,
)

app = FastAPI(title="MemoryAgent", version="1.0.0")
store = MemoryStore()

# very small in-process session cache: user_id -> list of {role, content}
_SESSION_HISTORY = {}
MAX_TURNS_IN_CONTEXT = 4


def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency to extract and validate session token from Authorization header.
    Returns authenticated user_id or raises 401 Unauthorized.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required. Missing Authorization header.")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format. Expected 'Bearer <token>'.")

    token = parts[1].strip()
    session = store.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session token. Please log in again.")

    return session["user_id"]


class AuthSignupRequest(BaseModel):
    user_id: str
    password: str
    display_name: Optional[str] = None


class AuthLoginRequest(BaseModel):
    user_id: str
    password: str


class ChatRequest(BaseModel):
    user_id: str
    message: str
    conversation_id: Optional[int] = None


class ChatResponse(BaseModel):
    reply: str
    recalled_memories: List[str]
    new_memory_stored: Optional[str] = None


class LearnRequest(BaseModel):
    text: str


class ProviderSetRequest(BaseModel):
    provider: str
    model: str


class ConversationCreateRequest(BaseModel):
    user_id: str
    title: Optional[str] = None


class UserLoginRequest(BaseModel):
    user_id: str
    display_name: Optional[str] = None


class TeamCreateRequest(BaseModel):
    name: str
    created_by: str


class TeamInviteRequest(BaseModel):
    invited_user_id: str
    invited_by: str


class InviteRespondRequest(BaseModel):
    accept: bool


class NegotiateRequest(BaseModel):
    team_id: int
    user_ids: List[str]
    goal: str


class TeamChatTurnRequest(BaseModel):
    user_id: str
    message: str
    team_conversation_id: Optional[int] = None


class TeamShareRequest(BaseModel):
    user_id: str
    content: str


# ── Authentication Endpoints ───────────────────────────────────────────────

@app.post("/auth/signup")
def auth_signup(req: AuthSignupRequest):
    try:
        return store.signup_user(req.user_id, req.password, req.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login")
def auth_login(req: AuthLoginRequest):
    try:
        return store.login_user(req.user_id, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/auth/logout")
def auth_logout(authorization: Optional[str] = Header(None), current_user: str = Depends(get_current_user)):
    token = authorization.split()[1].strip()
    store.delete_session(token)
    return {"status": "logged_out", "user_id": current_user}


# ── Core Chat & Memory Endpoints (Protected) ──────────────────────────────

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, current_user: str = Depends(get_current_user)):
    if req.user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions for another user.")

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    store.upsert_user(req.user_id)

    if req.conversation_id:
        store.save_chat_message(req.conversation_id, "user", req.message)

    store.decay_and_forget(user_id=req.user_id)

    recalled = store.recall(req.user_id, req.message, top_k=5)
    recalled_texts = [m.content for m in recalled]

    history = _SESSION_HISTORY.get(req.user_id, [])

    result = chat_with_memory(req.message, recalled_texts, history)

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": result["reply"]})
    _SESSION_HISTORY[req.user_id] = history[-(MAX_TURNS_IN_CONTEXT * 2):]

    if req.conversation_id:
        store.save_chat_message(req.conversation_id, "assistant", result["reply"])

    stored = None
    if result["new_memory"]:
        store.add_memory(req.user_id, result["new_memory"], category="preference")
        stored = result["new_memory"]

    return ChatResponse(
        reply=result["reply"],
        recalled_memories=recalled_texts,
        new_memory_stored=stored,
    )


@app.post("/conversations")
def create_conversation(req: ConversationCreateRequest, current_user: str = Depends(get_current_user)):
    if req.user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions for another user.")
    if not req.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id cannot be empty")
    return store.create_conversation(req.user_id, req.title)


@app.get("/conversations/{user_id}")
def list_conversations(user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's conversations.")
    return store.list_conversations(user_id)


@app.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(conversation_id: int, current_user: str = Depends(get_current_user)):
    return store.get_conversation_messages(conversation_id)


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, current_user: str = Depends(get_current_user)):
    store.delete_conversation(conversation_id)
    return {"status": "deleted", "id": conversation_id}


@app.get("/memories/{user_id}/export")
def export_memories(user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's memories.")
    memories = store.all_memories(user_id)
    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "content": m.content,
            "category": m.category,
            "confidence": round(m.confidence, 3),
            "created_at": m.created_at,
            "last_accessed": m.last_accessed,
            "access_count": m.access_count,
        }
        for m in memories
    ]


@app.get("/memories/{user_id}")
def list_memories(user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's memories.")
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
def delete_memory(mem_id: int, current_user: str = Depends(get_current_user)):
    store.forget(mem_id)
    return {"status": "deleted", "id": mem_id}


@app.post("/memories/{user_id}/learn-from-text")
def learn_from_text(user_id: str, req: LearnRequest, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to add memories for another user.")
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    extracted_facts = extract_memory_from_pasted_text(req.text)
    stored_facts = []

    for fact in extracted_facts:
        store.add_memory(user_id, fact, category="preference")
        stored_facts.append(fact)

    return {"extracted": stored_facts}


@app.post("/maintenance/decay")
def run_decay(current_user: str = Depends(get_current_user)):
    deleted = store.decay_and_forget()
    return {"status": "ok", "deleted": deleted}


@app.post("/providers/set")
def set_provider(req: ProviderSetRequest):
    try:
        set_runtime_provider_and_model(req.provider, req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "provider": req.provider, "model": req.model}


@app.get("/providers")
def get_providers():
    provider, model = get_provider_and_model()
    return {"provider": provider, "model": model}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── User Profile & Teams endpoints (Protected) ─────────────────────────────

@app.post("/users/login")
def user_login(req: UserLoginRequest):
    if not req.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id cannot be empty")
    return store.upsert_user(req.user_id, req.display_name)


@app.get("/users/check/{user_id}")
def check_user_exists(user_id: str):
    u = store.get_user(user_id)
    return {"exists": u is not None, "user_id": user_id}


@app.post("/teams")
def create_team(req: TeamCreateRequest, current_user: str = Depends(get_current_user)):
    if req.created_by != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions for another user.")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Team name cannot be empty")
    return store.create_team(req.name, req.created_by)


@app.post("/teams/{team_id}/invite")
def invite_to_team(team_id: int, req: TeamInviteRequest, current_user: str = Depends(get_current_user)):
    if req.invited_by != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions for another user.")
    try:
        return store.invite_user_to_team(team_id, req.invited_user_id, req.invited_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/users/{user_id}/invites")
def get_user_invites(user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's invites.")
    return store.get_user_invites(user_id)


@app.post("/invites/{invite_id}/respond")
def respond_to_invite(invite_id: int, req: InviteRespondRequest, current_user: str = Depends(get_current_user)):
    try:
        return store.respond_to_invite(invite_id, req.accept)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/users/{user_id}/teams")
def get_user_teams(user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's teams.")
    return store.get_user_teams(user_id)


@app.get("/teams/{team_id}/members")
def get_team_members(team_id: int, current_user: str = Depends(get_current_user)):
    return store.get_team_members(team_id)


@app.post("/negotiate")
def negotiate(req: NegotiateRequest, current_user: str = Depends(get_current_user)):
    if not req.goal.strip():
        raise HTTPException(status_code=400, detail="Goal cannot be empty")
    if not req.user_ids:
        raise HTTPException(status_code=400, detail="Must include at least 1 team member")

    confirmed_members = store.get_team_members(req.team_id)
    confirmed_set = {m["user_id"] for m in confirmed_members}
    if current_user not in confirmed_set:
        raise HTTPException(status_code=403, detail="Caller is not a confirmed member of this team.")

    for u in req.user_ids:
        if u not in confirmed_set:
            raise HTTPException(
                status_code=403,
                detail=f"User '{u}' is not a confirmed member of team {req.team_id}."
            )

    member_constraints = {}
    for uid in req.user_ids:
        raw_mems = store.recall(uid, req.goal, top_k=6)
        raw_texts = [m.content for m in raw_mems]
        derived = derive_user_constraints_for_goal(uid, req.goal, raw_texts)
        member_constraints[uid] = derived

    recommendation = negotiate_team_goal(req.goal, member_constraints)

    return {
        "team_id": req.team_id,
        "goal": req.goal,
        "recommendation": recommendation,
        "member_constraints": member_constraints,
    }


# ── Persistent Team Negotiator Chat & Shared Facts ──────────────────────────

@app.post("/teams/{team_id}/chat")
def team_chat_turn(team_id: int, req: TeamChatTurnRequest, current_user: str = Depends(get_current_user)):
    if req.user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions for another user.")

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    confirmed_members = store.get_team_members(team_id)
    confirmed_set = {m["user_id"] for m in confirmed_members}
    if req.user_id not in confirmed_set:
        raise HTTPException(
            status_code=403,
            detail=f"User '{req.user_id}' is not a confirmed member of team {team_id}."
        )

    conv = store.get_or_create_team_conversation(team_id, req.user_id)
    conv_id = req.team_conversation_id or conv["id"]

    store.save_team_message(conv_id, req.user_id, "user", req.message)

    member_constraints = {}
    for member in confirmed_members:
        uid = member["user_id"]
        raw_mems = store.recall(uid, req.message, top_k=5)
        raw_texts = [m.content for m in raw_mems]
        derived = derive_user_constraints_for_goal(uid, req.message, raw_texts)
        member_constraints[uid] = derived

    shared_facts = store.get_all_team_shared_facts(team_id)

    history = store.get_team_conversation_messages(conv_id)[-8:]

    reply = negotiate_team_chat_turn(req.message, history, member_constraints, shared_facts)

    store.save_team_message(conv_id, "negotiator", "assistant", reply, derived_constraints=member_constraints)

    return {
        "reply": reply,
        "team_conversation_id": conv_id,
        "derived_constraints": member_constraints,
    }


@app.get("/teams/{team_id}/conversations")
def get_team_conversations(team_id: int, user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's conversations.")
    return store.get_or_create_team_conversation(team_id, user_id)


@app.get("/team-conversations/{team_conversation_id}/messages")
def get_team_conversation_messages(team_conversation_id: int, current_user: str = Depends(get_current_user)):
    return store.get_team_conversation_messages(team_conversation_id)


@app.post("/teams/{team_id}/share")
def share_fact_with_team(team_id: int, req: TeamShareRequest, current_user: str = Depends(get_current_user)):
    if req.user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions for another user.")

    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Shared content cannot be empty")
    confirmed_members = store.get_team_members(team_id)
    confirmed_set = {m["user_id"] for m in confirmed_members}
    if req.user_id not in confirmed_set:
        raise HTTPException(
            status_code=403,
            detail=f"User '{req.user_id}' is not a confirmed member of team {team_id}."
        )
    return store.add_team_shared_fact(team_id, req.user_id, req.content)


@app.get("/teams/{team_id}/shared")
def get_team_shared_facts(team_id: int, user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to view another user's private disclosed facts.")
    return store.get_user_team_shared_facts(team_id, user_id)


@app.delete("/teams/{team_id}/shared/{fact_id}")
def delete_team_shared_fact(team_id: int, fact_id: int, user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to delete another user's disclosed fact.")
    store.delete_team_shared_fact(fact_id, user_id)
    return {"status": "deleted", "id": fact_id}


@app.delete("/teams/{team_id}/members/{target_user_id}")
def remove_team_member(team_id: int, target_user_id: str, caller_id: str, current_user: str = Depends(get_current_user)):
    if caller_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions as another user.")

    confirmed_members = store.get_team_members(team_id)
    confirmed_set = {m["user_id"] for m in confirmed_members}
    if caller_id not in confirmed_set:
        raise HTTPException(status_code=403, detail="Caller is not a member of this team.")

    teams = store.get_user_teams(caller_id)
    team_obj = next((t for t in teams if t["id"] == team_id), None)
    creator = team_obj["created_by"] if team_obj else None

    if caller_id != target_user_id and caller_id != creator:
        raise HTTPException(status_code=403, detail="Only team creator can remove other members.")

    store.delete_team_member(team_id, target_user_id)
    return {"status": "deleted", "team_id": team_id, "user_id": target_user_id}


@app.delete("/teams/{team_id}")
def delete_team(team_id: int, caller_id: str, current_user: str = Depends(get_current_user)):
    if caller_id != current_user:
        raise HTTPException(status_code=403, detail="You are not authorized to perform actions as another user.")
    return store.delete_team(team_id, caller_id)


@app.get("/teams/{team_id}/invites")
def get_team_pending_invites(team_id: int, current_user: str = Depends(get_current_user)):
    return store.get_team_pending_invites(team_id)


# ── Static frontend ────────────────────────────────────────────────────────
# Mounted AFTER all API routes so that /chat, /memories, /health, etc.
# are matched first, and only unmatched paths fall through to the SPA.
from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/", StaticFiles(directory="static", html=True), name="static")
