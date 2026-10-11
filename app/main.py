"""FastAPI application entry point."""

from fastapi import FastAPI

from app.web.health import router as health_router

app = FastAPI(title="IntakeFlow")
app.include_router(health_router)
