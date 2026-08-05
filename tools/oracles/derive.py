"""Derived fixtures: malformed inputs generated from healthy ones.

flight's decoders share one error contract, stated plainly in `swfDocument.test.ts`:

    The package's whole error contract is a null sentinel, so the property that matters is
    that no input produces an exception.

That property cannot be established from well-formed files. It needs inputs that are
truncated, corrupted and internally inconsistent — and the cheapest source of realistic
ones is the healthy corpus we already have, mutated deterministically.

DETERMINISM. Every mutation is a pure function of the source bytes: offsets come from a
counter mixed with the file's own SHA-256, never from a random number generator or a clock.
Re-deriving at the same lock produces byte-identical output, which is what lets these live
in the same reproducible-archive pipeline as everything else.

PROVENANCE. A derived file inherits the declaration of the file it came from — the same rule
that governs oracles. Deriving from one source block at a time keeps that unambiguous rather
than requiring a merge of several upstreams' terms.
"""

from __future__ import annotations

import hashlib
import struct

__all__ = ["STRATEGIES", "derive_all"]


def _seeded_offsets(data: bytes, count: int, low: int, high: int):
    """Deterministic offsets in [low, high), derived from the content itself."""
    if high <= low:
        return []
    span = high - low
    out, i = [], 0
    while len(out) < count and i < count * 8:
        digest = hashlib.sha256(data[:64] + i.to_bytes(4, "big")).digest()
        offset = low + int.from_bytes(digest[:8], "big") % span
        if offset not in out:
            out.append(offset)
        i += 1
    return sorted(out)


def _truncate(data: bytes):
    """Cut the stream short at several depths.

    The most common real-world corruption — an interrupted download, a partial write — and
    the one most likely to walk a parser off the end of a buffer. Fractions rather than fixed
    offsets so the cut lands in a different structural position for every file.
    """
    for numerator, label in ((1, "01pct"), (10, "10pct"), (50, "50pct"), (99, "99pct")):
        cut = max(1, len(data) * numerator // 100)
        if cut < len(data):
            yield f"truncate-{label}", data[:cut]


def _header(data: bytes):
    """Damage the leading bytes: wrong magic, and a zeroed header window.

    Tests the earliest rejection path. A decoder that trusts its magic and reads on will
    usually produce garbage rather than an error, which is the failure mode with no symptom.
    """
    if len(data) < 16:
        return
    yield "header-magic", b"\x00\x00\x00\x00" + data[4:]
    yield "header-zeroed", bytes(16) + data[16:]


def _lengths(data: bytes):
    """Rewrite 32-bit little-endian words near the head to implausible values.

    Length and count fields cluster in headers. Declaring 4 billion of something against a
    short buffer is the classic allocate-then-read-past-the-end trigger.
    """
    if len(data) < 32:
        return
    for offset in (4, 8, 12, 16, 20):
        if offset + 4 > len(data):
            continue
        for value, label in ((0xFFFFFFFF, "max"), (0, "zero")):
            yield (f"length-{offset}-{label}",
                   data[:offset] + struct.pack("<I", value) + data[offset + 4:])


def _bitflip(data: bytes):
    """Flip single bits deep in the payload, past any header.

    Where truncation and header damage test the obvious paths, this tests the interior:
    a checksum that no longer matches, an index pointing somewhere unexpected, an enum with
    a value the format never defines.
    """
    for i, offset in enumerate(_seeded_offsets(data, 3, min(64, len(data)), len(data))):
        mutated = bytearray(data)
        mutated[offset] ^= 1 << (offset % 8)
        yield f"bitflip-{i}", bytes(mutated)


def _empty(data: bytes):
    """Degenerate inputs every decoder is entitled to receive."""
    yield "empty", b""
    yield "one-byte", data[:1] or b"\x00"


STRATEGIES = {
    "truncate": _truncate,
    "header": _header,
    "lengths": _lengths,
    "bitflip": _bitflip,
    "empty": _empty,
}


def derive_all(name: str, data: bytes, strategies) -> list:
    """Yield (derived filename, bytes, strategy label) for one source file."""
    stem, _, ext = name.rpartition(".")
    stem = stem or name
    out = []
    for key in strategies:
        for label, mutated in STRATEGIES[key](data):
            out.append((f"{stem}.{label}.{ext}" if ext else f"{stem}.{label}",
                        mutated, label))
    return out
