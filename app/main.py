"""
Lekha AI — TDS Reconciliation API

FastAPI application with all routers mounted.

Run:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.upload import router as upload_router
from app.api.reconciliation import router as recon_router
from app.api.reports import router as reports_router
from app.api.chat import router as chat_router
from app.api.company import router as company_router
from app.api.auth import router as auth_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Lekha AI — TDS Reconciliation",
        description="AI-powered TDS reconciliation with 7 LLM-backed agents",
        version="3.0.0",
    )

    # CORS
    if settings.environment == "local":
        # Local dev — allow everything
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,  # can't use credentials with wildcard origin
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        # Production — restricted origins with credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Mount routers
    app.include_router(auth_router, prefix="/api")
    app.include_router(upload_router, prefix="/api")
    app.include_router(recon_router, prefix="/api")
    app.include_router(reports_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(company_router, prefix="/api")

    # Health check (no auth)
    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": "3.0.0",
            "environment": settings.environment,
            "llm_available": bool(settings.groq_api_key),
        }

    return app


app = create_app()
