"""FastAPI service: generate levels and export them.

    POST /levels                      GenerateRequest -> Level JSON
    POST /levels/warmup               GenerateRequest -> the built-in warm-up in its key and voice
    GET  /levels/{id}                 Level JSON
    GET  /levels/{id}/export?fmt=abc|musicxml|midi
    GET  /pieces                      choir pieces in $MOCKINGBIRD_PIECES (default pieces/ in the checkout)
    GET  /pieces/{id}                 Piece JSON: parts as sounding events, bars, tempo map, verses
    GET  /pieces/{id}/musicxml        the score, cleaned up for rendering
    GET  /health
    GET  /                            the web app if built, else the abcjs preview page
    GET  /piece.html                  the web app's piece practice page

The web app is read from $MOCKINGBIRD_WEB, by default web/dist in the checkout.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import pieces as piece_store
from ..export.formats import to_abc, to_midi, to_musicxml
from ..schema import GenerateRequest, Level

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_PAGE = ROOT / "tools" / "abc_preview.html"
WEB_DIST = Path(os.environ.get("MOCKINGBIRD_WEB", ROOT / "web" / "dist"))
PIECES = Path(os.environ.get("MOCKINGBIRD_PIECES", ROOT / "pieces"))
# levels are kept for their exports; the oldest are forgotten beyond this many
MAX_LEVELS = 1000


class LevelStore:
    """The most recently generated levels, by id."""

    def __init__(self, size: int = MAX_LEVELS):
        self.size = size
        self._levels: OrderedDict[str, Level] = OrderedDict()

    def add(self, level: Level) -> Level:
        self._levels[level.id] = level
        while len(self._levels) > self.size:
            self._levels.popitem(last=False)
        return level

    def get(self, level_id: str) -> Level:
        if level_id not in self._levels:
            raise HTTPException(404, "unknown level")
        return self._levels[level_id]

    def __len__(self) -> int:
        return len(self._levels)


def create_app(model_path: Path | None = None) -> FastAPI:
    levels = LevelStore()
    state: dict[str, object] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        from ..generate.service import LevelGenerator

        path = model_path or Path(os.environ.get("MOCKINGBIRD_MODEL", "models/melody-v1.pt"))
        state["gen"] = LevelGenerator(path)
        yield

    app = FastAPI(title="Mockingbird", version="0.1", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        gen = state.get("gen")
        return {"ok": gen is not None, "device": getattr(gen, "device", None), "levels": len(levels),
                "copy_check": gen is not None and gen.memo.available}

    def generator():
        gen = state.get("gen")
        if gen is None:
            raise HTTPException(503, "model not loaded")
        return gen

    @app.post("/levels", response_model=Level)
    def create_level(req: GenerateRequest) -> Level:
        from ..generate.service import GenerationFailed

        try:
            return levels.add(generator().generate(req))
        except (ValueError, GenerationFailed) as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/levels/warmup", response_model=Level)
    def create_warmup(req: GenerateRequest) -> Level:
        try:
            return levels.add(generator().warmup(req))
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/levels/{level_id}", response_model=Level)
    def get_level(level_id: str) -> Level:
        return levels.get(level_id)

    @app.get("/levels/{level_id}/export")
    def export_level(level_id: str, fmt: str = "abc"):
        level = levels.get(level_id)
        if fmt == "abc":
            return PlainTextResponse(to_abc(level), media_type="text/vnd.abc")
        if fmt == "musicxml":
            return Response(to_musicxml(level), media_type="application/vnd.recordare.musicxml+xml")
        if fmt in ("midi", "mid"):
            return Response(to_midi(level), media_type="audio/midi",
                            headers={"Content-Disposition": f'attachment; filename="{level_id}.mid"'})
        raise HTTPException(400, "fmt must be abc, musicxml or midi")

    def piece_path(piece_id: str) -> Path:
        path = piece_store.piece_files(PIECES).get(piece_id)
        if path is None:
            raise HTTPException(404, "unknown piece")
        return path

    @app.get("/pieces", response_model=list[piece_store.PieceSummary])
    def list_pieces() -> list[piece_store.PieceSummary]:
        out = []
        for path in piece_store.piece_files(PIECES).values():
            p = piece_store.load_piece(path)
            out.append(piece_store.PieceSummary(id=p.id, title=p.title, composer=p.composer))
        return out

    @app.get("/pieces/{piece_id}", response_model=piece_store.Piece)
    def get_piece(piece_id: str) -> piece_store.Piece:
        return piece_store.load_piece(piece_path(piece_id))

    @app.get("/pieces/{piece_id}/musicxml")
    def get_piece_musicxml(piece_id: str) -> Response:
        return Response(piece_store.musicxml(piece_path(piece_id)),
                        media_type="application/vnd.recordare.musicxml+xml")

    if (WEB_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/")
        def web_app() -> FileResponse:
            return FileResponse(WEB_DIST / "index.html")

        @app.get("/piece.html")
        def piece_page() -> FileResponse:
            return FileResponse(WEB_DIST / "piece.html")
    else:
        @app.get("/", response_class=HTMLResponse)
        def preview() -> str:
            if not PREVIEW_PAGE.exists():
                raise HTTPException(404, "preview page not found")
            return PREVIEW_PAGE.read_text(encoding="utf-8")

    return app


app = create_app()
