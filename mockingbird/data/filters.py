"""Quality filters and near-duplicate control for training windows."""
from __future__ import annotations

import hashlib
from collections import defaultdict

from ..schema import Phrase
from ..tokenizer import merge_ties

MAX_RANGE = 19
MIN_NOTES = 8
MAX_REST_SHARE = 0.4
MAX_DUPLICATES_PER_CLUSTER = 3


def reject_reason(phrase: Phrase) -> str | None:
    notes = [n for n in phrase.notes if n.pitch is not None]
    if len(notes) < MIN_NOTES:
        return "too_few_notes"
    ps = [n.pitch for n in notes]
    if max(ps) - min(ps) > MAX_RANGE:
        return "range_too_wide"
    total = phrase.total_ticks()
    rest = sum(n.duration for n in phrase.notes if n.pitch is None)
    if total and rest / total > MAX_REST_SHARE:
        return "too_many_rests"
    return None


def signature(phrase: Phrase) -> str:
    """Hash of the interval/duration skeleton, transposition- and tie-invariant."""
    merged = [n for n in merge_ties(phrase.notes) if n.pitch is not None]
    ivs = [b.pitch - a.pitch for a, b in zip(merged, merged[1:])]
    durs = [n.duration for n in merged]
    return hashlib.sha1(f"{ivs}|{durs}".encode()).hexdigest()


def coarse_signature(phrase: Phrase) -> str:
    """Looser key for near-duplicates: interval contour signs plus bar count."""
    merged = [n for n in merge_ties(phrase.notes) if n.pitch is not None]
    signs = "".join("u" if b.pitch > a.pitch else "d" if b.pitch < a.pitch else "s"
                    for a, b in zip(merged, merged[1:]))
    return hashlib.sha1(f"{signs[:40]}|{len(merged)//4}".encode()).hexdigest()


def dedup(phrases: list[Phrase]) -> tuple[list[Phrase], int]:
    seen_exact: set[str] = set()
    clusters: dict[str, int] = defaultdict(int)
    out: list[Phrase] = []
    dropped = 0
    for ph in phrases:
        sig = signature(ph)
        if sig in seen_exact:
            dropped += 1
            continue
        seen_exact.add(sig)
        c = coarse_signature(ph)
        if clusters[c] >= MAX_DUPLICATES_PER_CLUSTER:
            dropped += 1
            continue
        clusters[c] += 1
        out.append(ph)
    return out, dropped
