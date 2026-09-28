"""OpenScore Lieder loader: MuseScore files read with ms3, vocal staff only.

Only MuseScore 3 files are parseable without MuseScore installed; the remaining
MuseScore 2 files in the corpus are reported as rejects.
"""
from __future__ import annotations

import logging
import warnings
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import Phrase
from .extract import VOCAL_PART_RE, MeasureData, ScoreContext, phrases_from_measures

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)  # ms3 is very chatty about layout details

LIEDER_DIR = Path("data/external/Lieder/scores")


def list_files(root: Path = LIEDER_DIR):
    if not root.exists():
        return
    for p in sorted(root.rglob("*.mscx")):
        rel = p.relative_to(root)
        yield "lieder/" + "/".join(rel.parts[:-1]).replace(" ", "_")[:80], p


def _vocal_staff(parts: dict) -> int | None:
    """First single-staff part whose name looks vocal; else the first single-staff part."""
    single = []
    for part in parts.values():
        staves = part.get("staves", [])
        if len(staves) != 1:
            continue
        name = " ".join(str(part.get(k, "")) for k in ("instrument", "trackName", "longName"))
        if VOCAL_PART_RE.search(name):
            return int(staves[0])
        single.append(int(staves[0]))
    return single[0] if single else None


def _events_for_measure(rows, act_dur: Fraction) -> list[tuple[int | None, float, bool, bool]]:
    """Collapse a measure's note rows (one staff) into a monophonic event list with
    rests in the gaps. Simultaneous onsets keep the highest pitch; overlapping notes
    are cut at the next onset."""
    by_onset: dict[Fraction, tuple[int, Fraction, bool]] = {}
    for r in rows:
        onset = Fraction(r.mc_onset)
        dur = Fraction(r.duration)
        if dur <= 0:
            continue
        tie = not pd.isna(r.tied) and int(r.tied) in (0, 1)
        cur = by_onset.get(onset)
        if cur is None or r.midi > cur[0]:
            by_onset[onset] = (int(r.midi), dur, tie)
    events: list[tuple[int | None, float, bool, bool]] = []
    pos = Fraction(0)
    for onset in sorted(by_onset):
        pitch, dur, tie = by_onset[onset]
        if onset > pos:
            events.append((None, float((onset - pos) * 4), False, False))
            pos = onset
        elif onset < pos:
            continue  # swallowed by a longer previous note
        nxt = min((o for o in by_onset if o > onset), default=act_dur)
        end = min(onset + dur, nxt, act_dur)
        if end <= pos:
            continue
        events.append((pitch, float((end - pos) * 4), tie and end == onset + dur, False))
        pos = end
    if pos < act_dur:
        events.append((None, float((act_dur - pos) * 4), False, False))
    return events


def extract_mscx(path: Path, source_id: str, style: str = "lied") -> tuple[list[Phrase], list[tuple[str, str]]]:
    import ms3

    try:
        score = ms3.Score(str(path), read_only=True)
    except ValueError:
        return [], [(source_id, "musescore2_file")]
    except Exception as e:  # noqa: BLE001
        return [], [(source_id, f"parse_error:{type(e).__name__}")]
    try:
        parts = score.mscx.metadata.get("parts", {})
        staff = _vocal_staff(parts)
        if staff is None:
            return [], [(source_id, "no_vocal_staff")]
        notes = score.mscx.notes()
        measures = score.mscx.measures()
        if "gracenote" in notes.columns:
            notes = notes[notes["gracenote"].isna()]
        hist = np.zeros(12)
        for midi, dur in zip(notes["midi"], notes["duration"]):
            hist[int(midi) % 12] += float(Fraction(dur) * 4)
        lowest_staff = int(notes["staff"].max())
        low = notes[notes["staff"] == lowest_staff]
        final_pc = None
        if len(low) and lowest_staff != staff:
            last_mc = low["mc"].max()
            last = low[low["mc"] == last_mc]
            last = last[last["mc_onset"] == last["mc_onset"].max()]
            final_pc = int(last["midi"].min()) % 12
        ctx = ScoreContext(hist=hist, final_pc=final_pc, polyphonic=lowest_staff != staff)

        vocal = notes[notes["staff"] == staff]
        grouped = {mc: rows for mc, rows in vocal.groupby("mc")}
        mdata: list[MeasureData] = []
        for m in measures.itertuples(index=False):
            num, den = (int(x) for x in str(m.timesig).split("/"))
            act = Fraction(m.act_dur)
            rows = grouped.get(m.mc)
            events = _events_for_measure(list(rows.itertuples(index=False)), act) if rows is not None \
                else [(None, float(act * 4), False, False)]
            keysig = None if pd.isna(m.keysig) else int(m.keysig)
            mdata.append(MeasureData(num, den, keysig, events))
    except Exception as e:  # noqa: BLE001
        return [], [(source_id, f"error:{type(e).__name__}")]
    return phrases_from_measures(mdata, ctx, source_id, style)
