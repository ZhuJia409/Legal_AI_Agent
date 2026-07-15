from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1.case_analyses import router as case_analyses_router
from app.api.v1.contract_reviews import router as contract_reviews_router
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Legal AI Agent API",
        version="0.1.0",
        description="Backend API for legal AI agent workflows.",
    )
    app.include_router(health_router)
    app.include_router(case_analyses_router)
    app.include_router(contract_reviews_router)
    return app


app = create_app()
