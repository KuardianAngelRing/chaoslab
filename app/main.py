from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.database import SessionLocal, init_db
from app.db.repositories import AppRepository
from app.db.seed import seed_data
from app.deps import make_tunnel
from app.routers import apps, builds, experiments, handoffs, pages, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # mock seed는 stub 모드 전용 — real 모드는 실제 등록 데이터만 표시
    if not settings.use_real_services:
        session = SessionLocal()
        try:
            if not AppRepository(session).list_all():
                seed_data(session)
        finally:
            session.close()
    tunnel = make_tunnel()
    await tunnel.start()
    try:
        yield
    finally:
        await tunnel.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(pages.router)
app.include_router(apps.router)
app.include_router(stream.router)
app.include_router(builds.router)
app.include_router(experiments.router)
app.include_router(handoffs.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": settings.app_name}
