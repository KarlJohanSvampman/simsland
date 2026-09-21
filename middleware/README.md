# Simsland AI Middleware

Standalone service that sits between Simsland and the LLM (see the spec, `simsland-ai-middleware-spec.md`).

```
Simsland = game engine   |   this service = GM / narrator   |   LLM = the player controlling one character
```

The LLM never calls Simsland. It is shown a first-person account of the character's situation plus a
finite list of options Simsland has already determined are possible, and answers `{"choice": "<id>"}`.
Anything else is rejected.

This is **migration Phase 0 + Phase 1** of the spec: the whole fetch -> compile -> options -> LLM ->
validate -> execute loop, with a rule-based option generator. Not built yet: the cognition-aware output
(`thought` / `speech` / `interpretation`, Phase 2), event-driven wake-ups (Phase 3), hierarchical
decisions and the second "story" AI (Phase 4), scale-out (Phase 5).

## Run it

```bash
cd middleware
pip install -r requirements-dev.txt
python -m pytest                              # 63 tests, no Docker/Ollama needed
python -m simsland_mw.cli --mock              # see the prompt + options for the dinner example
python -m simsland_mw.cli --mock --ask 2      # ...and a decision as if the model picked option 2
```

Against the real stack (Simsland on :8000 — restart its container once so the new `/mw` routes load —
and Ollama on the host):

```bash
cp .env.example .env    # set OLLAMA_BASE_URL / OLLAMA_MODEL if not the defaults
uvicorn simsland_mw.main:app --port 8100

curl localhost:8100/characters                              # ids + whether they're middleware-driven
curl localhost:8100/characters/<id>/preview                 # exact prompt + options, no LLM call
curl -X POST localhost:8100/characters/<id>/decide          # asks Ollama, DRY RUN (nothing executes)
curl -X POST "localhost:8100/characters/<id>/decide?dry_run=false"   # actually does it
curl -X POST localhost:8100/characters/<id>/enable -H 'content-type: application/json' -d '{"enabled": true}'
curl -X POST localhost:8100/runner/start                    # background loop for enabled characters
```

Or set `MW_MANAGE_CHARACTERS=id1,id2` and `MW_AUTODRIVE=true`. `GET /data-types` lists the registry;
`GET /decisions` shows what the runner recently did, including the full prompt and every rejected reply.

## Changes inside Simsland (`backend/`)

Deliberately small; the middleware only touches Simsland through these:

- `api/middleware_bridge.py` (new, `/mw/*`): per-character snapshot split into sections
  (`meta, character, environment, household, actions`), `/mw/due`, `/mw/characters/{id}/external_brain`,
  and `/mw/characters/{id}/execute`, which runs the decision through the normal
  `process_decision -> validate_action -> route_action` path under the world lock.
  Other characters' bodies, memories and thoughts are stripped at this boundary.
- `brain/external_brain.py` (new): heartbeat + "is this character middleware-driven right now?"
- `brain/agent_loop.py`: 7 lines in `update_agent` so a middleware-driven character skips the built-in `think()`.
- `main.py`: registers the router.

**Safety valves.** A character is only middleware-driven while the middleware has talked to Simsland in the
last 30s (`MIDDLEWARE_ALIVE_SECONDS`) — if the service dies, the built-in brain resumes on its own.
Characters in a conversation, or woken by `heard_speech` / `provoked`, are also handed to the built-in brain,
because Phase 1 can't yet speak in its own words (that's Phase 2).

## Layout (spec section 12, under a `simsland_mw` package)

```
simsland_mw/
  simulation/   client.py (the only file that knows Simsland's URLs), mock.py (offline world)
  data/         provider.py, registry.py, resolver.py (waves + asyncio.gather + TTL cache), providers/
  narrative/    semantic.py (numbers -> meaning), perception.py (leak guard), compiler.py (consciousness snapshot)
  decisions/    options.py (rules), validator.py (rejection rules), executor.py
  cognition/    engine.py (sequences the stages), decisions.py (profiles + prompt), runner.py (wake loop)
  sessions/     one CharacterSession per character: a working set, never the source of truth
  llm/          client.py (interface), ollama.py (schema-constrained output, JSON fallback)
  api/, main.py, cli.py, config.py
```

Adding things: a new semantic data type is one `DataProvider` in `data/providers/`; a new option is one function
in `decisions/options.py` (append to `DEFAULT_RULES`); neither touches the LLM contract.

## Known gaps

- **Not yet run against the live Simsland.** The bridge and client are contract-tested together (real bridge
  code driven through real HTTP-client code with a fake world), and the `/execute` route compiles, but it has not
  been exercised against a running backend. Try `/decide` (dry run) on one character first.
- Option coverage is what Simsland exposes by name today: eat from a fridge, bathroom, drink, sleep / sit and rest,
  raise a missed expectation or frustration with someone present, chat, wait. "Order delivery" from the spec is
  not offered yet (needs the item catalog and a way to check affordability). Prop interactions are matched by
  name/tag in `AFFORDANCES` (`options.py`) — extend as templates are added.
- Speech lines are templated in Phase 1; the model only picks.
- If the model can't produce a valid choice after one corrective retry, the highest-priority rule option runs and
  the decision record is flagged `fallback`.
