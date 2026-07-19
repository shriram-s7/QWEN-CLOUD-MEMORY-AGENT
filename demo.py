"""
Run this against a live server (local or Alibaba Cloud) to demonstrate
cross-session memory recall for the submission video.

Usage:
  python demo.py                       # targets http://localhost:8000
  python demo.py http://<ECS_IP>:8000  # targets your Alibaba Cloud deployment
"""

import sys
import time
import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
USER_ID = "demo_user"


def send(message: str):
    print(f"\n>>> USER: {message}")
    r = requests.post(f"{BASE_URL}/chat", json={"user_id": USER_ID, "message": message})
    r.raise_for_status()
    data = r.json()
    print(f"<<< AGENT: {data['reply']}")
    if data.get("recalled_memories"):
        print(f"    [recalled from memory: {data['recalled_memories']}]")
    if data.get("new_memory_stored"):
        print(f"    [stored new memory: {data['new_memory_stored']}]")
    return data


if __name__ == "__main__":
    print("=== SESSION 1 ===")
    send("Hi! I'm a vegetarian and I'm allergic to peanuts.")
    send("I also prefer short, no-fluff answers.")

    print("\n(simulating end of session -- in a real demo, restart the process here)")
    time.sleep(1)

    print("\n=== SESSION 2 (new conversation, same user_id) ===")
    send("Can you suggest a dinner recipe for me?")
    send("What do you remember about me?")
