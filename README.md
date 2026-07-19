# MemoryAgent

**Track 1: MemoryAgent** — Global AI Hackathon with Qwen Cloud

A personal assistant that accumulates durable knowledge about a user
(preferences, allergies, constraints) across sessions, recalls only the
most *relevant* memories for each new query instead of dumping its whole
history into the prompt, and forgets stale information over time.

## What it does

- Every chat turn is sent to **Qwen** (via Qwen Cloud's OpenAI-compatible
  API) alongside a small set of *recalled* memories relevant to that turn.
- The model itself flags any durable preference/fact worth remembering; the
  backend persists it to a per-user SQLite memory store.
- On the next session — even after a full restart — those facts are
  recalled and folded back into context automatically. No re-asking.
- Memories decay in confidence over time (recency + disuse) and are
  hard-deleted once they drop below a floor, so the store stays small and
  the recalled context stays high-signal.
- New facts that closely match an existing memory **overwrite** it instead
  of duplicating it, so corrections ("I moved to a new city") replace
  outdated facts rather than piling up.

## Architecture

```
User ──POST /chat──▶ FastAPI backend (Alibaba Cloud ECS / Function Compute)
                          │
                          ├─▶ MemoryStore (SQLite)
                          │     - recall(): relevance × confidence × recency scoring
                          │     - add_memory(): dedupe/overwrite on high similarity
                          │     - decay_and_forget(): periodic confidence decay
                          │
                          ├─▶ Qwen Cloud API (dashscope-intl, OpenAI-compatible)
                          │     - chat completion with injected memory context
                          │     - extracts new durable facts inline
                          │
                          └─▶ Alibaba Cloud OSS (oss_backup.py)
                                - backs up memory.db so it survives redeploys
```

See `docs/architecture.svg` for the visual diagram.

## Setup

```bash
git clone <this repo>
cd memoryagent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export QWEN_API_KEY=your_qwen_cloud_api_key
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Try it

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "demo_user", "message": "I am vegetarian and allergic to peanuts"}'

# ... later, even after restarting the server ...
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "demo_user", "message": "Suggest a dinner recipe for me"}'
```

Or run `python demo.py` for a scripted cross-session recall demo (used for
the submission video).

## Alibaba Cloud Deployment

The backend is deployed on Alibaba Cloud. Proof of deployment:
- `alibaba_deploy/oss_backup.py` — uses the Alibaba Cloud OSS SDK (`oss2`)
  to persist the memory store to Object Storage Service so it survives
  instance restarts / redeploys.
- `alibaba_deploy/fc_handler.py` + `alibaba_deploy/s.yaml` — Function
  Compute serverless deployment definition.
- `alibaba_deploy/ecs_deploy.sh` — ECS deployment script (fastest path for
  a live demo instance).

## Qwen Cloud Integration

`app/qwen_client.py` calls Qwen Cloud's OpenAI-compatible endpoint
(`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`) using the
`openai` Python SDK, injecting recalled memories into the system prompt on
every turn and extracting new durable facts from the model's own output.

## Why this matters (Problem Value)

Most chat assistants forget everything the moment a session ends, forcing
users to re-explain context every time. MemoryAgent shows a lightweight,
dependency-free pattern (no vector DB required) for durable personalization
that stays within a small context budget — directly useful for customer
support tools, personal assistants, and any product where "remembering the
user" is the core value proposition.

## License

MIT — see `LICENSE`.
