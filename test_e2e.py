"""
End-to-end test: signup -> chat (build memories) -> team chat uses memories
Simulates the full 'homelander says I dont like Africa' -> team chat recalls it flow.
"""
import os, sys
os.environ.pop('QWEN_API_KEY', None)       # force mock mode
os.environ.pop('OPENROUTER_API_KEY', None)

# Use a temp db
import tempfile, shutil
tmp = tempfile.mktemp(suffix='.db')
os.environ['MEMORY_DB_PATH'] = tmp

from app.memory import MemoryStore
from app.qwen_client import chat_with_memory, derive_user_constraints_for_goal, negotiate_team_chat_turn

store = MemoryStore(tmp)

print("=== Step 1: Signup Homelander ===")
result = store.signup_user("Homelander", "test1234")
token = result["token"]
print(f"  user_id={result['user_id']}, token={token[:12]}...")

print()
print("=== Step 2: Homelander says 'I don't like Africa' ===")
chat_result = chat_with_memory("I don't like Africa", [], [])
print(f"  Reply (mock): {chat_result['reply'][:60]}...")
print(f"  New memory:   {chat_result['new_memory']}")

# Store the memory
if chat_result["new_memory"]:
    store.add_memory("Homelander", chat_result["new_memory"], category="preference")
    print(f"  STORED memory for Homelander")
else:
    print("  WARNING: No memory extracted!")

print()
print("=== Step 3: Homelander says 'I love lasagna' ===")
chat_result2 = chat_with_memory("I love lasagna", [], [])
print(f"  New memory: {chat_result2['new_memory']}")
if chat_result2["new_memory"]:
    store.add_memory("Homelander", chat_result2["new_memory"], category="preference")

print()
print("=== Step 4: Check /memories/Homelander ===")
mems = store.all_memories("Homelander")
print(f"  Total memories: {len(mems)}")
for m in mems:
    print(f"    [{m.category}] {m.content}")

print()
print("=== Step 5: Create team & add Homelander ===")
store.signup_user("Butcher", "test1234")
team = store.create_team("The Boys", "Homelander")
store.invite_user_to_team(team["id"], "Butcher", "Homelander")
# Find the invite and accept it
invites = store.get_user_invites("Butcher")
store.respond_to_invite(invites[0]["id"], accept=True)
members = store.get_team_members(team["id"])
print(f"  Team members: {[m['user_id'] for m in members]}")

print()
print("=== Step 6: Team chat asks 'where should we travel?' ===")
member_constraints = {}
for member in members:
    uid = member["user_id"]
    raw_mems = store.recall(uid, "where should we travel?", top_k=5)
    raw_texts = [m.content for m in raw_mems]
    print(f"  Recalled for {uid}: {raw_texts}")
    derived = derive_user_constraints_for_goal(uid, "where should we travel?", raw_texts)
    member_constraints[uid] = derived
    print(f"  Constraints for {uid}: {derived}")

print()
print("=== Step 7: Negotiate (mock mode) ===")
reply = negotiate_team_chat_turn("where should we travel?", [], member_constraints, [])
print(f"  Negotiator reply:\n{reply}")

print()
print("=== RESULT ===")
africa_in_constraints = any(
    "africa" in str(c).lower()
    for constraints in member_constraints.values()
    for c in constraints
)
print(f"  Africa dislike in team constraints: {'YES ✅' if africa_in_constraints else 'NO ❌'}")

# cleanup
os.remove(tmp)
