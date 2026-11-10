"""INI file helpers (optional thin layer)."""

import configparser
from pathlib import Path


def read_text(path):
    path = Path(path)
    raw = path.read_bytes()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def make_parser():
    return configparser.ConfigParser(interpolation=None)
