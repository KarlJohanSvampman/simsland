"""
What someone is doing on their phone or computer (systems/screen_activity.py).

A. A text, a call, the news, research, email, stocks, shopping, videos -- each described in words, with who and what.
B. after_route(): c["screen"] (device, app, what, their own words) and a short log; nothing for non-device actions.
C. current(): only while that activity is going on.

Run inside the backend container:   python tests/test_screen_activity.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import systems.screen_activity as S
world = {"tick": 50, "characters": {"r": {"id": "r", "name": "Rebecca Carter"}}}
c = {"id": "a", "name": "Anthony", "hobbies": ["historical_writing"], "activity": {}}

def d(action, activity=None):
    c["activity"] = activity or {"type": action["type"]}
    return S.describe(c, world, action)

check("A: a text, to whom, what", d({"type": "phone_send_text", "target_id": "r", "message": "Running late, sorry"}) == 'texting Rebecca: "Running late, sorry"')
check("A: a call", d({"type": "phone_call", "target_id": "r"}) == "on a call with Rebecca")
check("A: the news, with the headline", d({"type": "computer_news"}, {"type": "computer_news", "headlines": [{"title": "Storm hits coast"}]}) == 'reading the news: "Storm hits coast"')
check("A: research, what", d({"type": "computer_wiki_research"}, {"type": "computer_wiki_research", "research_keyword": "Roman roads"}) == "looking up Roman roads")
check("A: email, to whom", d({"type": "computer_send_email", "target_id": "r", "subject": "Dinner Friday"}).startswith("writing an email to Rebecca"))
check("A: stocks", d({"type": "computer_buy_stock", "ticker": "ACME"}, {"type": "computer_buy_stock", "stock_price": {"ticker": "ACME", "price": 12.5}}) == "buying stocks -- ACME at 12.5")
check("A: videos, about their hobby when nothing else is said", d({"type": "computer_videos"}) == "watching videos about historical writing")
check("A: shopping for something", d({"type": "computer_window_shopping", "detail": "a new lamp"}) == "browsing an online shop for a new lamp")

# B
c["activity"] = {"type": "phone_send_text"}
e = S.after_route(c, world, {"type": "phone_send_text", "target_id": "r", "message": "hi", "reason": "I text Rebecca to say hi"})
check("B: the screen says device, app, what, and their own words", e and e["device"] == "phone" and e["app"] == "Messages"
      and e["what"] == 'texting Rebecca: "hi"' and e["in_their_words"].startswith("I text"), e)
check("B: logged", c["screen_log"][-1]["what"] == 'texting Rebecca: "hi"')
check("B: nothing for an action off the device", S.after_route(c, world, {"type": "eat"}) is None)

# C
check("C: on screen while the activity goes on", S.current(c) is not None)
c["activity"] = {"type": "eat_meal"}
check("C: not once they've moved on", S.current(c) is None)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
