# Choir pieces

The pieces the practice page serves by default (see `docs/FRONTEND.md`). Only files
whose source allows passing them on belong here; pieces kept for private practice go
elsewhere and are served by pointing `$MOCKINGBIRD_PIECES` at them.

| Files | Work | Source | License |
|---|---|---|---|
| `wo-05`, `wo-09`, `wo-12`, `wo-17`, `wo-23`, `wo-28`, `wo-33`, `wo-35` | Bach, Weihnachtsoratorium BWV 248, chorales of parts I–III | notes from the music21 corpus (`bach/bwv248.*`); the oratorio's text laid under every voice | the music21 corpus terms (distributed with the encoders' permission); the work is public domain |
| `elias-11` | Mendelssohn, Elias op. 70, No. 11 "Baal, erhöre uns!" | transcribed from a public-domain vocal score on IMSLP | the work and the edition are public domain |

## Rebuilding

The Weihnachtsoratorium files are built by `tools/pieces/weihnachtsoratorium.py`,
which holds the libretto and the per-piece settings (tempo, where the syllables go,
typos in the sources):

```bash
python tools/pieces/weihnachtsoratorium.py          # all of them
python tools/pieces/weihnachtsoratorium.py 12 24    # only these numbers
```

It prints each file it writes; anything indented below a file name is a problem to
look at, such as a syllable without a note or a word the libretto does not have.
