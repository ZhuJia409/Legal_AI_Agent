from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1.analysis import router as analysis_router
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Legal AI Agent API",
        version="0.1.0",
        description="Backend API for legal AI agent workflows.",
    )
    app.include_router(health_router)
    app.include_router(analysis_router)
    return app


app = create_app()
