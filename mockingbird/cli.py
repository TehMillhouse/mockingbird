"""Command-line entry points: `uv run mb --help`."""
from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)
data_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")


@data_app.command("build")
def data_build(
    sources: list[str] = typer.Option(["essen", "bach", "palestrina", "monteverdi", "josquin", "lieder", "pdmx"],
                                      "--source", "-s"),
    out: Path = Path("data/processed"),
    workers: int = 6,
    limit: int | None = None,
):
    """Extract, segment and filter the corpora into train/val JSONL files."""
    from .data.build import build

    build(sources, out_dir=out, workers=workers, limit=limit)


@data_app.command("prepare-pdmx")
def data_prepare_pdmx():
    """Select vocal scores from PDMX.csv and extract their MusicXML from mxl.tar.gz."""
    from .data.pdmx import prepare

    prepare()


@app.command()
def train(
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 5e-4,
    data: Path = Path("data/processed"),
    out: Path = Path("models"),
    n_layer: int = 6,
    d_model: int = 256,
    dropout: float = 0.2,
    pos: str = typer.Option("learned", help="learned | rope | metric_rope | none"),
    metric_emb: bool = True,
    arch: str = typer.Option("stack", help="stack | looped"),
    loop_center: int = 3,
    loop_jitter: int = 1,
    n_core: int = 2,
    sandwich_norm: bool = False,
    anchor_prefix: bool = False,
    seed: int = 0,
    patience: int = 8,
    checkpoint: str = "melody-v1.pt",
):
    """Train the melody model; writes <out>/<checkpoint> and a JSONL training log."""
    from .model import ModelConfig
    from .train import TrainConfig, train as run_train

    run_train(TrainConfig(data_dir=data, out_dir=out, epochs=epochs, batch_size=batch_size, lr=lr,
                          patience=patience, checkpoint_name=checkpoint, seed=seed),
              ModelConfig(n_layer=n_layer, d_model=d_model, d_ff=4 * d_model, dropout=dropout,
                          pos_encoding=pos, metric_emb=metric_emb, arch=arch, loop_center=loop_center,
                          loop_jitter=loop_jitter, n_core=n_core, sandwich_norm=sandwich_norm,
                          anchor_prefix=anchor_prefix))


@app.command()
def generate(
    tonic: str = "C",
    mode: str = "major",
    meter: str = "4/4",
    voice: str = "S",
    difficulty: int = 2,
    bars: int = 8,
    style: str | None = None,
    accompaniment: str = "auto",
    seed: int | None = None,
    out: Path = Path("level.abc"),
    model: Path = Path("models/melody-v1.pt"),
):
    """Generate one level and write it as .abc, .musicxml, .mid or .json (by extension)."""
    from .export.formats import to_abc, to_midi, to_musicxml
    from .generate.service import LevelGenerator
    from .schema import GenerateRequest

    gen = LevelGenerator(model)
    level = gen.generate(GenerateRequest(tonic=tonic, mode=mode, meter=meter, voice=voice,
                                         difficulty=difficulty, bars=bars, style=style,
                                         accompaniment=accompaniment, seed=seed))
    suffix = out.suffix.lower()
    if suffix == ".abc":
        out.write_text(to_abc(level), encoding="utf-8")
    elif suffix in (".musicxml", ".xml"):
        out.write_text(to_musicxml(level), encoding="utf-8")
    elif suffix in (".mid", ".midi"):
        out.write_bytes(to_midi(level))
    else:
        out.write_text(level.model_dump_json(indent=1), encoding="utf-8")
    typer.echo(f"wrote {out} (difficulty score {level.difficulty_score:.1f})")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, model: Path = Path("models/melody-v1.pt")):
    """Run the HTTP API with the preview page at /."""
    import os

    import uvicorn

    os.environ["MOCKINGBIRD_MODEL"] = str(model)
    uvicorn.run("mockingbird.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
