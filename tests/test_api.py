from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mockingbird.api.app import create_app
from mockingbird.schema import Level

MODEL = Path("models/melody-v1.pt")


@pytest.mark.skipif(not MODEL.exists(), reason="trained model not present")
def test_generate_and_export():
    app = create_app(MODEL)
    with TestClient(app) as client:
        assert client.get("/health").json()["ok"] is True
        r = client.post("/levels", json={"tonic": "A", "mode": "minor", "meter": "3/4", "voice": "A",
                                         "difficulty": 2, "bars": 4, "seed": 3})
        assert r.status_code == 200, r.text
        level = Level(**r.json())
        assert level.bars == 4 and level.chords
        abc = client.get(f"/levels/{level.id}/export?fmt=abc")
        assert abc.status_code == 200 and "K:Am" in abc.text
        assert client.get(f"/levels/{level.id}/export?fmt=musicxml").status_code == 200
        midi = client.get(f"/levels/{level.id}/export?fmt=midi")
        assert midi.status_code == 200 and midi.content[:4] == b"MThd"
        assert client.get("/levels/nope").status_code == 404


def test_level_store_forgets_the_oldest():
    from fastapi import HTTPException

    from mockingbird.api.app import LevelStore

    def level(i: int) -> Level:
        return Level(id=f"l{i}", tonic="C", mode="major", meter="4/4", voice="S", difficulty=1, bars=1,
                     tempo_bpm=80, melody=[], chords=[], accompaniment=[])

    store = LevelStore(size=2)
    for i in range(3):
        store.add(level(i))
    assert len(store) == 2 and store.get("l2").id == "l2"
    with pytest.raises(HTTPException):
        store.get("l0")
