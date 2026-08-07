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


def _frames_meta_sheet(data: bytes, name: str):
    """The frames+meta spritesheet JSON that TexturePacker and Aseprite both emit."""
    if not name.lower().endswith(".json"):
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict) or "frames" not in doc or "meta" not in doc:
        return None
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    info = FormatInfo(kind="spritesheet-json", version=str(meta.get("version") or "") or None)
    if meta.get("app"):
        info["producer"] = str(meta["app"])
    frames = doc["frames"]
    info["frameCount"] = len(frames) if isinstance(frames, (list, dict)) else 0
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


_TMX_VERSION = re.compile(rb'<map[^>]*\sversion="([^"]+)"')
_TSX_VERSION = re.compile(rb'<tileset[^>]*\sversion="([^"]+)"')
_TMX_ORIENT = re.compile(rb'<map[^>]*\sorientation="([^"]+)"')


def _tiled_xml(data: bytes, name: str):
    """Tiled TMX/TSX: XML with a version attribute on the root element."""
    if not name.lower().endswith((".tmx", ".tsx")):
        return None
    head = data[:2048]
    if name.lower().endswith(".tmx"):
        match = _TMX_VERSION.search(head)
        info = FormatInfo(kind="tmx", version=match.group(1).decode() if match else None)
        orient = _TMX_ORIENT.search(head)
        if orient:
            info["orientation"] = orient.group(1).decode()
        return info
    match = _TSX_VERSION.search(head)
    return FormatInfo(kind="tsx", version=match.group(1).decode() if match else None)


def _tiled_json(data: bytes, name: str):
    """Tiled TMJ/TSJ: the JSON serialisation of the same model."""
    if not name.lower().endswith((".tmj", ".tsj", ".tiled-project")):
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    kind = {"tmj": "tmj", "tsj": "tsj"}.get(name.lower().rsplit(".", 1)[-1], "tiled-project")
    info = FormatInfo(kind=kind, version=str(doc.get("version") or "") or None)
    if doc.get("orientation"):
        info["orientation"] = str(doc["orientation"])
    return info


def _bmfont(data: bytes, name: str):
    """AngelCode BMFont in any of its three serialisations.

    All three routinely carry the .fnt extension, so the encoding has to come from the
    bytes. Reporting them all as "fnt" would hide the one fact that matters here: this
    corpus holds the SAME font in text and XML form, and the point of having both is
    proving the two readers agree.
    """
    lowered = name.lower()
    head = data[:64].lstrip()
    if head.startswith(b"BMF"):
        return FormatInfo(kind="fnt", version="binary", encoding="binary")
    # The XML form must be identified by its ROOT ELEMENT, not by looking like XML. An
    # earlier version keyed off a leading "<?xml" and promptly relabelled 52 Cocos property
    # lists as bitmap fonts — every XML document starts that way.
    if b"<font" in data[:512] and (b"<chars" in data[:4096] or b"<pages" in data[:4096]
                                   or lowered.endswith(".fnt")):
        return FormatInfo(kind="fnt", version="xml", encoding="xml")
    if head[:4].lower() == b"info" and lowered.endswith(".fnt"):
        return FormatInfo(kind="fnt", version="text", encoding="text")
    if lowered.endswith(".fnt"):
        return FormatInfo(kind="fnt", version=None)
    return None


def _bmfont_json(data: bytes, name: str):
    """The JSON serialisation of the same model: chars plus info/common."""
    if not name.lower().endswith(".json"):
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict) or "chars" not in doc:
        return None
    if not any(k in doc for k in ("info", "common", "pages")):
        return None
    info = FormatInfo(kind="fnt", version="json", encoding="json")
    if isinstance(doc.get("chars"), list):
        info["glyphCount"] = len(doc["chars"])
    return info


def _libgdx_atlas(data: bytes, name: str):
    if name.lower().endswith(".atlas"):
        return FormatInfo(kind="libgdx-atlas", version=None)
    if name.lower().endswith(".p"):
        return FormatInfo(kind="libgdx-particle", version=None)
    return None


def _ldtk(data: bytes, name: str):
    """LDtk project or separated level: JSON carrying an explicit jsonVersion."""
    if not name.lower().endswith((".ldtk", ".ldtkl")):
        return None
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    kind = "ldtk" if name.lower().endswith(".ldtk") else "ldtk-level"
    info = FormatInfo(kind=kind, version=str(doc.get("jsonVersion") or "") or None)
    if isinstance(doc.get("levels"), list):
        info["levelCount"] = len(doc["levels"])
    return info


def _effekseer(data: bytes, name: str):
    """Effekseer: 'SKFE' runtime binary, 'EFKEFC' container, or an XML editor project."""
    if data.startswith(b"SKFE"):
        version = struct.unpack("<i", data[4:8])[0] if len(data) >= 8 else None
        return FormatInfo(kind="efk", version=str(version) if version is not None else None)
    if data.startswith(b"EFKE") and b"INFO" in data[:16]:
        # EFKE, a version word, then chunked sections beginning with INFO.
        version = struct.unpack("<i", data[4:8])[0] if len(data) >= 8 else None
        return FormatInfo(kind="efkefc", version=str(version) if version is not None else None)
    if name.lower().endswith(".efkproj"):
        return FormatInfo(kind="efkproj", version=None)
    return None


_BVH_HIERARCHY = re.compile(rb"^\s*HIERARCHY", re.I)


def _bvh(data: bytes, name: str):
    """Biovision Hierarchy: HIERARCHY block, then MOTION with a frame count."""
    if not name.lower().endswith(".bvh") or not _BVH_HIERARCHY.match(data[:64]):
        return None
    info = FormatInfo(kind="bvh", version=None)
    frames = re.search(rb"Frames:\s*(\d+)", data)
    if frames:
        info["frames"] = int(frames.group(1))
    return info


def _iqm(data: bytes):
    """Inter-Quake Model: 'INTERQUAKEMODEL\0' then a uint32 version."""
    if not data.startswith(b"INTERQUAKEMODEL\0") or len(data) < 20:
        return None
    return FormatInfo(kind="iqm", version=str(struct.unpack("<I", data[16:20])[0]))


def _stl_ply(data: bytes, name: str):
    lowered = name.lower()
    if lowered.endswith(".ply") and data[:3].lower() == b"ply":
        fmt = re.search(rb"format\s+(\w+)\s+([\d.]+)", data[:128])
        info = FormatInfo(kind="ply", version=fmt.group(2).decode() if fmt else None)
        if fmt:
            info["encoding"] = fmt.group(1).decode()
        return info
    if lowered.endswith(".stl"):
        # ASCII STL opens with "solid"; anything else is the 80-byte-header binary form.
        return FormatInfo(kind="stl",
                          version=None,
                          encoding="ascii" if data[:5].lower() == b"solid" else "binary")
    return None


def _fbx(data: bytes, name: str):
    """FBX: binary files open with 'Kaydara FBX Binary'; ASCII ones are text."""
    if data.startswith(b"Kaydara FBX Binary"):
        version = struct.unpack("<I", data[23:27])[0] if len(data) >= 27 else None
        # Real FBX versions run roughly 6000-8000. Anything outside that is the header
        # padding being read as a number, which is worse than reporting nothing.
        if version is not None and not 5000 <= version <= 9000:
            version = None
        return FormatInfo(kind="fbx", version=str(version) if version else None,
                          encoding="binary")
    if name.lower().endswith(".fbx"):
        match = re.search(rb"FBXVersion:\s*(\d+)", data[:4096])
        return FormatInfo(kind="fbx",
                          version=match.group(1).decode() if match else None,
                          encoding="ascii")
    return None


def _collada(data: bytes, name: str):
    if not name.lower().endswith(".dae"):
        return None
    match = re.search(rb'<COLLADA[^>]*\sversion="([^"]+)"', data[:2048])
    return FormatInfo(kind="collada", version=match.group(1).decode() if match else None)


_SVG_D = re.compile(rb'\sd\s*=\s*"\s*([MmZzLlHhVvCcSsQqTtAa][^"]*)"')


def _xml(data: bytes, name: str):
    """A generic XML document, once every more specific XML probe has declined.

    Ordered last among the XML-shaped probes on purpose: SVG, Tiled, Starling atlases, PEX
    and BMFont XML are all XML too, and reporting them as "xml" would lose the identification
    that matters. This is the fallback for documents that are only XML.
    """
    if not name.lower().endswith((".xml", ".xhtml", ".dtd", ".ent", ".htm", ".html")):
        return None
    head = data[:256].lstrip()
    if not head.startswith((b"<?xml", b"<!DOCTYPE", b"<!--", b"<")):
        return None
    info = FormatInfo(kind="xml", version=None)
    decl = re.search(rb'<\?xml[^>]*\sversion="([^"]+)"', data[:256])
    if decl:
        info["version"] = decl.group(1).decode("utf-8", "replace")
    enc = re.search(rb'<\?xml[^>]*\sencoding="([^"]+)"', data[:256])
    if enc:
        info["encoding"] = enc.group(1).decode("utf-8", "replace")
    if data[:256].lstrip().startswith(b"<!DOCTYPE"):
        info["hasDoctype"] = True
    return info


def _svg(data: bytes, name: str):
    """An SVG document, and how much path data it carries.

    The `d`-attribute count is the number that matters for this corpus: an SVG with no path
    element exercises nothing in path-formats, and knowing the count up front is what lets a
    test suite pick the dense cases.
    """
    lowered = name.lower()
    if not lowered.endswith((".svg", ".svg.txt")):
        return None
    if b"<svg" not in data[:2048]:
        return None
    info = FormatInfo(kind="svg", version=None)
    version = re.search(rb'<svg[^>]*\sversion="([^"]+)"', data[:1024])
    if version:
        info["version"] = version.group(1).decode("utf-8", "replace")
    paths = _SVG_D.findall(data)
    info["pathCount"] = len(paths)
    # svgo's fixtures are `input @@@ expected` in one file; note when a file is such a pair
    # so a consumer knows it carries its own answer rather than being a plain document.
    if b"@@@" in data:
        info["expectationPairs"] = data.count(b"@@@")
    return info


def _starling_atlas(data: bytes, name: str):
    """Starling/Sparrow texture atlas: <TextureAtlas imagePath=..><SubTexture ../></>."""
    if not name.lower().endswith(".xml") or b"<TextureAtlas" not in data[:512]:
        return None
    info = FormatInfo(kind="starling-atlas", version=None)
    image = re.search(rb'<TextureAtlas[^>]*\simagePath="([^"]+)"', data[:1024])
    if image:
        info["imagePath"] = image.group(1).decode("utf-8", "replace")
    info["regionCount"] = data.count(b"<SubTexture")
    return info


def _unity_yaml(data: bytes, name: str):
    """Unity scene or prefab YAML, and whether it carries a ParticleSystem.

    Recorded distinctly from the normalised JSON that unityParse reads, because the two are
    not the same format and conflating them is how the gap stayed invisible.
    """
    if not name.lower().endswith((".unity", ".prefab", ".asset")):
        return None
    if not data.startswith(b"%YAML"):
        return None
    info = FormatInfo(kind="unity-yaml", version=None)
    match = re.search(rb"%TAG !u! tag:unity3d.com,(\d+):", data[:128])
    if match:
        info["version"] = match.group(1).decode()
    info["particleSystems"] = data.count(b"ParticleSystem:")
    return info


def _pex(data: bytes, name: str):
    """Starling/ParticleDesigner PEX: the emitter model serialised as XML."""
    if not name.lower().endswith(".pex") and b"<particleEmitterConfig" not in data[:512]:
        return None
    info = FormatInfo(kind="pex", version=None)
    texture = re.search(rb'<texture\s+name="([^"]*)"', data[:2048])
    if texture:
        info["texture"] = texture.group(1).decode("utf-8", "replace")
    kind = re.search(rb'<emitterType\s+value="(\d+)"', data)
    if kind:
        info["emitterType"] = int(kind.group(1))
    return info


def _plist(data: bytes, name: str):
    """Apple property list, as used by both Cocos dialects.

    Spritesheet and ParticleDesigner plists are the same container carrying different
    models, so the distinguishing key is reported: a parser handed the wrong one should
    say so rather than half-succeed.
    """
    if not name.lower().endswith(".plist"):
        return None
    head = data[:16384]
    if b"itemWidth" in head and b"textureFilename" in head:
        # A fixed-cell bitmap font in property-list clothing: same model as .fnt, different
        # serialisation. Without this it reads as "some plist" and lands in the wrong pack.
        return FormatInfo(kind="plist-charmap", version=None)
    if b"<key>frames</key>" in head:
        return FormatInfo(kind="plist-spritesheet", version=None)
    if b"emitterType" in head or b"maxParticles" in head:
        return FormatInfo(kind="plist-particle", version=None)
    return FormatInfo(kind="plist", version=None)


def _obj_mtl(data: bytes, name: str):
    lowered = name.lower()
    if lowered.endswith(".obj"):
        return FormatInfo(kind="obj", version=None)
    if lowered.endswith(".mtl"):
        return FormatInfo(kind="mtl", version=None)
    if lowered.endswith(".3ds"):
        return FormatInfo(kind="3ds", version=None)
    return None


def _atf(data: bytes):
    """Adobe Texture Format: 'ATF' magic, then a length and a version byte."""
    if not data.startswith(b"ATF") or len(data) < 8:
        return None
    # Post-3.0 files carry an explicit version at offset 6; earlier ones have a 3-byte
    # big-endian length there instead, so only trust it when it looks like a version.
    version = data[6] if data[6] < 16 else None
    return FormatInfo(kind="atf", version=str(version) if version is not None else None)


# --- fonts -------------------------------------------------------------------------
#
# A font's "version" is not one number, and picking the wrong one records something
# useless. The sfnt header carries a *flavour* rather than a revision (0x00010000 for
# TrueType outlines, 'OTTO' for CFF), and the majorVersion/minorVersion in a WOFF header
# describe the *font*, not the WOFF format — WOFF's own version is its signature. So the
# version recorded here is the container's: "1.0" for WOFF, "2.0" for WOFF2, the TTC
# header version for collections, and None for a bare sfnt, which has no such number.
#
# What actually distinguishes one font fixture from another is which tables it carries,
# so that is what the detector reports: outline flavour (glyf / CFF / CFF2), whether it
# is variable (fvar), and which colour technology it uses (COLR / CBDT / sbix / SVG).
# Those make the manifest queryable — "every fixture with a CFF2 table" is a decoder
# obligation, and a corpus you cannot ask that question of is a pile of files.

_SFNT_FLAVORS = {
    b"\x00\x01\x00\x00": "truetype",
    b"OTTO": "cff",
    b"true": "truetype",
    b"typ1": "type1",
}

# WOFF2 does not spell out table tags it can predict; a 6-bit index into this list stands
# in for them, and only index 63 means "an arbitrary 4-byte tag follows". Order is
# normative (WOFF2 spec, "Known Table Tags"), so this list is a specification constant
# rather than a convenience.
_WOFF2_KNOWN_TAGS = [
    b"cmap", b"head", b"hhea", b"hmtx", b"maxp", b"name", b"OS/2", b"post",
    b"cvt ", b"fpgm", b"glyf", b"loca", b"prep", b"CFF ", b"VORG", b"EBDT",
    b"EBLC", b"gasp", b"hdmx", b"kern", b"LTSH", b"PCLT", b"VDMX", b"vhea",
    b"vmtx", b"BASE", b"GDEF", b"GPOS", b"GSUB", b"EBSC", b"JSTF", b"MATH",
    b"CBDT", b"CBLC", b"COLR", b"CPAL", b"SVG ", b"sbix", b"acnt", b"avar",
    b"bdat", b"bloc", b"bsln", b"cvar", b"fdsc", b"feat", b"fmtx", b"fvar",
    b"gvar", b"hsty", b"just", b"lcar", b"mort", b"morx", b"opbd", b"prop",
    b"trak", b"Zapf", b"Silf", b"Glat", b"Gloc", b"Feat", b"Sill",
]


def _table_traits(tags):
    """Summarise a table set: outline flavour, variability, colour technology.

    Compact on purpose. Recording all ~20 tags per file would add more bulk to the locks
    than it buys; these three answer the questions a decoder suite actually asks.
    """
    tags = set(tags)
    traits = {}
    if b"CFF2" in tags:
        traits["outlines"] = "cff2"
    elif b"CFF " in tags:
        traits["outlines"] = "cff"
    elif b"glyf" in tags:
        traits["outlines"] = "glyf"
    if b"fvar" in tags:
        traits["variable"] = True
    colour = [name for tag, name in (
        (b"COLR", "colr"), (b"CBDT", "cbdt"), (b"sbix", "sbix"), (b"SVG ", "svg"),
        (b"EBDT", "ebdt"),
    ) if tag in tags]
    if colour:
        traits["color"] = colour
    return traits


def _sfnt_tables(data: bytes, offset: int = 0):
    """Table tags from an sfnt directory at *offset*, or None if it does not fit."""
    if len(data) < offset + 12:
        return None
    count = struct.unpack(">H", data[offset + 4:offset + 6])[0]
    # 4096 is far above any real font (the record holder is in the low hundreds) and far
    # below what a bogus length would produce, so it separates a font from four bytes of
    # coincidence without rejecting anything real.
    if not 0 < count <= 4096 or len(data) < offset + 12 + 16 * count:
        return None
    base = offset + 12
    return [data[base + 16 * i:base + 16 * i + 4] for i in range(count)]


def _sfnt(data: bytes):
    """Bare TrueType/OpenType: a 4-byte flavour tag, then the table directory."""
    flavor = _SFNT_FLAVORS.get(data[:4])
    if flavor is None:
        return None
    tags = _sfnt_tables(data)
    if tags is None:
        return None
    kind = "otf" if flavor == "cff" else "ttf"
    info = FormatInfo(kind=kind, version=None, sfntVersion=flavor, numTables=len(tags))
    info.update(_table_traits(tags))
    return info


def _ttc(data: bytes):
    """TrueType/OpenType Collection: 'ttcf', a header version, then per-font offsets."""
    if not data.startswith(b"ttcf") or len(data) < 12:
        return None
    major, minor, count = struct.unpack(">HHI", data[4:12])
    if not 0 < count <= 4096 or len(data) < 12 + 4 * count:
        return None
    offsets = struct.unpack(f">{count}I", data[12:12 + 4 * count])
    tags = set()
    for off in offsets:
        found = _sfnt_tables(data, off)
        if found:
            tags.update(found)
    info = FormatInfo(
        kind="ttc", version=f"{major}.{minor}", numFonts=count, numTables=len(tags)
    )
    info.update(_table_traits(tags))
    return info


def _woff(data: bytes):
    """WOFF 1.0: 'wOFF', the wrapped sfnt flavour, then a 20-byte-per-table directory.

    The directory is plain even though the tables are zlib-compressed, so the tag set is
    readable without decompressing anything.
    """
    if not data.startswith(b"wOFF") or len(data) < 44:
        return None
    flavor, _length, count = struct.unpack(">IIH", data[4:14])
    total_sfnt = struct.unpack(">I", data[16:20])[0]
    info = FormatInfo(
        kind="woff",
        version="1.0",
        flavor=_SFNT_FLAVORS.get(struct.pack(">I", flavor)) or f"0x{flavor:08x}",
        numTables=count,
        totalSfntSize=total_sfnt,
    )
    if 0 < count <= 4096 and len(data) >= 44 + 20 * count:
        tags = [data[44 + 20 * i:44 + 20 * i + 4] for i in range(count)]
        info.update(_table_traits(tags))
    return info


def _uint_base128(data: bytes, pos: int):
    """WOFF2's variable-length integer: 7 bits per byte, high bit continues."""
    value = 0
    for i in range(5):
        if pos >= len(data):
            return None, pos
        byte = data[pos]
        pos += 1
        # Leading zeros are forbidden by the spec, and so is overflowing 32 bits; both
        # mean we are not reading a table directory and should stop rather than guess.
        if i == 0 and byte == 0x80:
            return None, pos
        if value & 0xFE000000:
            return None, pos
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos
    return None, pos


def _woff2(data: bytes):
    """WOFF2: 'wOF2' and a header whose table directory precedes the brotli stream.

    The directory is deliberately parsed here even though the font body needs brotli,
    which is not in the standard library. Everything that identifies the font — which
    tables it has, whether glyf/loca were transformed — sits in that uncompressed
    prologue, so the interesting facts are reachable without a dependency.
    """
    if not data.startswith(b"wOF2") or len(data) < 48:
        return None
    flavor, _length, count = struct.unpack(">IIH", data[4:14])
    total_sfnt, total_compressed = struct.unpack(">II", data[16:24])
    info = FormatInfo(
        kind="woff2",
        version="2.0",
        flavor=_SFNT_FLAVORS.get(struct.pack(">I", flavor))
        or ("collection" if struct.pack(">I", flavor) == b"ttcf" else f"0x{flavor:08x}"),
        numTables=count,
        totalSfntSize=total_sfnt,
        totalCompressedSize=total_compressed,
    )
    # The WOFF2 header is 48 bytes — four more than WOFF's, for totalCompressedSize — and
    # the table directory begins immediately after it. Starting the walk at the wrong
    # offset does not fail: it reads the tail of the header as flag bytes and produces a
    # plausible-looking tag list for the wrong tables, which is how this was caught (a
    # TrueType-flavoured file reporting CFF outlines).
    tags, transformed, pos = [], [], 48
    for _ in range(count):
        if pos >= len(data):
            tags = None
            break
        flags = data[pos]
        pos += 1
        index = flags & 0x3F
        if index == 0x3F:
            if pos + 4 > len(data):
                tags = None
                break
            tag = data[pos:pos + 4]
            pos += 4
        else:
            tag = _WOFF2_KNOWN_TAGS[index]
        orig_length, pos = _uint_base128(data, pos)
        if orig_length is None:
            tags = None
            break
        # Transform version 0 means *transformed* for glyf and loca and *untransformed*
        # for everything else — the one place in this header where the same value means
        # opposite things, and where a transformLength is silently present or absent.
        version = flags >> 6
        if tag in (b"glyf", b"loca"):
            is_transformed = version == 0
        else:
            is_transformed = version != 0
        if is_transformed:
            transform_length, pos = _uint_base128(data, pos)
            if transform_length is None:
                tags = None
                break
            transformed.append(tag.decode("latin-1").strip())
        tags.append(tag)
    if tags is not None:
        info.update(_table_traits(tags))
        if transformed:
            info["transformed"] = transformed
    return info


_TTX_ROOT = re.compile(rb"<ttFont\b[^>]*>")
_TTX_ATTR = re.compile(rb'(\w+)="([^"]*)"')
# Top-level children of <ttFont> are table elements. fontTools spells tags that are not
# valid XML names with underscores — 'OS/2' becomes 'OS_2', 'cvt ' becomes 'cvt_' — so the
# element name is the tag, not something to translate back.
_TTX_TABLE = re.compile(rb"^  <([A-Za-z][\w_]*)[ >/]", re.M)


def _ttx(data: bytes, name: str):
    """fontTools' XML serialisation of a font.

    Reported as its own format rather than falling through to generic XML, because a .ttx
    beside a .ttf is not incidentally XML — it is that font's table structure written out,
    which is the closest thing to an expected-output document a font corpus carries.
    """
    if not name.lower().endswith(".ttx"):
        return None
    root = _TTX_ROOT.search(data[:4096])
    if root is None:
        return None
    attrs = dict(_TTX_ATTR.findall(root.group(0)))
    info = FormatInfo(kind="ttx", version=None)
    lib = attrs.get(b"ttLibVersion")
    if lib:
        info["ttLibVersion"] = lib.decode("utf-8", "replace")
    sfnt = attrs.get(b"sfntVersion")
    if sfnt:
        # Written as an escaped literal — "\x00\x01\x00\x00" for TrueType, "OTTO" for CFF.
        raw = sfnt.decode("unicode_escape").encode("latin-1")
        info["sfntVersion"] = _SFNT_FLAVORS.get(raw) or sfnt.decode("utf-8", "replace")
    tables = set()
    for element in _TTX_TABLE.findall(data):
        # GlyphOrder is fontTools' own bookkeeping, not a table in the font.
        if element == b"GlyphOrder":
            continue
        if element == b"OS_2":
            element = b"OS/2"
        elif element.endswith(b"_"):
            element = element[:-1] + b" "      # 'cvt_' is the tag 'cvt '
        tables.add(element)
    if tables:
        info["numTables"] = len(tables)
        info.update(_table_traits(tables))
    return info


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
    for probe in (_riv, _swf, _glb, _ktx2, _ktx1, _basis, _dds, _md2, _awd, _atf,
                  _iqm,
                  _woff2, _woff, _ttc, _sfnt,
                  _png, _gltf_json, _spine_json, _lottie):
        info = probe(data)
        if info is not None:
            return info
    for probe in (_ttx,
                  _dragonbones, _md5, _tiled_xml, _tiled_json, _bmfont, _plist,
                  _ldtk, _effekseer, _bmfont_json, _frames_meta_sheet, _bvh,
                  _starling_atlas, _unity_yaml, _svg, _xml,
                  _stl_ply, _fbx,
                  _pex,
                  _collada,
                  _libgdx_atlas, _spine_skel, _spine_atlas, _obj_mtl):
        info = probe(data, name)
        if info is not None:
            return info
    return None
