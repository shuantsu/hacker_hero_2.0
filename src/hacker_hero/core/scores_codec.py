"""Minimal Cerealizer subset for Frets on Fire score blobs (§2.3).

Pure functions: ``loads(data: bytes) -> object``, ``dumps(obj) -> bytes``.
Supports only dict, list, tuple containers and int, str, bool, None refs.
"""

import io
from typing import Any

from .errors import ScoresCodecError


class _Dumper:
    def __init__(self):
        self.objs = []          # non-tuple containers in discovery order
        self.objs_id = set()
        self.priorities = []    # (depth, tuple)
        self.id2id = {}
        self.id2obj: list[Any] = []

    def collect(self, obj):
        t = type(obj)
        if t is dict:
            if id(obj) not in self.objs_id:
                self.objs.append(obj)
                self.objs_id.add(id(obj))
                for k in obj:
                    self.collect(k)
                for v in obj.values():
                    self.collect(v)
        elif t is list:
            if id(obj) not in self.objs_id:
                self.objs.append(obj)
                self.objs_id.add(id(obj))
                for i in obj:
                    self.collect(i)
        elif t is tuple:
            if id(obj) not in self.objs_id:
                self.priorities.append((self._depth(obj), obj))
                self.objs_id.add(id(obj))
                for i in obj:
                    self.collect(i)
        else:
            # primitive / ref type: nothing to collect
            if t not in (int, bool, str, type(None)):
                raise ScoresCodecError(f"unsupported type {t!r}")

    def _depth(self, t):
        depth = 0
        for i in t:
            if isinstance(i, tuple):
                x = self._depth(i)
                if x > depth:
                    depth = x
        return depth + 1

    def dump(self, root):
        self.collect(root)
        # stable sort by depth
        self.priorities.sort(key=lambda x: x[0])
        self.objs.extend(o for _, o in self.priorities)
        for i, o in enumerate(self.objs):
            self.id2id[id(o)] = i

        buf = io.BytesIO()
        buf.write(b"cereal1\n")
        buf.write(f"{len(self.objs)}\n".encode("ascii"))
        for o in self.objs:
            self._dump_obj(o, buf)
        for o in self.objs:
            self._dump_data(o, buf)
        self._dump_ref(root, buf)
        return buf.getvalue()

    def _dump_obj(self, obj, buf):
        t = type(obj)
        if t is dict:
            buf.write(b"dict\n")
        elif t is list:
            buf.write(b"list\n")
        elif t is tuple:
            buf.write(b"tuple\n")
            buf.write(f"{len(obj)}\n".encode("ascii"))
            for i in obj:
                self._dump_ref(i, buf)
        else:
            raise ScoresCodecError(f"bad container {t!r}")

    def _dump_data(self, obj, buf):
        t = type(obj)
        if t is dict:
            buf.write(f"{len(obj)}\n".encode("ascii"))
            for k, v in obj.items():
                self._dump_ref(v, buf)
                self._dump_ref(k, buf)
        elif t is list:
            buf.write(f"{len(obj)}\n".encode("ascii"))
            for i in obj:
                self._dump_ref(i, buf)
        elif t is tuple:
            pass  # empty
        else:
            raise ScoresCodecError(f"bad container {t!r}")

    def _dump_ref(self, obj, buf):
        t = type(obj)
        if t is bool:
            buf.write(b"b1" if obj else b"b0")
        elif t is int:
            buf.write(f"i{obj}\n".encode("ascii"))
        elif t is str:
            b = obj.encode("iso-8859-1", errors="strict")
            buf.write(f"s{len(b)}\n".encode("ascii"))
            buf.write(b)
        elif t is type(None):
            buf.write(b"n")
        elif isinstance(obj, (dict, list, tuple)):
            if id(obj) not in self.id2id:
                raise ScoresCodecError("unregistered container")
            buf.write(f"r{self.id2id[id(obj)]}\n".encode("ascii"))
        else:
            raise ScoresCodecError(f"unsupported ref type {t!r}")

    def undump(self, data):
        if isinstance(data, str):
            data = data.encode("latin-1")
        s = io.BytesIO(data)
        magic = s.readline()
        if magic != b"cereal1\n":
            raise ScoresCodecError("not a cerealizer file")
        try:
            nb = int(s.readline())
        except ValueError:
            raise ScoresCodecError("bad object count")
        self.id2obj: list[Any] = [None] * nb
        for i in range(nb):
            classname = s.readline()
            if classname == b"dict\n":
                self.id2obj[i] = {}
            elif classname == b"list\n":
                self.id2obj[i] = []
            elif classname.startswith(b"tuple\n"):
                # tuple block includes length + refs in phase A
                # classname already consumed; but spec: "tuple\n" then len on next line
                # Here classname line is "tuple\n"; length is next line
                n = int(s.readline())
                items = [self.undump_ref(s) for _ in range(n)]
                self.id2obj[i] = tuple(items)
            else:
                raise ScoresCodecError(f"unknown class {classname!r}")
            # If tuple, fully constructed; skip phase B later (handled by marking)
        # Need distinguish tuples (already complete) vs containers needing phase B.
        # We stored tuples already; for dict/list need undump_data. But we lost handler.
        # Re-derive: tuples are tuple instances; dict/list need phase B read.
        # We'll do phase B only for dict/list, reading counts.
        for obj in self.id2obj:
            if isinstance(obj, dict):
                n_line = s.readline()
                try:
                    n = int(n_line)
                except ValueError:
                    raise ScoresCodecError("bad dict count")
                for _ in range(n):
                    v = self.undump_ref(s)
                    k = self.undump_ref(s)
                    obj[k] = v
            elif isinstance(obj, list):
                n_line = s.readline()
                try:
                    n = int(n_line)
                except ValueError:
                    raise ScoresCodecError("bad list count")
                for _ in range(n):
                    obj.append(self.undump_ref(s))
            elif isinstance(obj, tuple):
                # no phase B data
                pass
            else:
                raise ScoresCodecError("unexpected object")
        root = self.undump_ref(s)
        return root

    def undump_ref(self, s):
        c = s.read(1)
        if c == b"i":
            return int(s.readline())
        if c == b"l":
            return int(s.readline())
        if c == b"f":
            return float(s.readline())
        if c == b"b":
            v = s.read(1)
            return v == b"1"
        if c == b"s":
            n = int(s.readline())
            data = s.read(n)
            return data.decode("iso-8859-1")
        if c == b"u":
            n = int(s.readline())
            data = s.read(n)
            return data.decode("utf-8")
        if c == b"r":
            idx = int(s.readline())
            if idx < 0 or idx >= len(self.id2obj):
                raise ScoresCodecError("bad ref index")
            return self.id2obj[idx]
        if c == b"n":
            return None
        raise ScoresCodecError(f"unknown ref code {c!r}")


def loads(data):
    """Decode bytes (or str) into a Python object."""
    dumper = _Dumper()
    return dumper.undump(data)


def dumps(obj):
    """Encode a Python object into bytes."""
    dumper = _Dumper()
    return dumper.dump(obj)
