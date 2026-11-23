"""systems/voice.py: every character gets a stable voice of their own, and their recent lines in the prompt."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from systems import voice

# stable: the same id rolls the same voice, and ensure() keeps a stored one
a = {"id": "char_1", "traits": []}
assert voice.roll(a) == voice.roll(dict(a)), "the roll is seeded by id"
v = voice.ensure(a); assert a["voice"] is v and voice.ensure(a) is v

# varied: random characters rarely share a voice
vs = {tuple(voice.roll({"id": f"x{i}"}).values()) for i in range(100)}
assert len(vs) > 90, len(vs)

# traits lean the roll: aggressive characters come out prickly far more often
prickly = sum(voice.roll({"id": f"g{i}", "traits": ["aggressive"]})["warmth"] == 3 for i in range(200))
calm = sum(voice.roll({"id": f"g{i}", "traits": []})["warmth"] == 3 for i in range(200))
assert prickly > calm * 2, (prickly, calm)

# children never get careful, proper wording or adult habits
for i in range(100):
    k = voice.roll({"id": f"k{i}", "age": 8})
    assert k["register"] != 2 and k["habit"] in voice.CHILD_HABITS

# recent lines: distinct, newest last, in the prompt
c = {"id": "char_2", "speech_log": [{"utterance": "What's going on?"}, {"utterance": "what's going on?"}, {"utterance": "Fine."}]}
assert voice.recent_lines(c) == ["what's going on?", "Fine."], voice.recent_lines(c)
lines = voice.prompt_lines(c)
assert lines[0].startswith("How you talk:") and "don't reuse" in lines[1]
assert voice.prompt_lines({"id": "char_3"})[1:] == [], "no recent-lines line when they haven't spoken"
print("all passed")
