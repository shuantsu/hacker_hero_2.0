"""Song document model (§4.2)."""

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from .errors import DocumentError, ScoresCodecError
from . import scores_codec


class ScoreEntry(NamedTuple):
    score: int
    stars: int
    name: str
    hash: str


DIFFICULTIES = {0: "Amazing", 1: "Medium", 2: "Easy", 3: "Supaeasy"}


def _parse_int_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None


@dataclass
class SongDocument:
    path: Path | None = None
    save_path: Path | None = None
    dirty: bool = False
    artist: str = ""
    name: str = ""
    count: int | None = None
    cassettecolor: str = ""
    scores: dict[int, list[ScoreEntry]] | None = None
    scores_load_warning: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
    other_sections: dict[str, dict[str, str]] = field(default_factory=dict)

    # ---------- loading ----------

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.is_file():
            raise DocumentError(f"file not found: {path}")
        raw = path.read_bytes()
        text = None
        for enc in ("utf-8", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("latin-1")
        cp = configparser.ConfigParser(interpolation=None)
        try:
            cp.read_string(text)
        except configparser.Error as e:
            raise DocumentError(f"cannot parse INI: {e}")

        # find song section case-insensitively
        song_section = None
        for sec in cp.sections():
            if sec.lower() == "song":
                song_section = sec
                break
        if song_section is None:
            raise DocumentError("missing [song] section")

        song = {k.lower(): v for k, v in cp.items(song_section)}

        doc = cls(path=path)
        doc.artist = song.get("artist", "")
        doc.name = song.get("name", "")
        doc.count = _parse_int_or_none(song.get("count"))
        doc.cassettecolor = song.get("cassettecolor", "")

        # scores
        handled = {"artist", "name", "count", "cassettecolor", "scores"}
        scores_hex = song.get("scores")
        doc.scores = None
        doc.scores_load_warning = None
        if scores_hex is not None and scores_hex.strip() != "":
            try:
                obj = scores_codec.loads(bytes.fromhex(scores_hex.strip()))
            except (ScoresCodecError, ValueError) as e:
                doc.scores = None
                doc.scores_load_warning = str(e)
            else:
                try:
                    doc.scores = _validate_scores(obj)
                except (ScoresCodecError, ValueError, TypeError) as e:
                    doc.scores = None
                    doc.scores_load_warning = str(e)
        # extra keys (preserve unknown)
        for k, v in song.items():
            if k in handled:
                continue
            doc.extra[k] = v
        if scores_hex is not None and scores_hex.strip() != "" and doc.scores is None and doc.scores_load_warning:
            doc.extra["scores"] = scores_hex.strip()
        else:
            doc.extra.pop("scores", None)

        # other sections
        for sec in cp.sections():
            if sec.lower() == "song":
                continue
            doc.other_sections[sec] = {k.lower(): v for k, v in cp.items(sec)}

        doc.dirty = False
        return doc

    # ---------- saving ----------

    def save(self, path=None):
        target = path or self.save_path or self.path
        if target is None:
            raise DocumentError("no save path")
        target = Path(target)

        cp = configparser.ConfigParser(interpolation=None)
        cp.add_section("song")
        if self.artist:
            cp.set("song", "artist", self.artist)
        if self.name:
            cp.set("song", "name", self.name)
        if self.count is not None:
            cp.set("song", "count", str(self.count))
        if self.cassettecolor:
            cp.set("song", "cassettecolor", self.cassettecolor)
        if self.scores is not None:
            obj = {}
            for diff, entries in self.scores.items():
                obj[diff] = [tuple(e) for e in entries]
            hexstr = scores_codec.dumps(obj).hex()
            cp.set("song", "scores", hexstr)
        elif "scores" in self.extra:
            cp.set("song", "scores", self.extra["scores"])
        for k, v in self.extra.items():
            if k == "scores":
                continue
            cp.set("song", k, v)

        for sec, items in self.other_sections.items():
            if not cp.has_section(sec):
                cp.add_section(sec)
            for k, v in items.items():
                cp.set(sec, k, v)

        try:
            with open(target, "w", encoding="utf-8", newline="") as f:
                cp.write(f)
        except OSError as e:
            raise DocumentError(f"write failed: {e}")

        if self.path is None:
            self.path = target
        if path is not None:
            self.save_path = Path(path)
        self.dirty = False
        return target

    # ---------- metadata setters ----------

    def set_artist(self, v):
        self.artist = v
        self.dirty = True

    def set_name(self, v):
        self.name = v
        self.dirty = True

    def set_count(self, v):
        self.count = v
        self.dirty = True

    def set_cassettecolor(self, v):
        self.cassettecolor = v
        self.dirty = True

    def set_score_entry(self, diff, idx, score, stars, name, hash_value):
        if self.scores is None:
            self.scores = {}
        if diff not in self.scores:
            self.scores[diff] = []
        lst = self.scores[diff]
        if idx < len(lst):
            lst[idx] = ScoreEntry(score, stars, name, hash_value)
        else:
            lst.append(ScoreEntry(score, stars, name, hash_value))
        self.dirty = True


def _validate_scores(obj):
    if not isinstance(obj, dict):
        raise ScoresCodecError("scores must be dict")
    out = {}
    for k, v in obj.items():
        if isinstance(k, bool) or not isinstance(k, int):
            raise ScoresCodecError("score key must be int")
        if not isinstance(v, list):
            raise ScoresCodecError("score value must be list")
        entries = []
        for e in v:
            if not isinstance(e, (tuple, list)):
                raise ScoresCodecError("entry must be tuple")
            if len(e) != 4:
                raise ScoresCodecError("entry must have 4 fields")
            score, stars, name, h = e
            if isinstance(score, bool) or not isinstance(score, int):
                # allow? require int
                try:
                    score = int(score)
                except (TypeError, ValueError):
                    raise ScoresCodecError("score must be int")
            if isinstance(stars, bool) or not isinstance(stars, int):
                try:
                    stars = int(stars)
                except (TypeError, ValueError):
                    raise ScoresCodecError("stars must be int")
            if not isinstance(name, str):
                raise ScoresCodecError("name must be str")
            if not isinstance(h, str):
                h = str(h)
            entries.append(ScoreEntry(int(score), int(stars), name, h))
        out[int(k)] = entries
    return out


