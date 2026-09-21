"""Runtime configuration, read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Simsland backend (the FastAPI container exposed on the host).
    sim_base_url: str = "http://localhost:8000"
    sim_timeout: float = 30.0

    # Ollama runs on the host machine, next to this service.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:latest"
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "10m"
    ollama_temperature: float = 0.7
    llm_timeout: float = 120.0

    # Wake-up loop (Phase 1: polls Simsland's /mw/due; Phase 3 makes it event driven).
    autodrive: bool = False          # start the background runner on boot
    poll_interval: float = 2.0
    max_concurrency: int = 2         # simultaneous LLM decisions
    manage_characters: str = ""      # comma-separated ids to flag external_brain on boot

    # When true the loop still builds prompts and asks the LLM, but never executes.
    dry_run: bool = False


def get_settings() -> Settings:
    return Settings(
        sim_base_url=os.getenv("SIMSLAND_URL", "http://localhost:8000").rstrip("/"),
        sim_timeout=_f("SIMSLAND_TIMEOUT", 30.0),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:latest"),
        ollama_num_ctx=_i("OLLAMA_NUM_CTX", 8192),
        ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
        ollama_temperature=_f("OLLAMA_TEMPERATURE", 0.7),
        llm_timeout=_f("LLM_TIMEOUT", 120.0),
        autodrive=_b("MW_AUTODRIVE", False),
        poll_interval=_f("MW_POLL_INTERVAL", 2.0),
        max_concurrency=_i("MW_MAX_CONCURRENCY", 2),
        manage_characters=os.getenv("MW_MANAGE_CHARACTERS", ""),
        dry_run=_b("MW_DRY_RUN", False),
    )
