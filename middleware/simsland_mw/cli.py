"""
Try the pipeline without Docker or Ollama:

    python -m simsland_mw.cli --mock            # prompt + options for the dinner scenario
    python -m simsland_mw.cli --mock --ask 2    # ...and pretend the model picked option 2

Against the real stack (Simsland on :8000, Ollama on :11434):

    python -m simsland_mw.cli --char <character_id>           # preview only
    python -m simsland_mw.cli --char <character_id> --decide  # ask Ollama, DRY RUN
    python -m simsland_mw.cli --char <character_id> --decide --execute
"""

from __future__ import annotations

import argparse
import asyncio
import json

from .cognition.engine import CognitionEngine
from .config import get_settings
from .llm.ollama import OllamaClient
from .simulation.client import SimClient
from .simulation.mock import MockSimClient


class _ScriptedLLM:
    def __init__(self, pick):
        self.pick = pick

    async def choose(self, messages, option_ids):
        return json.dumps({"choice": self.pick})

    async def aclose(self):
        return None


async def _main(args) -> None:
    settings = get_settings()
    if args.mock:
        sim, char = MockSimClient(), "kim"
        llm = _ScriptedLLM(args.ask if args.ask is not None else 1)
    else:
        if not args.char:
            raise SystemExit("--char is required unless --mock")
        sim, char = SimClient(settings.sim_base_url, settings.sim_timeout), args.char
        llm = OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_num_ctx,
                           settings.ollama_keep_alive, settings.ollama_temperature, settings.llm_timeout)
    engine = CognitionEngine(sim, llm, settings)
    try:
        if args.decide or args.ask is not None:
            rec = await engine.decide(char, dry_run=not args.execute)
            print(rec.prompt[0]["content"], "\n", rec.prompt[1]["content"], sep="\n")
            print("\n--- decision ---")
            print(json.dumps({k: v for k, v in rec.to_dict().items() if k not in ("prompt", "options")},
                             indent=2, default=str))
        else:
            p = await engine.prepare(char)
            print(p.messages[0]["content"], "\n", p.messages[1]["content"], sep="\n")
            print(f"\n(profile={p.profile}, waves={p.resolution.waves}, errors={p.resolution.errors})")
    finally:
        await sim.aclose()
        await llm.aclose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--char")
    ap.add_argument("--decide", action="store_true", help="also ask the LLM")
    ap.add_argument("--ask", type=int, help="(mock) the option number the fake model picks")
    ap.add_argument("--execute", action="store_true", help="really apply the choice in Simsland")
    asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    main()
