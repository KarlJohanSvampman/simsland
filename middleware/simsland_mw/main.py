"""
Simsland AI middleware -- standalone service.

    uvicorn simsland_mw.main:app --port 8100

The LLM never calls Simsland. This service is the only thing that reads
simulation state and writes outcomes back.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import characters, health, situations
from .cognition.engine import CognitionEngine
from .cognition.runner import Runner
from .config import get_settings
from .llm.ollama import OllamaClient
from .simulation.client import SimClient

log = logging.getLogger("simsland_mw")


def create_app(sim=None, llm=None, settings=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.sim = sim or SimClient(settings.sim_base_url, settings.sim_timeout)
        app.state.llm = llm or OllamaClient(
            settings.ollama_base_url, settings.ollama_model, settings.ollama_num_ctx,
            settings.ollama_keep_alive, settings.ollama_temperature, settings.llm_timeout)
        app.state.engine = CognitionEngine(app.state.sim, app.state.llm, settings)
        app.state.runner = Runner(app.state.engine, settings.poll_interval, settings.max_concurrency)

        for cid in [c.strip() for c in settings.manage_characters.split(",") if c.strip()]:
            try:
                await app.state.sim.set_external_brain(cid, True)
            except Exception as e:  # noqa: BLE001
                log.warning("could not enable %s: %s", cid, e)
        if settings.autodrive:
            app.state.runner.start()
        try:
            yield
        finally:
            await app.state.runner.stop()
            await app.state.sim.aclose()
            await app.state.llm.aclose()

    app = FastAPI(title="Simsland AI Middleware", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(characters.router)
    app.include_router(situations.router)
    return app


app = create_app()
