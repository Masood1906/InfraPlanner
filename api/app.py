# api/app.py
# FastAPI application factory.

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.dependencies import lifespan
from api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Infra Planner API",
        description="AI-powered Kubernetes infrastructure planning for virtualized Cisco routers.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow the frontend origin to call the API.
    # In production set ALLOWED_ORIGINS to your Vercel URL, e.g.:
    #   ALLOWED_ORIGINS=https://your-project.vercel.app
    # In development "*" is fine because the Vite proxy handles it locally.
    allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
    allowed_origins = [
        o.strip() for o in allowed_origins_env.split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    app.include_router(router, prefix="/api/v1")
    return app
