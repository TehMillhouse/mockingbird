"""Phrase <-> token conversion.

Token stream layout:

    BOS MODE_x METER_x DIFF_x STYLE_x RANGE_x [PICKUP]
    (P<midi> | REST) D<ticks> [TIE] ... BAR [REMAIN_k] ... EOS

Bar lines are emitted whenever the cumulative duration reaches a bar boundary, so a
well-formed stream never needs a note to cross a bar: `normalize` splits such notes
into tied pieces beforehand and also splits durations that are not in the vocabulary.
In phrases whose last bar is the last bar of the original piece, each of the last
COUNTDOWN bars starts with REMAIN_k (k bars left including this one), so the model
sees an ending approaching the way the source pieces do.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schema import Note, Phrase
from .theory import DURATIONS, METERS, PITCH_MAX, PITCH_MIN, bar_ticks

PAD, BOS, EOS, BAR, TIE, REST, PICKUP = "PAD", "BOS", "EOS", "BAR", "TIE", "REST", "PICKUP"
COUNTDOWN = 4
REMAIN = tuple(f"REMAIN_{k}" for k in range(1, COUNTDOWN + 1))
MODES = ("major", "minor")
STYLES = ("folk", "chorale", "renaissance", "lied")
RANGES = ("S", "A", "T", "B")
DIFFICULTIES = (1, 2, 3, 4, 5)


def _build_vocab() -> list[str]:
    toks = [PAD, BOS, EOS, BAR, TIE, REST, PICKUP, *REMAIN]
    toks += [f"MODE_{m}" for m in MODES]
    toks += [f"METER_{m.replace('/', '_')}" for m in METERS]
    toks += [f"DIFF_{d}" for d in DIFFICULTIES]
    toks += [f"STYLE_{s}" for s in STYLES]
    toks += [f"RANGE_{r}" for r in RANGES]
    toks += [f"P{p}" for p in range(PITCH_MIN, PITCH_MAX + 1)]
    toks += [f"D{d}" for d in DURATIONS]
    return toks


VOCAB: list[str] = _build_vocab()
TOKEN_TO_ID: dict[str, int] = {t: i for i, t in enumerate(VOCAB)}
VOCAB_SIZE = len(VOCAB)

PITCH_IDS = tuple(TOKEN_TO_ID[f"P{p}"] for p in range(PITCH_MIN, PITCH_MAX + 1))
DURATION_IDS = tuple(TOKEN_TO_ID[f"D{d}"] for d in DURATIONS)
ID_TO_PITCH = {TOKEN_TO_ID[f"P{p}"]: p for p in range(PITCH_MIN, PITCH_MAX + 1)}
ID_TO_DURATION = {TOKEN_TO_ID[f"D{d}"]: d for d in DURATIONS}
PREFIX_LEN = 6  # BOS MODE METER DIFF STYLE RANGE (PICKUP is optional and follows)

# Metric position classes for the model's optional bar/tick embeddings.
MAX_BAR_INDEX = 40          # windows have at most 32 bars plus a pickup; clamp beyond
TICK_STEP = 3               # smallest duration on the grid
BAR_TICK_CLASSES = 64       # 0..62 = tick // 3 within the bar, 63 = "at the bar line"
BAR_LINE_CLASS = BAR_TICK_CLASSES - 1


def tid(token: str) -> int:
    return TOKEN_TO_ID[token]


def split_duration(ticks: int) -> list[int]:
    """Greedy split into vocabulary durations, largest first."""
    out: list[int] = []
    rest = ticks
    for d in sorted(DURATIONS, reverse=True):
        while rest >= d:
            out.append(d)
            rest -= d
    if rest:
        raise ValueError(f"duration {ticks} not representable on the 3-tick grid")
    return out


def normalize(phrase: Phrase) -> Phrase:
    """Split notes at bar lines and into vocabulary durations, adding ties."""
    bt = bar_ticks(phrase.meter)
    pos = (-phrase.pickup_ticks) % bt if phrase.pickup_ticks else 0
    out: list[Note] = []
    for n in phrase.notes:
        remaining = n.duration
        while remaining > 0:
            room = bt - pos
            piece = min(remaining, room)
            remaining -= piece
            parts = split_duration(piece)
            for i, d in enumerate(parts):
                last_piece = remaining == 0 and i == len(parts) - 1
                tie = (n.tie if last_piece else True) and n.pitch is not None
                out.append(Note(pitch=n.pitch, duration=d, tie=tie))
            pos = (pos + piece) % bt
    return phrase.model_copy(update={"notes": out})


def prefix_tokens(mode: str, meter: str, difficulty: int, style: str, range_bucket: str,
                  pickup: bool = False) -> list[int]:
    toks = [
        tid(BOS),
        tid(f"MODE_{mode}"),
        tid(f"METER_{meter.replace('/', '_')}"),
        tid(f"DIFF_{difficulty}"),
        tid(f"STYLE_{style}"),
        tid(f"RANGE_{range_bucket}"),
    ]
    if pickup:
        toks.append(tid(PICKUP))
    return toks


def encode(phrase: Phrase, *, difficulty: int | None = None,
           range_bucket: str | None = None) -> list[int]:
    """Encode a normalized phrase. Raises if a note crosses a bar or has a bad duration."""
    diff = difficulty if difficulty is not None else (phrase.difficulty or 3)
    rng = range_bucket or phrase.range_bucket or "S"
    toks = prefix_tokens(phrase.mode, phrase.meter, diff, phrase.style, rng,
                         pickup=phrase.pickup_ticks > 0)
    bt = bar_ticks(phrase.meter)
    pos = (-phrase.pickup_ticks) % bt if phrase.pickup_ticks else 0
    countdown = _countdown_starts(phrase) if phrase.is_ending else {}
    total = 0
    for n in phrase.notes:
        if total in countdown:
            toks.append(tid(f"REMAIN_{countdown.pop(total)}"))
        total += n.duration
        if n.duration not in DURATIONS:
            raise ValueError(f"duration {n.duration} not in vocabulary; call normalize()")
        if pos + n.duration > bt:
            raise ValueError("note crosses bar line; call normalize()")
        if n.pitch is None:
            toks.append(tid(REST))
        else:
            if not PITCH_MIN <= n.pitch <= PITCH_MAX:
                raise ValueError(f"pitch {n.pitch} outside frame window")
            toks.append(tid(f"P{n.pitch}"))
        toks.append(tid(f"D{n.duration}"))
        if n.tie and n.pitch is not None:
            toks.append(tid(TIE))
        pos += n.duration
        if pos == bt:
            toks.append(tid(BAR))
            pos = 0
    toks.append(tid(EOS))
    return toks


def _countdown_starts(phrase: Phrase) -> dict[int, int]:
    """Map tick offset of each of the last COUNTDOWN bar starts -> bars remaining."""
    bt = bar_ticks(phrase.meter)
    total = phrase.total_ticks()
    if total == 0:
        return {}
    starts = [0]
    t = phrase.pickup_ticks if phrase.pickup_ticks else bt
    while t < total:
        starts.append(t)
        t += bt
    return {s: len(starts) - i for i, s in enumerate(starts) if len(starts) - i <= COUNTDOWN}


@dataclass
class Decoded:
    phrase: Phrase
    complete_bars: int  # full bars closed by BAR; an incomplete pickup bar is not counted
    trailing_ticks: int  # ticks after the last BAR (0 if the stream ended on a bar line)


def decode(tokens: list[int], *, source: str = "") -> Decoded:
    """Decode a token stream. Tolerates a missing EOS and trailing partial bars."""
    if len(tokens) < PREFIX_LEN or tokens[0] != tid(BOS):
        raise ValueError("stream must start with the conditioning prefix")
    names = [VOCAB[t] for t in tokens]
    mode = names[1].removeprefix("MODE_")
    meter = names[2].removeprefix("METER_").replace("_", "/")
    difficulty = int(names[3].removeprefix("DIFF_"))
    style = names[4].removeprefix("STYLE_")
    rng = names[5].removeprefix("RANGE_")
    i = PREFIX_LEN
    has_pickup = i < len(names) and names[i] == PICKUP
    if has_pickup:
        i += 1
    bt = bar_ticks(meter)
    notes: list[Note] = []
    pos = 0
    bars = 0
    first_bar_at: int | None = None
    total = 0
    is_ending = False
    while i < len(names):
        t = names[i]
        if t == EOS:
            break
        if t.startswith("REMAIN_"):
            is_ending = True
            i += 1
            continue
        if t == BAR:
            if first_bar_at is None:
                first_bar_at = total
                if not (has_pickup and total % bt):
                    bars += 1
            else:
                bars += 1
            pos = 0
            i += 1
            continue
        if t == REST or t.startswith("P"):
            pitch = None if t == REST else int(t[1:])
            if i + 1 >= len(names) or not names[i + 1].startswith("D"):
                break  # truncated stream
            dur = int(names[i + 1][1:])
            i += 2
            tie = False
            if i < len(names) and names[i] == TIE:
                tie = pitch is not None
                i += 1
            notes.append(Note(pitch=pitch, duration=dur, tie=tie))
            pos += dur
            total += dur
            continue
        raise ValueError(f"unexpected token {t} at {i}")
    pickup = (first_bar_at % bt) if (has_pickup and first_bar_at is not None) else 0
    phrase = Phrase(mode=mode, meter=meter, style=style, notes=notes, pickup_ticks=pickup,
                    is_ending=is_ending, range_bucket=rng, difficulty=difficulty, source=source)
    return Decoded(phrase=phrase, complete_bars=bars, trailing_ticks=pos)


def _build_token_tables() -> tuple[list[int], list[int], dict[int, int]]:
    """Per-token-id kind (0 prefix-like, 1 BAR, 2 duration, 3 other), duration value, and
    bar length per METER token; used by `metric_positions` to stay fast in pure Python."""
    kind = [3] * VOCAB_SIZE
    durval = [0] * VOCAB_SIZE
    meter_bt: dict[int, int] = {}
    for t, name in enumerate(VOCAB):
        if name == BAR:
            kind[t] = 1
        elif name[:1] == "D" and name[1:].isdigit():
            kind[t] = 2
            durval[t] = int(name[1:])
        elif name == PICKUP or name.startswith(("MODE_", "METER_", "DIFF_", "STYLE_", "RANGE_")) or name == BOS:
            kind[t] = 0
            if name.startswith("METER_"):
                meter_bt[t] = bar_ticks(name.removeprefix("METER_").replace("_", "/"))
    return kind, durval, meter_bt


_KIND, _DURVAL, _METER_BT = _build_token_tables()


def metric_positions(tokens: list[int]) -> tuple[list[int], list[int]]:
    """Per-token (bar index, tick class) derived from the stream itself.

    Prefix tokens sit at bar 0, tick 0. A note or rest token and its duration token
    carry the note's start position; TIE, REMAIN and EOS carry the current position;
    BAR carries the bar it closes with the special bar-line tick class. The pickup bar,
    if any, counts as bar 0 with ticks counted from its own start."""
    n = len(tokens)
    bars = [0] * n
    ticks = [0] * n
    bar = 0
    pos = 0
    start_pos = 0
    bt = 0
    max_tick = BAR_LINE_CLASS - 1
    for i in range(n):
        t = tokens[i]
        k = _KIND[t]
        if k == 0 and (i < PREFIX_LEN or VOCAB[t] == PICKUP):
            if t in _METER_BT:
                bt = _METER_BT[t]
            continue  # bar 0, tick 0
        b = bar if bar < MAX_BAR_INDEX else MAX_BAR_INDEX
        bars[i] = b
        if k == 1:
            ticks[i] = BAR_LINE_CLASS
            bar += 1
            pos = 0
        elif k == 2:
            c = start_pos // TICK_STEP
            ticks[i] = c if c < max_tick else max_tick
            pos += _DURVAL[t]
            if bt and pos > bt:
                pos = bt  # malformed stream: stay at the bar line
        else:
            start_pos = pos
            c = pos // TICK_STEP
            ticks[i] = c if c < max_tick else max_tick
    return bars, ticks


def merge_ties(notes: list[Note]) -> list[Note]:
    """Inverse of the splitting in `normalize`: join tied notes of equal pitch."""
    out: list[Note] = []
    for n in notes:
        if out and out[-1].tie and out[-1].pitch == n.pitch and n.pitch is not None:
            out[-1] = Note(pitch=n.pitch, duration=out[-1].duration + n.duration, tie=n.tie)
        else:
            out.append(n.model_copy())
    return out
