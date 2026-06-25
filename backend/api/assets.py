from fastapi import APIRouter
from pathlib import Path

router = APIRouter()

RESOURCE_DIR = Path("/resources")


def scan_glbs(path):

    if not path.exists():
        return []

    return [
        str(p).replace(
            str(RESOURCE_DIR),
            "/resources"
        )
        for p in path.rglob("*.glb")
    ]


@router.get("/assets")
def get_assets():

    return {

        "props": scan_glbs(
            RESOURCE_DIR / "props"
        ),

        "characters": scan_glbs(
            RESOURCE_DIR / "characters"
        ),

        "items": scan_glbs(
            RESOURCE_DIR / "items"
        )
    }