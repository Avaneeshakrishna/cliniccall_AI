from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routes import api_router
from .seed import seed_data

app = FastAPI(title="ClinicCall AI API")
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_data()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(api_router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
