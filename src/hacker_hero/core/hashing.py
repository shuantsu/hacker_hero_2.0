"""Score hash algorithm (§2.4)."""

import hashlib


def score_hash(difficulty: int, score: int, stars: int, name: str) -> str:
    payload = f"{difficulty}{score}{stars}{name}".encode("iso-8859-1", errors="strict")
    return hashlib.sha1(payload).hexdigest()
