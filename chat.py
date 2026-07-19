"""
Interactive chat client for MemoryAgent - type your own messages like a
real chatbot, instead of running the scripted demo.

Usage:
  python chat.py                       # targets http://localhost:8000
  python chat.py http://<ECS_IP>:8000  # targets your Alibaba Cloud deployment

Type 'exit' to quit. Type 'new' to switch to a fresh user_id (simulates a
different person). Memories persist in memory.db even after you quit and
rerun this script - that's the cross-session recall in action.
"""

import sys
import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
user_id = "demo_user"

print(f"Connected to {BASE_URL}")
print(f"Chatting as user_id='{user_id}'")
print("Type your message and hit Enter. Commands: 'new' = switch user, 'exit' = quit\n")

while True:
    message = input("You: ").strip()

    if not message:
        continue
    if message.lower() == "exit":
        break
    if message.lower() == "new":
        user_id = input("New user_id: ").strip() or "demo_user"
        print(f"Switched to user_id='{user_id}'\n")
        continue

    try:
        r = requests.post(f"{BASE_URL}/chat", json={"user_id": user_id, "message": message})
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print(f"[error] Could not reach server: {e}\n")
        continue

    print(f"Agent: {data['reply']}")
    if data.get("recalled_memories"):
        print(f"  (recalled: {data['recalled_memories']})")
    if data.get("new_memory_stored"):
        print(f"  (stored: {data['new_memory_stored']})")
    print()