"""Resolve the external files our descriptors point at.

Most of what this repository ships is a *descriptor*: an atlas naming its page images, a
tilemap naming its tilesets, an OBJ naming its material library, a bitmap font naming its
glyph pages. Parsing one needs nothing else. Rendering one needs every file it names.

That distinction produced a silent, systematic hole. Packs were assembled a format at a
time, each glob written for the parser in front of me, and six of nine ended up shipping
descriptors whose images were simply absent — 316 unresolved references in the tilemap pack
alone. Nothing caught it, because every pack verified perfectly against its own lock and the
missing files were never in the lock to begin with.

The glTF merge-group check found exactly this problem for one format. This generalises it:
every format we can parse a reference out of, checked on every verify. A descriptor pack
that cannot render is a legitimate choice — but it should be a choice someone made, not an
accident nobody noticed.
"""

from __future__ import annotations

import json
import pathlib
import posixpath
import re
from urllib.parse import unquote

__all__ = ["extract", "unresolved"]

# MTL map_* lines carry option flags before the filename, and some of those flags take their
# own arguments. Matching the last token is right far more often than matching the first.
_MTL_MAP = re.compile(r"^map_\w+\s+(?:-\S+(?:\s+[\d.-]+){0,3}\s+)*(\S+)\s*$", re.M)
_MTL_OPTION_WORDS = {"bump", "map_d", "on", "off"}


def _atlas_pages(text: str):
    """libgdx and Spine atlases: a page image filename on its own unindented line."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or line[:1] in " \t" or ":" in stripped:
            continue
        if "." in stripped:
            yield stripped


def extract(name: str, data: bytes):
    """Yield the paths *name* references, relative to its own directory."""
    lowered = name.lower()
    try:
        text = data.decode("utf-8", "replace")
    except Exception:
        return

    if lowered.endswith(".atlas"):
        yield from _atlas_pages(text)
    elif lowered.endswith(".fnt"):
        yield from re.findall(r'file="([^"]+)"', text)
    elif lowered.endswith(".plist"):
        for key in ("textureFileName", "textureFilename", "realTextureFileName"):
            yield from re.findall(rf"<key>{key}</key>\s*<string>([^<]+)</string>", text)
    elif lowered.endswith((".tmx", ".tsx")):
        yield from re.findall(r'<image[^>]*\ssource="([^"]+)"', text)
        yield from re.findall(r'<tileset[^>]*\ssource="([^"]+)"', text)
    elif lowered.endswith((".tmj", ".tsj")):
        try:
            doc = json.loads(text)
        except ValueError:
            return
        if not isinstance(doc, dict):
            return
        if doc.get("image"):
            yield doc["image"]
        for tileset in doc.get("tilesets") or []:
            for key in ("image", "source"):
                if isinstance(tileset, dict) and tileset.get(key):
                    yield tileset[key]
    elif lowered.endswith(".xml"):
        yield from re.findall(r'<TextureAtlas[^>]*\simagePath="([^"]+)"', text)
    elif lowered.endswith(".pex"):
        yield from re.findall(r'<texture\s+name="([^"]+)"', text)
    elif lowered.endswith(".obj"):
        yield from re.findall(r"^mtllib\s+(.+?)\s*$", text, re.M)
    elif lowered.endswith(".mtl"):
        for hit in _MTL_MAP.findall(text):
            if hit.lower() not in _MTL_OPTION_WORDS and "." in hit:
                yield hit
    elif lowered.endswith(".gltf"):
        try:
            doc = json.loads(text)
        except ValueError:
            return
        if not isinstance(doc, dict):
            return
        for group in ("buffers", "images"):
            for item in doc.get(group) or []:
                uri = isinstance(item, dict) and item.get("uri")
                if uri and not uri.startswith("data:"):
                    yield uri
    elif lowered.endswith(".json"):
        try:
            doc = json.loads(text)
        except ValueError:
            return
        if not isinstance(doc, dict):
            return
        if doc.get("imagePath"):                      # DragonBones atlas
            yield doc["imagePath"]
        for asset in doc.get("assets") or []:          # Lottie external assets
            if isinstance(asset, dict) and asset.get("p") and not str(asset["p"]).startswith("data:"):
                yield (asset.get("u") or "") + asset["p"]


def unresolved(locks, root: pathlib.Path, max_bytes: int = 4_000_000):
    """Return (pack, descriptor, reference) for every reference that resolves nowhere.

    Resolution is checked across ALL supplied locks, so packs deliberately split — geometry
    here, textures there — count as resolved when the group is taken together.
    """
    present = set()
    by_basename = set()
    for lock in locks:
        for entry in lock["files"]:
            present.add(entry["path"])
            by_basename.add(pathlib.PurePosixPath(entry["path"]).name)

    problems = []
    for lock in locks:
        pack = lock["pack"]["name"]
        vendor = root / "vendor" / pack
        for entry in lock["files"]:
            path = vendor / entry["path"]
            if not path.exists() or path.stat().st_size > max_bytes:
                continue
            base = pathlib.PurePosixPath(entry["path"]).parent
            for ref in extract(entry["path"], path.read_bytes()):
                ref = unquote(ref.strip())
                if not ref or ref.startswith(("data:", "http:", "https:")):
                    continue
                if ref.startswith("/"):
                    # Site-absolute, as in a documentation site's own URL space. Nothing we
                    # place on disk resolves it, so it is not an omission we can fix.
                    continue
                # normpath, not PurePosixPath: the latter keeps ".." segments literally, so
                # an ordinary "../../tileset.png" never matches a stored path and every
                # relative-parent reference is reported missing while the file sits right
                # there. This has regressed once already — the test below is the guard.
                target = posixpath.normpath(str(base / ref))
                if target in present or target.lstrip("./") in present:
                    continue
                # Cocos resolves a texture name through an engine SEARCH PATH rather than
                # relative to the descriptor naming it, so a plist in one directory
                # legitimately points at an image in another. Relative resolution is simply
                # the wrong test for that dialect; the basename is how the engine finds it.
                if entry["path"].lower().endswith(".plist") and \
                        pathlib.PurePosixPath(ref).name in by_basename:
                    continue
                problems.append((pack, entry["path"], ref))
    return problems
