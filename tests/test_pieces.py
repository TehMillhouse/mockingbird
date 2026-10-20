"""Choir pieces from MusicXML: playback data and the cleaned-up score."""
from fastapi.testclient import TestClient
from music21 import metadata, meter, note, stream, tempo, tie

from mockingbird import pieces
from mockingbird.api import app as api


def _write_piece(path):
    """A soprano with two lyric lines, a tie and a pickup, over a piano part."""
    sop, piano = stream.Part(), stream.Part()
    sop.partName, piano.partName = "Soprano", "Piano"
    pickup = stream.Measure(number=1)
    pickup.append([meter.TimeSignature("4/4"), tempo.MetronomeMark(number=60)])
    first = note.Note("E4", quarterLength=1)
    first.addLyric("Cast", lyricNumber=1)
    first.addLyric("Wirf", lyricNumber=2)
    pickup.append(first)
    pickup.paddingLeft = 3.0
    full = stream.Measure(number=2)
    held = note.Note("G4", quarterLength=2)
    held.tie = tie.Tie("start")
    held.addLyric("thy", lyricNumber=1)
    held.addLyric("dein", lyricNumber=2)
    rest_of_it = note.Note("G4", quarterLength=2)
    rest_of_it.tie = tie.Tie("stop")
    full.append([held, rest_of_it])
    sop.append([pickup, full])
    piano.append([stream.Measure([meter.TimeSignature("4/4"), note.Note("C3", quarterLength=1)], number=1),
                  stream.Measure([note.Note("C3", quarterLength=4)], number=2)])
    piano.getElementsByClass("Measure")[0].paddingLeft = 3.0
    score = stream.Score([sop, piano])
    score.metadata = metadata.Metadata(title="Wirf dein Anliegen", composer="Mendelssohn")
    score.write("musicxml", fp=str(path))


def test_piece_playback_data(tmp_path):
    path = tmp_path / "elias-15.musicxml"
    _write_piece(path)
    p = pieces.load_piece(path)
    assert (p.id, p.title, p.composer) == ("elias-15", "Wirf dein Anliegen", "Mendelssohn")
    sop, piano = p.parts
    assert (sop.sung, sop.voice, piano.sung, piano.voice) == (True, "S", False, None)
    # the tie becomes one event; ticks are 24 per quarter from the pickup's start
    assert [(e.start, e.duration, e.pitches) for e in sop.events] == [(0, 24, [64]), (24, 96, [67])]
    assert [(m.start, m.duration, m.meter) for m in p.measures] == [(0, 24, "4/4"), (24, 96, "4/4")]
    assert [(t.start, t.bpm) for t in p.tempos] == [(0, 60.0)]
    assert [(v.number, v.incipit) for v in p.verses] == [("1", "Cast thy"), ("2", "Wirf dein")]


def test_soft_hyphen_syllables_are_removed(tmp_path):
    path = tmp_path / "x.musicxml"
    path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise><part-list><score-part id="P1"><part-name>S</part-name></score-part></part-list>
<part id="P1"><measure number="1"><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
<lyric number="2"><syllabic>end</syllabic><text>­</text><elision/><syllabic>begin</syllabic><text>sor</text></lyric>
</note></measure></part></score-partwise>""", encoding="utf-8")
    assert pieces.load_piece(path).title == "x"  # no metadata: the file name
    xml = pieces.musicxml(path)
    assert "­" not in xml and "<elision" not in xml
    assert "<syllabic>begin</syllabic><text>sor</text>" in xml.replace("\n", "")


def test_piece_routes(tmp_path, monkeypatch):
    _write_piece(tmp_path / "elias-15.musicxml")
    monkeypatch.setattr(api, "PIECES", tmp_path)
    client = TestClient(api.create_app())  # no lifespan: the model is not needed for pieces
    assert client.get("/pieces").json() == [{"id": "elias-15", "title": "Wirf dein Anliegen", "composer": "Mendelssohn"}]
    assert client.get("/pieces/elias-15").json()["parts"][0]["name"] == "Soprano"
    assert client.get("/pieces/elias-15/musicxml").text.startswith("<?xml")
    assert client.get("/pieces/nope").status_code == 404
