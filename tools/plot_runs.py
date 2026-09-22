"""Convergence chart for training runs: per-epoch train loss and validation NLL.

    uv run python tools/plot_runs.py out.html models/ablation2/metric models/ablation2/mrope ...

Writes a self-contained HTML file with an inline SVG (no plotting dependency).
Solid lines are validation NLL, dashed lines the training loss (which includes
dropout and label smoothing, so it sits above the validation curve). Hover a point
for its value.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
W, H = 880, 460
ML, MR, MT, MB = 64, 150, 36, 48


def load(run: Path) -> list[dict]:
    return [json.loads(l) for l in (run / "train_log.jsonl").open()]


def render(runs: list[Path], title: str) -> str:
    data = {r.name: load(r) for r in runs}
    max_epoch = max(len(v) for v in data.values())
    ys = [x for v in data.values() for r in v for x in (r["train_loss"], r["val_nll"])]
    lo, hi = min(ys), max(ys)
    lo, hi = lo - 0.02, min(hi, lo + 1.2) + 0.02  # clip the first noisy epochs
    pw, ph = W - ML - MR, H - MT - MB

    def sx(e: float) -> float:
        return ML + (e - 1) / max(1, max_epoch - 1) * pw

    def sy(v: float) -> float:
        return MT + (hi - min(max(v, lo), hi)) / (hi - lo) * ph

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui, sans-serif" font-size="12">']
    parts.append(f'<rect width="{W}" height="{H}" fill="var(--surface)"/>')
    parts.append(f'<text x="{ML}" y="20" font-size="14" font-weight="600" fill="var(--text)">{html.escape(title)}</text>')
    # grid and axes
    step = 0.1 if hi - lo < 0.8 else 0.2
    v = round(lo / step) * step
    while v <= hi + 1e-9:
        if v >= lo:
            y = sy(v)
            parts.append(f'<line x1="{ML}" x2="{ML + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
            parts.append(f'<text x="{ML - 8}" y="{y + 4:.1f}" text-anchor="end" fill="var(--text2)">{v:.2f}</text>')
        v += step
    for e in range(1, max_epoch + 1):
        if e == 1 or e % 5 == 0:
            parts.append(f'<text x="{sx(e):.1f}" y="{MT + ph + 18}" text-anchor="middle" fill="var(--text2)">{e}</text>')
    parts.append(f'<text x="{ML + pw / 2:.0f}" y="{H - 8}" text-anchor="middle" fill="var(--text2)">epoch</text>')
    parts.append(f'<text transform="rotate(-90)" x="{-(MT + ph / 2):.0f}" y="16" text-anchor="middle" fill="var(--text2)">nats / token</text>')
    # series
    legend_y = MT
    for i, (name, rows) in enumerate(data.items()):
        c = SERIES[i % len(SERIES)]
        for key, dash in (("val_nll", ""), ("train_loss", ' stroke-dasharray="6 4"')):
            pts = " ".join(f"{sx(r['epoch']):.1f},{sy(r[key]):.1f}" for r in rows)
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2"{dash} stroke-linejoin="round"/>')
            for r in rows:
                parts.append(f'<circle cx="{sx(r["epoch"]):.1f}" cy="{sy(r[key]):.1f}" r="7" fill="transparent" stroke="none">'
                             f'<title>{html.escape(name)} epoch {r["epoch"]}: {key} {r[key]:.4f}</title></circle>')
        last = rows[-1]
        best = min(rows, key=lambda r: r["val_nll"])
        parts.append(f'<circle cx="{sx(best["epoch"]):.1f}" cy="{sy(best["val_nll"]):.1f}" r="4" fill="{c}" stroke="var(--surface)" stroke-width="2"/>')
        parts.append(f'<text x="{sx(last["epoch"]) + 6:.1f}" y="{sy(last["val_nll"]) + 4:.1f}" fill="var(--text)">'
                     f'{html.escape(name)} {best["val_nll"]:.3f}</text>')
        # legend
        parts.append(f'<line x1="{W - MR + 40}" x2="{W - MR + 64}" y1="{legend_y + 4}" y2="{legend_y + 4}" stroke="{c}" stroke-width="2"/>')
        parts.append(f'<text x="{W - MR + 70}" y="{legend_y + 8}" fill="var(--text)">{html.escape(name)}</text>')
        legend_y += 18
    legend_y += 8
    parts.append(f'<line x1="{W - MR + 40}" x2="{W - MR + 64}" y1="{legend_y + 4}" y2="{legend_y + 4}" stroke="var(--text2)" stroke-width="2"/>'
                 f'<text x="{W - MR + 70}" y="{legend_y + 8}" fill="var(--text2)">validation NLL</text>')
    legend_y += 18
    parts.append(f'<line x1="{W - MR + 40}" x2="{W - MR + 64}" y1="{legend_y + 4}" y2="{legend_y + 4}" stroke="var(--text2)" stroke-width="2" stroke-dasharray="6 4"/>'
                 f'<text x="{W - MR + 70}" y="{legend_y + 8}" fill="var(--text2)">train loss</text>')
    parts.append("</svg>")

    # table view
    rows_html = "".join(
        f"<tr><td>{html.escape(n)}</td><td>{len(v)}</td><td>{min(v, key=lambda r: r['val_nll'])['epoch']}</td>"
        f"<td>{min(r['val_nll'] for r in v):.4f}</td><td>{v[-1]['train_loss']:.4f}</td></tr>" for n, v in data.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Training convergence</title>
<style>
:root {{ --surface:#fcfcfb; --text:#0b0b0b; --text2:#52514e; --grid:#e6e5e1; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --surface:#1a1a19; --text:#fff; --text2:#c3c2b7; --grid:#33322f; }} }}
body {{ background: var(--surface); color: var(--text); font-family: system-ui, sans-serif; margin: 16px; }}
table {{ border-collapse: collapse; margin-top: 12px; font-size: 13px; }} td, th {{ padding: 4px 10px; border-bottom: 1px solid var(--grid); text-align: left; }}
svg {{ max-width: 100%; height: auto; }}
</style></head><body>
{''.join(parts)}
<table><tr><th>run</th><th>epochs</th><th>best epoch</th><th>best val NLL</th><th>final train loss</th></tr>{rows_html}</table>
</body></html>"""


if __name__ == "__main__":
    out = Path(sys.argv[1])
    runs = [Path(p) for p in sys.argv[2:]]
    out.write_text(render(runs, "Training convergence"), encoding="utf-8")
    print(f"wrote {out}")
