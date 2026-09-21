import json

import httpx
from fastapi.testclient import TestClient

from conftest import ScriptedLLM
from simsland_mw.config import Settings
from simsland_mw.llm.ollama import OllamaClient, choice_schema
from simsland_mw.main import create_app
from simsland_mw.simulation.client import SimClient
from simsland_mw.simulation.mock import MockSimClient


async def test_ollama_constrains_output_to_offered_ids():
    seen = []

    def handler(req: httpx.Request):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": '{"choice": "wait"}'}})

    c = OllamaClient("http://x", "m", transport=httpx.MockTransport(handler))
    assert await c.choose([{"role": "user", "content": "hi"}], ["eat", "wait"]) == '{"choice": "wait"}'
    assert seen[0]["format"] == choice_schema(["eat", "wait"])
    assert seen[0]["format"]["properties"]["choice"]["enum"] == ["eat", "wait"]
    assert seen[0]["stream"] is False


async def test_ollama_falls_back_to_plain_json_mode_on_old_servers():
    formats = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        formats.append(body["format"])
        if isinstance(body["format"], dict):
            return httpx.Response(400, text="invalid format")
        return httpx.Response(200, json={"message": {"content": "{}"}})

    c = OllamaClient("http://x", "m", transport=httpx.MockTransport(handler))
    await c.choose([], ["a"])
    assert formats[-1] == "json" and len(formats) == 2


async def test_sim_client_talks_to_the_bridge_routes():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, dict(req.url.params), req.content))
        return httpx.Response(200, json={"ok": True})

    c = SimClient("http://sim", transport=httpx.MockTransport(handler))
    await c.snapshot("kim", ["environment", "character"])
    await c.execute("kim", {"action": {"type": "wait"}}, "idle")
    assert calls[0][:3] == ("GET", "/mw/characters/kim/snapshot", {"sections": "character,environment"})
    assert calls[1][:2] == ("POST", "/mw/characters/kim/execute")
    assert json.loads(calls[1][3])["wake_reason"] == "idle"


def _client(llm=None):
    app = create_app(sim=MockSimClient(), llm=llm or ScriptedLLM('{"choice": "eat_something_at_home"}'), settings=Settings())
    return TestClient(app)


def test_api_preview_shows_prompt_without_calling_llm():
    llm = ScriptedLLM()
    with _client(llm) as c:
        body = c.get("/characters/kim/preview").json()
        assert body["options"][0]["id"] == "eat_something_at_home" and "WHO I AM" in body["prompt"][1]["content"]
        assert llm.calls == []


def test_api_decide_defaults_to_dry_run():
    with _client() as c:
        rec = c.post("/characters/kim/decide").json()
        assert rec["choice_id"] == "eat_something_at_home" and rec["executed"] is False
        live = c.post("/characters/kim/decide?dry_run=false").json()
        assert live["executed"] is True


def test_api_lists_data_types_with_dependencies():
    with _client() as c:
        types = {t["type"]: t for t in c.get("/data-types").json()}
        assert types["environment.nearby_characters"]["depends_on"] == ["character.location"]


def test_api_rejects_unknown_profile():
    with _client() as c:
        assert c.get("/characters/kim/preview?profile=nope").status_code == 400
