from hacker_hero.core.hashing import score_hash


def test_holydiver_hash():
    assert score_hash(1, 240018, 5, "Filipe o bom") == "519598ae32bfb6be8306100056e5599d828aaf57"


def test_latin1_strict():
    try:
        score_hash(0, 0, 0, "\u0100")
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("expected UnicodeEncodeError")
