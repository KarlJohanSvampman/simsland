from fastapi import APIRouter, UploadFile, File
from pathlib import Path
import json
import shutil

router = APIRouter()

RESOURCES = Path("/resources")

MESHBANK_FILE = (
    RESOURCES /
    "meshbank.json"
)


def load_meshbank():

    if not MESHBANK_FILE.exists():

        return {}

    with open(
        MESHBANK_FILE,
        "r"
    ) as f:

        return json.load(f)


def save_meshbank(data):

    RESOURCES.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        MESHBANK_FILE,
        "w"
    ) as f:

        json.dump(
            data,
            f,
            indent=2
        )


# ==========================
# GET
# ==========================

@router.get("/meshbank")
def get_meshbank():

    return load_meshbank()


# ==========================
# SAVE
# ==========================

@router.post("/meshbank")
def update_meshbank(
    data: dict
):

    save_meshbank(data)

    return {
        "ok": True
    }


# ==========================
# UPLOAD
# ==========================

@router.post("/assets/upload")
async def upload_asset(

    category: str,

    file: UploadFile = File(...)
):

    target_dir = (
        RESOURCES /
        category
    )

    target_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    target = (
        target_dir /
        file.filename
    )

    with open(
        target,
        "wb"
    ) as buffer:

        shutil.copyfileobj(
            file.file,
            buffer
        )

    return {

        "ok": True,

        "path":
            f"/resources/{category}/{file.filename}"
    }