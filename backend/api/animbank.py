from fastapi import APIRouter
from pathlib import Path
import json

router = APIRouter()

RESOURCES      = Path("/resources")
ANIMBANK_FILE  = RESOURCES / "animbank.json"


# =========================================================
# HELPERS
# =========================================================

def load_animbank():
    if not ANIMBANK_FILE.exists():
        return {}
    with open(ANIMBANK_FILE) as f:
        return json.load(f)


def save_animbank(data):
    RESOURCES.mkdir(parents=True, exist_ok=True)
    with open(ANIMBANK_FILE, "w") as f:
        json.dump(data, f, indent=2)


# =========================================================
# ROUTES
# =========================================================

@router.get("/animbank")
def get_animbank():
    return load_animbank()


@router.post("/animbank")
def update_animbank(data: dict):
    save_animbank(data)
    return {"ok": True}
