"""
llm/provider.py: the simulation talks to Ollama (the default) or to any OpenAI-compatible service (ChatGPT and the rest).

  * the request each provider is sent: Ollama's /api/chat body unchanged; the OpenAI form with the model, a Bearer
    key, the reply cap under the name the service takes (or none, LLM_MAX_TOKENS=off), reasoning_effort when set;
  * the reply text read out of each response shape (content parts too);
  * a real round trip, and the status light, against a stand-in OpenAI server on localhost: up, a missing model,
    a refused key, nothing listening.

Run inside the backend container:   python tests/test_llm_provider.py
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from llm import provider  # noqa: E402

for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "OPENAI_API_KEY", "LLM_MAX_TOKENS",
          "LLM_REASONING_EFFORT"):
    os.environ.pop(k, None)
MSG = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

# ── Ollama, the default: the request it always got ──────────────────────────────────────────────────────────────────
os.environ.update(OLLAMA_BASE_URL="http://o:11434/", OLLAMA_MODEL="llama3.1:latest")
url, body, headers = provider.chat_request(MSG, max_tokens=220)
check("default is Ollama: /api/chat, the model, num_predict for the cap, no auth",
      provider.name() == "ollama" and url == "http://o:11434/api/chat" and body["model"] == "llama3.1:latest"
      and body["options"]["num_predict"] == 220 and body["stream"] is False and not headers, (url, body))
check("Ollama reply text", provider.reply_text({"message": {"content": "ACTION: wait"}}) == "ACTION: wait")

# ── OpenAI form ─────────────────────────────────────────────────────────────────────────────────────────────────────
os.environ.update(LLM_PROVIDER="openai", LLM_MODEL="gpt-4o-mini", LLM_API_KEY="sk-test")
url, body, headers = provider.chat_request(MSG, max_tokens=220)
check("OpenAI by default: chat/completions, Bearer key, max_completion_tokens",
      url == "https://api.openai.com/v1/chat/completions" and headers == {"Authorization": "Bearer sk-test"}
      and body == {"model": "gpt-4o-mini", "messages": MSG, "max_completion_tokens": 220}, (url, body))
check("named OpenAI", provider.label() == "OpenAI")
os.environ["LLM_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
url, body, _ = provider.chat_request(MSG, max_tokens=220)
check("a compatible service: its base URL, max_tokens", url.endswith("/v1beta/openai/chat/completions")
      and body.get("max_tokens") == 220 and "max_completion_tokens" not in body and provider.label() == "Gemini", body)
os.environ.update(LLM_MAX_TOKENS="off", LLM_REASONING_EFFORT="low")
_, body, _ = provider.chat_request(MSG, max_tokens=220)
check("LLM_MAX_TOKENS=off drops the cap; reasoning_effort passed on",
      "max_tokens" not in body and body.get("reasoning_effort") == "low", body)
os.environ.pop("LLM_MAX_TOKENS"); os.environ.pop("LLM_REASONING_EFFORT")
os.environ.pop("LLM_API_KEY"); os.environ["OPENAI_API_KEY"] = "sk-other"
check("OPENAI_API_KEY is read too", provider.chat_request(MSG)[2] == {"Authorization": "Bearer sk-other"})
check("OpenAI reply text", provider.reply_text({"choices": [{"message": {"content": "hi"}}]}) == "hi")
check("... content parts joined", provider.reply_text(
    {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}) == "ab")
check("... nothing there is an empty reply", provider.reply_text({"choices": []}) == "")

# ── a stand-in OpenAI server ────────────────────────────────────────────────────────────────────────────────────────
seen = []


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
        if self.headers.get("Authorization") != "Bearer good":
            return self._send(401, {"error": {"message": "bad key"}})
        self._send(200, {"data": [{"id": "gpt-4o-mini"}, {"id": "other"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, self.headers.get("Authorization"), body))
        if self.headers.get("Authorization") != "Bearer good":
            return self._send(401, {"error": {"message": "bad key"}})
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": "ACTION: wait | here"}}]})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
os.environ.pop("OPENAI_API_KEY")
os.environ.update(LLM_BASE_URL=f"http://127.0.0.1:{port}/v1", LLM_API_KEY="good", LLM_MODEL="gpt-4o-mini")

from llm import llm_client  # noqa: E402
out = asyncio.run(llm_client._call_llm(MSG, timeout=5, max_tokens=50))
check("a round trip through llm_client: the reply text comes back", out == "ACTION: wait | here", out)
check("... sent to /v1/chat/completions with the key and the cap", seen and seen[-1][0] == "/v1/chat/completions"
      and seen[-1][1] == "Bearer good" and seen[-1][2]["max_tokens"] == 50, seen[-1:])

st = provider.status()
check("status: up, the model listed", st["state"] == "up" and st["model_available"] and st["provider"] == "openai", st)
os.environ["LLM_MODEL"] = "gpt-nope"
st = provider.status()
check("status: degraded when the model isn't listed", st["state"] == "degraded" and "gpt-nope" in st["error"], st)
os.environ.update(LLM_MODEL="gpt-4o-mini", LLM_API_KEY="bad")
st = provider.status()
check("status: down, saying the key was refused", st["state"] == "down" and "key" in st["error"], st)
try:
    asyncio.run(llm_client._call_llm(MSG, timeout=5))
    check("a refused key raises", False)
except Exception as e:
    why = llm_client.describe_llm_error(e)
    check("a refused key raises, described with the provider's name", why.startswith("http 401: Model API refused"), why)
srv.shutdown()
srv.server_close()
st = provider.status(timeout=1)
check("status: down when nothing listens", st["state"] == "down", st)
os.environ.update(LLM_BASE_URL="https://api.openai.com/v1")
os.environ.pop("LLM_API_KEY")
st = provider.status()
check("status: OpenAI without a key says so (and asks nothing)", st["state"] == "down" and "API key" in st["error"], st)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
