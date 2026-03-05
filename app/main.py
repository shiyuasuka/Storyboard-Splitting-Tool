from __future__ import annotations

from fastapi import FastAPI

from app.routers import export, generate, health, novel, projects, ui

app = FastAPI(title="Auto Quasi-Storyboard Manga Drama Platform", version="1.0.0")

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(novel.router)
app.include_router(ui.router)
app.include_router(generate.router)
app.include_router(export.router)


@app.get("/")
async def root() -> dict:
    return {
        "service": "auto-quasi-storyboard-platform",
        "version": "1.0.0",
        "docs": "/docs",
    }
