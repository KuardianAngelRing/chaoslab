from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.database import SessionLocal, init_db
from app.db.repositories import AppRepository
from app.db.seed import seed_data
from app.routers import pages, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    session = SessionLocal()
    try:
        if not AppRepository(session).list_all():
            seed_data(session)
    finally:
        session.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(pages.router)
app.include_router(stream.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": settings.app_name}
