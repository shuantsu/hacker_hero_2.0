from pathlib import Path

import pytest

from hacker_hero.core.document import SongDocument


EXAMPLES = Path("example .INIs")


def test_all_examples_load():
    for p in sorted(EXAMPLES.glob("*.ini")):
        doc = SongDocument.load(p)
        assert doc.path == p


def test_roundtrip_preserves_scores_and_extras():
    for p in sorted(EXAMPLES.glob("*.ini")):
        doc = SongDocument.load(p)
        import tempfile, pathlib
        tmp = pathlib.Path(tempfile.gettempdir()) / "rt.ini"
        doc.save(tmp)
        doc2 = SongDocument.load(tmp)
        assert doc.scores == doc2.scores
        assert doc.extra == doc2.extra
        assert doc.other_sections == doc2.other_sections
        assert doc.artist == doc2.artist
        assert doc.name == doc2.name
        assert doc.count == doc2.count
        assert doc.cassettecolor == doc2.cassettecolor


def test_missing_song_section_raises():
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.gettempdir()) / "nosong.ini"
    tmp.write_text("[other]\nfoo=bar\n", encoding="utf-8")
    with pytest.raises(Exception):
        SongDocument.load(tmp)


def test_cleared_field_not_written():
    import tempfile, pathlib
    p = EXAMPLES / "holydiver.ini"
    doc = SongDocument.load(p)
    doc.artist = ""
    doc.count = None
    tmp = pathlib.Path(tempfile.gettempdir()) / "cleared.ini"
    doc.save(tmp)
    text = tmp.read_text()
    assert "artist" not in text
    assert "count" not in text
