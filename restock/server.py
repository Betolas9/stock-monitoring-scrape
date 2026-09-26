from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__, bootstrap, runtime
from .api import router as api_router
from .notify import Dispatcher
from .paths import WEB_DIST
from .scheduler import Scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap.run()
    runtime.dispatcher = Dispatcher()
    runtime.dispatcher.start()
    if app.state.run_scheduler:
        runtime.scheduler = Scheduler(runtime.dispatcher)
        runtime.scheduler.start()
    logger.info(f"{APP_NAME} {__version__} started")
    yield
    if runtime.scheduler:
        runtime.scheduler.stop()
    runtime.dispatcher.stop()


def create_app(run_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan)
    app.state.run_scheduler = run_scheduler
    app.include_router(api_router)

    @app.exception_handler(Exception)
    async def unhandled(_request, exc: Exception):
        logger.exception("API error")
        return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

    index = WEB_DIST / "index.html"
    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        file = WEB_DIST / path
        if path and file.is_file() and WEB_DIST in file.resolve().parents:
            return FileResponse(file)
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            {"detail": "Frontend not built yet: run `npm install && npm run build` in web/ "
                       "(or `npm run dev` for development)."},
            status_code=503,
        )

    return app
