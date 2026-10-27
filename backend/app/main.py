import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import auth, cameras, credentials, devices, employees, events, internal, media, org, scan, users, ws
from app.config import get_settings
from app.services.maintenance import ensure_admin, start_background_jobs
from app.services.streams import close_go2rtc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().media_dir.mkdir(parents=True, exist_ok=True)
    await ensure_admin()
    jobs = start_background_jobs() if app.state.background_jobs else []
    yield
    for job in jobs:
        job.cancel()
    await close_go2rtc()


def create_app(background_jobs: bool = True) -> FastAPI:
    app = FastAPI(
        title="Argus",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.background_jobs = background_jobs
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    origins = get_settings().cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"]
        )

    api = APIRouter(prefix="/api")
    for module in (auth, users, org, devices, credentials, scan, cameras, employees, events, ws, internal, media):
        api.include_router(module.router)

    @api.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    app.include_router(api)
    return app


app = create_app()
