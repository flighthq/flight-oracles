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


def _glb(data: bytes):
    """glTF binary container: 'glTF' magic, uint32 version, uint32 total length."""
    if not data.startswith(b"glTF") or len(data) < 12:
        return None
    version, length = struct.unpack("<II", data[4:12])
    return FormatInfo(kind="glb", version=str(version), totalLength=length)


def _gltf_json(data: bytes):
    """glTF JSON: {"asset": {"version": "2.0", ...}, ...}"""
    if data.lstrip()[:1] != b"{":
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    asset = doc.get("asset")
    if not isinstance(asset, dict) or "version" not in asset:
        return None
    info = FormatInfo(kind="gltf", version=str(asset["version"]))
    # Extension coverage is the whole point of this corpus, so record it per file:
    # it lets a test assert that every extension the decoder claims is exercised.
    used = doc.get("extensionsUsed")
    if isinstance(used, list):
        info["extensionsUsed"] = sorted(str(x) for x in used)
    required = doc.get("extensionsRequired")
    if isinstance(required, list):
        info["extensionsRequired"] = sorted(str(x) for x in required)
    return info


def _lottie(data: bytes):
    """Lottie/Bodymovin: {"v": "5.7.4", "fr": 30, "ip": .., "op": .., "layers": [..]}"""
    if data.lstrip()[:1] != b"{":
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict) or "layers" not in doc or "v" not in doc:
        return None
    info = FormatInfo(kind="lottie", version=str(doc["v"]))
    for key, field in (("fr", "frameRate"), ("ip", "inPoint"), ("op", "outPoint")):
        if isinstance(doc.get(key), (int, float)):
            info[field] = doc[key]
    info["layerCount"] = len(doc["layers"]) if isinstance(doc["layers"], list) else 0
    return info


def _dragonbones(data: bytes, name: str):
    """DragonBones skeleton: JSON with a "version" and "armature", or a DBDT binary."""
    if data.startswith(b"DBDT"):
        return FormatInfo(kind="dragonbones-binary", version=None)
    if data.lstrip()[:1] != b"{":
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    if "armature" in doc and "version" in doc:
        return FormatInfo(kind="dragonbones", version=str(doc["version"]),
                          armatures=len(doc["armature"]) if isinstance(doc["armature"], list) else 0)
    # Atlas sidecar: {"imagePath": .., "SubTexture": [..]}
    if "imagePath" in doc and "SubTexture" in doc:
        return FormatInfo(kind="dragonbones-atlas", version=str(doc.get("version") or ""))
    return None


def _ktx2(data: bytes):
    if not data.startswith(b"\xabKTX 20\xbb\r\n\x1a\n"):
        return None
    return FormatInfo(kind="ktx2", version="2.0")


def _ktx1(data: bytes):
    if not data.startswith(b"\xabKTX 11\xbb\r\n\x1a\n"):
        return None
    return FormatInfo(kind="ktx", version="1.1")


def _basis(data: bytes):
    """Basis Universal: 0x4273 'sB' little-endian magic, then a uint16 header size."""
    if len(data) < 4 or data[:2] != b"sB":
        return None
    return FormatInfo(kind="basis", version=None)


def _dds(data: bytes):
    if not data.startswith(b"DDS "):
        return None
    if len(data) >= 20:
        height, width = struct.unpack("<II", data[12:20])
        return FormatInfo(kind="dds", version=None, width=width, height=height)
    return FormatInfo(kind="dds", version=None)


def _md2(data: bytes):
    """Quake II MD2: 'IDP2' magic then an int32 version (always 8)."""
    if not data.startswith(b"IDP2") or len(data) < 8:
        return None
    return FormatInfo(kind="md2", version=str(struct.unpack("<i", data[4:8])[0]))


def _awd(data: bytes):
    """AWD2: 'AWD' magic, then major/minor version bytes."""
    if not data.startswith(b"AWD") or len(data) < 6:
        return None
    return FormatInfo(kind="awd", version=f"{data[3]}.{data[4]}")


_MD5_VERSION = re.compile(rb"MD5Version\s+(\d+)")


def _md5(data: bytes, name: str):
    if not name.endswith((".md5mesh", ".md5anim")):
        return None
    match = _MD5_VERSION.search(data[:64])
    kind = "md5mesh" if name.endswith(".md5mesh") else "md5anim"
    return FormatInfo(kind=kind, version=match.group(1).decode() if match else None)


def _obj_mtl(data: bytes, name: str):
    lowered = name.lower()
    if lowered.endswith(".obj"):
        return FormatInfo(kind="obj", version=None)
    if lowered.endswith(".mtl"):
        return FormatInfo(kind="mtl", version=None)
    if lowered.endswith(".3ds"):
        return FormatInfo(kind="3ds", version=None)
    return None


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
    for probe in (_riv, _swf, _glb, _ktx2, _ktx1, _basis, _dds, _md2, _awd,
                  _png, _gltf_json, _spine_json, _lottie):
        info = probe(data)
        if info is not None:
            return info
    for probe in (_dragonbones, _md5, _spine_skel, _spine_atlas, _obj_mtl):
        info = probe(data, name)
        if info is not None:
            return info
    return None
