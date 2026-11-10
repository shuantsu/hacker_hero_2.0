import re
from pathlib import Path

import pytest

from hacker_hero.core import scores_codec

EXAMPLES = Path("example .INIs")


def _hex_values(text):
    vals = []
    for m in re.finditer(r"(?m)^\s*scores[A-Za-z_]*\s*=\s*([0-9a-fA-F]+)\s*$", text):
        vals.append(m.group(1))
    return vals


def test_all_blobs_decode_and_roundtrip():
    assert EXAMPLES.is_dir()
    count = 0
    for p in sorted(EXAMPLES.glob("*.ini")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for hexstr in _hex_values(text):
            obj = scores_codec.loads(bytes.fromhex(hexstr))
            out = scores_codec.dumps(obj)
            obj2 = scores_codec.loads(out)
            assert obj == obj2
            count += 1
    assert count > 0


def test_empty_dict_roundtrip():
    data = scores_codec.dumps({})
    assert scores_codec.loads(data) == {}


def test_holydiver_structure():
    text = (EXAMPLES / "holydiver.ini").read_text()
    m = re.search(r"scores\s*=\s*([0-9a-fA-F]+)", text)
    obj = scores_codec.loads(bytes.fromhex(m.group(1)))
    assert obj == {1: [(240018, 5, "Filipe o bom", "519598ae32bfb6be8306100056e5599d828aaf57")]}
