"""Container-format version detection.

A commit SHA pins *which* file we took; it does not pin *what format that file is in*.
If an upstream re-exports its assets to a newer runtime format, the same logical fixture
starts exercising a different code path and nothing in the lock would show it. Every
ingested file therefore records its container version, parsed from the bytes themselves,
and drift detection compares it alongside the SHA-256.

Detection is deliberately lenient: an unrecognised file yields ``None`` rather than
raising. Not knowing a version is a fact worth recording, not a reason to drop a fixture.
"""

from __future__ import annotations

import json
import re
import struct

__all__ = ["detect", "FormatInfo"]


class FormatInfo(dict):
    """Format detection result. Behaves as a plain dict for JSON serialisation."""

    @property
    def kind(self):
        return self.get("kind")

    @property
    def version(self):
        return self.get("version")


def _riv(data: bytes):
    """Rive: 'RIVE' magic, then LEB128 varuint major, minor, file id."""
    if not data.startswith(b"RIVE"):
        return None
    pos = 4
    parts = []
    for _ in range(2):
        val = shift = 0
        while pos < len(data):
            byte = data[pos]
            pos += 1
            val |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
            if shift > 35:
                return None
        else:
            return None
        parts.append(val)
    return FormatInfo(kind="riv", version=f"{parts[0]}.{parts[1]}", major=parts[0], minor=parts[1])


def _swf(data: bytes):
    """SWF: 'FWS' (raw), 'CWS' (zlib) or 'ZWS' (LZMA), then a one-byte version."""
    if len(data) < 8 or data[:3] not in (b"FWS", b"CWS", b"ZWS"):
        return None
    compression = {b"FWS": "none", b"CWS": "zlib", b"ZWS": "lzma"}[data[:3]]
    length = struct.unpack("<I", data[4:8])[0]
    return FormatInfo(
        kind="swf",
        version=str(data[3]),
        compression=compression,
        uncompressedLength=length,
    )


_SPINE_VERSION = re.compile(rb"\d+\.\d+(?:\.\d+)?(?:-(?:beta|rc)\d*)?")


def _spine_json(data: bytes):
    """Spine JSON export: {"skeleton": {"spine": "4.2.xx", ...}, ...}"""
    if not data.lstrip()[:1] == b"{":
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    skeleton = doc.get("skeleton")
    if not isinstance(skeleton, dict) or "spine" not in skeleton:
        return None
    return FormatInfo(kind="spine-json", version=str(skeleton["spine"]))


def _spine_skel(data: bytes, name: str):
    """Spine binary export: 8-byte hash, then a length-prefixed version string.

    The prefix encoding shifted between 3.8 and 4.x, so rather than commit to one
    layout we scan the header window for the first version-shaped token. Fixtures
    only need the version recorded, not a full parse.
    """
    if not name.endswith(".skel"):
        return None
    match = _SPINE_VERSION.search(data[:64])
    if not match:
        return FormatInfo(kind="spine-skel", version=None)
    return FormatInfo(kind="spine-skel", version=match.group().decode("ascii"))


def _spine_atlas(data: bytes, name: str):
    if not name.endswith(".atlas"):
        return None
    return FormatInfo(kind="spine-atlas", version=None)


def _png(data: bytes):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    # IHDR is always the first chunk: width/height at a fixed offset.
    if len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return FormatInfo(kind="png", version=None, width=width, height=height)
    return FormatInfo(kind="png", version=None)


def detect(data: bytes, name: str = "") -> FormatInfo | None:
    """Identify *data*, using *name* only where the bytes are ambiguous."""
    for probe in (_riv, _swf, _png, _spine_json):
        info = probe(data)
        if info is not None:
            return info
    for probe in (_spine_skel, _spine_atlas):
        info = probe(data, name)
        if info is not None:
            return info
    return None
