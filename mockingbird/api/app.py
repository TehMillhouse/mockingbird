"""FastAPI service: generate levels and export them.

    POST /levels                      GenerateRequest -> Level JSON
    POST /levels/warmup               GenerateRequest -> the built-in warm-up in its key and voice
    GET  /levels/{id}                 Level JSON
    GET  /levels/{id}/export?fmt=abc|musicxml|midi
    GET  /health
    GET  /                            the web app if built, else the abcjs preview page

The web app is read from $MOCKINGBIRD_WEB, by default web/dist in the checkout.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from ..export.formats import to_abc, to_midi, to_musicxml
from ..schema import GenerateRequest, Level

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_PAGE = ROOT / "tools" / "abc_preview.html"
WEB_DIST = Path(os.environ.get("MOCKINGBIRD_WEB", ROOT / "web" / "dist"))


def create_app(model_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Mockingbird", version="0.1")
    levels: dict[str, Level] = {}
    state: dict[str, object] = {}

    @app.on_event("startup")
    def _load() -> None:
        from ..generate.service import LevelGenerator

        path = model_path or Path(os.environ.get("MOCKINGBIRD_MODEL", "models/melody-v1.pt"))
        state["gen"] = LevelGenerator(path)

    @app.get("/health")
    def health() -> dict:
        gen = state.get("gen")
        return {"ok": gen is not None, "device": getattr(gen, "device", None), "levels": len(levels),
                "copy_check": gen is not None and gen.memo.available}

    @app.post("/levels", response_model=Level)
    def create_level(req: GenerateRequest) -> Level:
        gen = state.get("gen")
        if gen is None:
            raise HTTPException(503, "model not loaded")
        try:
            level = gen.generate(req)
        except RuntimeError as e:
            raise HTTPException(422, str(e)) from e
        levels[level.id] = level
        return level

    @app.post("/levels/warmup", response_model=Level)
    def create_warmup(req: GenerateRequest) -> Level:
        gen = state.get("gen")
        if gen is None:
            raise HTTPException(503, "model not loaded")
        level = gen.warmup(req)
        levels[level.id] = level
        return level

    @app.get("/levels/{level_id}", response_model=Level)
    def get_level(level_id: str) -> Level:
        if level_id not in levels:
            raise HTTPException(404, "unknown level")
        return levels[level_id]

    @app.get("/levels/{level_id}/export")
    def export_level(level_id: str, fmt: str = "abc"):
        if level_id not in levels:
            raise HTTPException(404, "unknown level")
        level = levels[level_id]
        if fmt == "abc":
            return PlainTextResponse(to_abc(level), media_type="text/vnd.abc")
        if fmt == "musicxml":
            return Response(to_musicxml(level), media_type="application/vnd.recordare.musicxml+xml")
        if fmt in ("midi", "mid"):
            return Response(to_midi(level), media_type="audio/midi",
                            headers={"Content-Disposition": f'attachment; filename="{level_id}.mid"'})
        raise HTTPException(400, "fmt must be abc, musicxml or midi")

    if (WEB_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/")
        def web_app() -> FileResponse:
            return FileResponse(WEB_DIST / "index.html")
    else:
        @app.get("/", response_class=HTMLResponse)
        def preview() -> str:
            if not PREVIEW_PAGE.exists():
                raise HTTPException(404, "preview page not found")
            return PREVIEW_PAGE.read_text(encoding="utf-8")

    return app


app = create_app()
