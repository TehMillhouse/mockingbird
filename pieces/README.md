# Choir pieces

The pieces the practice page serves (see `docs/FRONTEND.md`). Only files whose source
allows passing them on belong here. Pieces kept for private practice go in
`custom_pieces/` next to this directory: git ignores it, and the server serves both.
Where both hold a file of the same name, the one here wins. A private piece records
where it comes from in its MusicXML `<identification><source>`.

| Files | Work | Source | License |
|---|---|---|---|
| `wo-05`, `wo-09`, `wo-12`, `wo-17`, `wo-23`, `wo-28`, `wo-33`, `wo-35` | Bach, Weihnachtsoratorium BWV 248, chorales of parts I–III | notes from the music21 corpus (`bach/bwv248.*`); the oratorio's text laid under every voice | the music21 corpus terms (distributed with the encoders' permission); the work is public domain |
| `wo-01`, `wo-21`, `wo-24`, `wo-26` | Bach, Weihnachtsoratorium BWV 248, choruses of parts I–III | CPDL editions by Pothám Imre, kept as received in `sources/cpdl/`; text repaired, No. 1's da capo written out | [CPDL license](https://www.cpdl.org/wiki/index.php/ChoralWiki:CPDL) |

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
