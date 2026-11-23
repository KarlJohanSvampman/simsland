"""
llm/provider.py profiles: several model services at once, and which character uses which.

  * no profiles file: one profile, "env", from the LLM_* / OLLAMA_* variables (the old behaviour);
  * a file: each character's calls go to its own llm_profile, else the file's assign map (id / full name, then
    surname), else the default; calls for no character go to the background profile; an unknown name falls back;
  * a profile's key comes from the variable it names (api_key_env), never from the file;
  * a real round trip per character goes to that character's server (two stand-in OpenAI servers);
  * llm_gate gives every profile its own lane, sized by the profile's max_concurrency;
  * workers, which have no world, take the core's character -> profile map with a request;
  * the Persona tab's llm_profile field sets / clears a character's own choice;
  * the file is re-read when it changes; a broken file is ignored (the sim keeps going on "env").

Run inside the backend container:   python tests/test_llm_profiles.py
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "OPENAI_API_KEY", "LLM_MAX_TOKENS",
          "LLM_REASONING_EFFORT", "LLM_MAX_CONCURRENCY"):
    os.environ.pop(k, None)
tmpdir = tempfile.mkdtemp()
cfg_path = os.path.join(tmpdir, "llm_profiles.json")
os.environ["LLM_PROFILES_FILE"] = cfg_path
os.environ.update(OLLAMA_BASE_URL="http://o:11434", OLLAMA_MODEL="llama3.1:latest")

from llm import provider  # noqa: E402

MSG = [{"role": "user", "content": "u"}]


def write_cfg(obj):
    with open(cfg_path, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
    t = time.time() + 5 + len(str(obj)) % 7          # a different mtime each write, even within one second
    os.utime(cfg_path, (t, t))
    provider._cfg["checked"] = 0.0                    # don't wait out the 2 s re-check


# ── no file ─────────────────────────────────────────────────────────────────────────────────────────────────────────
check("no file: one profile, 'env', from the variables",
      provider.profile_names() == ["env"] and provider.default_name() == "env" and provider.name() == "ollama"
      and provider.model() == "llama3.1:latest")
check("no file: every character uses 'env'", provider.resolve_character({"id": "x", "name": "A B"}) == "env"
      and provider.profile_for("x") == "env" and provider.profile_for(None) == "env")

# ── stand-in servers ────────────────────────────────────────────────────────────────────────────────────────────────
seen = []


def make_server(tag, key):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            ok = self.headers.get("Authorization") == f"Bearer {key}"
            self._send(200 if ok else 401, {"data": [{"id": f"model-{tag}"}]} if ok else {"error": "bad key"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((tag, self.headers.get("Authorization"), body.get("model")))
            time.sleep(0.2)
            self._send(200, {"choices": [{"message": {"content": f"reply from {tag}"}}]})

    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


sa, sb = make_server("A", "key-a"), make_server("B", "key-b")
os.environ.update(KEY_A="key-a", KEY_B="key-b")
write_cfg({
    "default": "a", "background": "b",
    "profiles": {
        "a": {"provider": "openai", "base_url": f"http://127.0.0.1:{sa.server_address[1]}/v1", "model": "model-A",
              "api_key_env": "KEY_A", "max_concurrency": 3},
        "b": {"provider": "openai", "base_url": f"http://127.0.0.1:{sb.server_address[1]}/v1", "model": "model-B",
              "api_key_env": "KEY_B", "max_concurrency": 1},
        "local": {"provider": "ollama", "base_url": "http://o2:11434", "model": "llama3.1:latest"},
    },
    "assign": {"characters": {"Kathleen Okafor": "b", "char_steven": "local"}, "surnames": {"Okafor": "local"}},
})

# ── which profile ───────────────────────────────────────────────────────────────────────────────────────────────────
check("the file's profiles are read", provider.profile_names() == ["a", "b", "local"] and provider.default_name() == "a"
      and provider.background_name() == "b")
kat = {"id": "char_kat", "name": "Kathleen Okafor"}
rob = {"id": "char_rob", "name": "Robert Okafor"}
stv = {"id": "char_steven", "name": "Steven Moreau"}
don = {"id": "char_donna", "name": "Donna Moreau"}
own = {"id": "char_own", "name": "Robin Okafor", "llm_profile": "a"}
bad = {"id": "char_bad", "name": "Ann Smith", "llm_profile": "nope"}
check("assign by full name", provider.resolve_character(kat) == "b")
check("assign by id", provider.resolve_character(stv) == "local")
check("assign by surname", provider.resolve_character(rob) == "local")
check("nothing assigned: the default", provider.resolve_character(don) == "a")
check("their own choice beats the assign map", provider.resolve_character(own) == "a")
check("an unknown own choice falls back to assign / default", provider.resolve_character(bad) == "a")
check("profile_for follows what was worked out; no character -> background",
      provider.profile_for("char_kat") == "b" and provider.profile_for("char_rob") == "local"
      and provider.profile_for(None) == "b" and provider.profile_for("someone_new") == "a")

# ── settings and requests ───────────────────────────────────────────────────────────────────────────────────────────
url, body, headers = provider.chat_request(MSG, max_tokens=50, profile="b")
check("a profile's request: its URL, model and the key from its variable",
      url.endswith(f":{sb.server_address[1]}/v1/chat/completions") and body["model"] == "model-B"
      and headers == {"Authorization": "Bearer key-b"} and body.get("max_tokens") == 50, (url, body, headers))
url, body, headers = provider.chat_request(MSG, max_tokens=50, profile="local")
check("an ollama profile in the same file", url == "http://o2:11434/api/chat" and body["options"]["num_predict"] == 50
      and not headers, (url, body))
check("labels per profile", provider.label("local") == "Ollama" and provider.label("a") == "Model API")
check("keys never come from the file", "key-a" not in open(cfg_path).read())

# ── round trips go to each character's server ───────────────────────────────────────────────────────────────────────
from llm import llm_client  # noqa: E402
seen.clear()
ra = asyncio.run(llm_client._call_llm(MSG, timeout=5, char_id="char_donna"))
rb = asyncio.run(llm_client._call_llm(MSG, timeout=5, char_id="char_kat"))
rn = asyncio.run(llm_client._call_llm(MSG, timeout=5))
check("Donna's call goes to A, Kathleen's to B, a call for nobody to the background (B)",
      ra == "reply from A" and rb == "reply from B" and rn == "reply from B"
      and [s[0] for s in seen] == ["A", "B", "B"] and seen[0][1] == "Bearer key-a" and seen[1][2] == "model-B", seen)
check("the cache keeps models apart", llm_client._cache_key(MSG, "c", "a") != llm_client._cache_key(MSG, "c", "b"))

# ── gate lanes ──────────────────────────────────────────────────────────────────────────────────────────────────────
from llm import llm_gate  # noqa: E402


async def ask(messages, char_id=None):
    return await llm_client._call_llm(messages, 5, None, char_id=char_id)


llm_gate.run_llm_call(ask(MSG, char_id="char_donna"), timeout=10)      # warm up (imports, first connection)
seen.clear()
results, done_at = {}, {}


def run(i, cid):
    results[i] = llm_gate.run_llm_call(ask(MSG, char_id=cid), timeout=10)
    done_at[i] = time.time()


threads = [threading.Thread(target=run, args=(i, cid)) for i, cid in
           enumerate(["char_donna", "char_donna", "char_kat", "char_kat", "char_kat"])]
t0 = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
took = time.time() - t0
lanes = llm_gate.lanes_state()
check("every profile gets its own lane, sized by its max_concurrency",
      lanes.get("a", {}).get("max_concurrency") == 3 and lanes.get("b", {}).get("max_concurrency") == 1, lanes)
check("all calls answered by their own server", sorted(results.values()) == ["reply from A"] * 2 + ["reply from B"] * 3,
      results)
b_span = max(done_at[i] for i in (2, 3, 4)) - t0
a_span = max(done_at[i] for i in (0, 1)) - t0
check("B's one-at-a-time lane serialises its 3 calls (>= 0.6 s)", b_span >= 0.55, b_span)
check("... while A's calls run alongside, not behind them", a_span < b_span - 0.15, (a_span, b_span))
check("admin view: _heap / _running over all lanes", llm_gate._heap == [] and llm_gate._running == [])

# ── workers take the core's map ─────────────────────────────────────────────────────────────────────────────────────
provider._assign.clear()
check("a worker without the map uses the default", provider.profile_for("char_kat") == "a")
provider.load_assignments({"char_kat": "b", "junk": 3})
check("... and with it, the core's choice", provider.profile_for("char_kat") == "b" and "junk" not in provider._assign)

# ── persona field ───────────────────────────────────────────────────────────────────────────────────────────────────
from systems import personality_profile as pp  # noqa: E402
world = {"definitions": {"mood_templates": {}}, "characters": {}}
c = {"id": "char_donna", "name": "Donna Moreau", "traits": []}
out = pp.update(c, world, {"llm_profile": "local"})
check("the Persona tab sets a character's own model", c.get("llm_profile") == "local"
      and out.get("llm_profile_in_use") == "local" and [p["name"] for p in out["llm_profiles"]] == ["a", "b", "local"])
out = pp.update(c, world, {"llm_profile": ""})
check("... and clears it back to the default", "llm_profile" not in c and out.get("llm_profile_in_use") == "a")

# ── file changes ────────────────────────────────────────────────────────────────────────────────────────────────────
write_cfg({"default": "b", "profiles": {"b": {"provider": "openai", "model": "m"}}})
check("a changed file is re-read", provider.profile_names() == ["b"] and provider.default_name() == "b"
      and provider.background_name() == "b")
write_cfg("{ not json")
check("a broken file is ignored: back to 'env'", provider.profile_names() == ["env"])
st = provider.status_all(timeout=1)
check("status_all lists every profile", [p["profile"] for p in st["profiles"]] == ["env"] and not st["from_file"], st)

sa.shutdown(); sb.shutdown()
print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
