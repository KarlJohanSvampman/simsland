"""
Is Ollama up, and has it been answering? (llm/ollama_health.py, recorded by llm/llm_client.py::_call_llm)

Run inside the backend container:   python tests/test_ollama_health.py
(a fake Ollama on a local port; uses Redis, under a test key, never the live one)
"""

import asyncio
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from llm import ollama_health as oh
from llm import llm_client as lc

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeOllama(BaseHTTPRequestHandler):
    delay = 0.0

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:                         # the caller gave up on this one (the abandoned-call check)
            pass

    def do_GET(self):
        self._json({"models": [{"name": "llama3.1:latest"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        time.sleep(FakeOllama.delay)
        self._json({"message": {"content": "hello"}})

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=server.serve_forever, daemon=True).start()
fake = f"http://127.0.0.1:{server.server_port}"

oh._KEY = "ollama:health:test"
lc.r.delete(oh._KEY)
os.environ["OLLAMA_BASE_URL"], os.environ["OLLAMA_MODEL"] = fake, "llama3.1:latest"
msgs = [{"role": "user", "content": "hi"}]

check("nothing called yet: unknown without a probe", oh.status(do_probe=False)["status"] == "unknown")
check("the probe finds the server and the model", oh.status()["status"] == "up")

check("a call comes back", asyncio.run(lc._call_llm(msgs)) == "hello")
s = oh.status()
check("and is recorded as a reply", s["recorded"].get("ok_count") == 1 and s["responding_recently"], str(s["recorded"]))
check("up, with or without the probe", s["status"] == "up" and oh.status(do_probe=False)["status"] == "up")

os.environ["OLLAMA_MODEL"] = "mistral"
check("a server without the configured model is degraded", oh.status()["status"] == "degraded")
os.environ["OLLAMA_MODEL"] = "llama3.1:latest"

FakeOllama.delay = 2.0
async def abandoned():
    try:
        await asyncio.wait_for(lc._call_llm(msgs), 0.3)
    except asyncio.TimeoutError:
        pass
asyncio.run(abandoned())
s = oh.status(do_probe=False)
check("a call the caller gave up on is counted as cancelled, not failed",
      s["recorded"].get("cancelled_count") == 1 and s["recorded"].get("error_count", 0) == 0, str(s["recorded"]))
check("and leaves the call unanswered", "unanswered_since" in s["recorded"])
FakeOllama.delay = 0.0

lc.r.hset(oh._KEY, mapping={"unanswered_since": time.time() - 120, "last_ok": time.time() - 400})
s = oh.status(do_probe=False)
check("calls unanswered for two minutes: degraded", s["calls_unanswered"] and s["status"] == "degraded", str(s))
asyncio.run(lc._call_llm(msgs))
s = oh.status(do_probe=False)
check("a reply clears it", not s["calls_unanswered"] and s["status"] == "up", str(s))

os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"
for _ in range(3):
    try:
        asyncio.run(lc._call_llm(msgs))
    except Exception:
        pass
s = oh.status()
check("an unreachable server is down", s["status"] == "down" and not s["probe"]["reachable"], str(s.get("probe")))
check("its errors are recorded", s["recorded"].get("consecutive_failures") == 3 and "Connect" in s["recorded"].get("last_error_text", ""))
check("three failures in a row is degraded even without the probe", oh.status(do_probe=False)["status"] == "degraded")

lc.r.delete(oh._KEY)
server.shutdown()
print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
