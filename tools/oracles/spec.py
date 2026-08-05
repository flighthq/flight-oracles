"""Loading and validation of hand-authored pack specs (``sources/*.toml``).

A spec records *intent*: which upstream, pinned to which commit, which paths, and what
that upstream declared about the licence. The per-file facts (hashes, sizes, format
versions) are not written here — they are produced by ingest into ``locks/*.lock.json``.
Hand-maintaining 400+ file entries is not a thing anyone will keep doing correctly, so
the split is load-bearing rather than cosmetic.

The ``[[source]]`` block is the unit of licence declaration. Where one upstream repo
declares different things for different subtrees — Ruffle's own tests are Apache-2.0/MIT
while ``from_gnash`` carries GPL-3.0 from its origin — that is two source blocks, not one
block with an asterisk.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["PackSpec", "SourceSpec", "LicenseSpec", "load_spec", "load_all", "compile_globs"]

# Scope of a licence declaration, weakest last. A repository-root LICENSE is a statement
# about the repository, not necessarily about every file in it; a licence sitting beside
# the asset speaks about the asset. Consumers deserve to know which one they have.
SCOPES = ("file-adjacent", "directory", "repository-root")

SOURCE_KINDS = ("upstream", "recovered")


def compile_globs(patterns):
    """Translate glob patterns to a regex, supporting ``**`` across separators."""
    alts = []
    for pattern in patterns:
        out, i = [], 0
        while i < len(pattern):
            ch = pattern[i]
            if pattern.startswith("**/", i):
                out.append(r"(?:.*/)?")
                i += 3
            elif pattern.startswith("**", i):
                out.append(r".*")
                i += 2
            elif ch == "*":
                out.append(r"[^/]*")
                i += 1
            elif ch == "?":
                out.append(r"[^/]")
                i += 1
            else:
                out.append(re.escape(ch))
                i += 1
        alts.append("".join(out))
    return re.compile(r"^(?:%s)$" % "|".join(alts))


@dataclass
class LicenseSpec:
    declared: str
    declared_scope: str
    declared_from: str | None = None
    covers: str | None = None
    commercial_use: object = "unknown"  # True | False | "unknown"
    source_code: str | None = None      # e.g. GPL generator scripts for from_gnash
    concluded: str | None = None        # only where a human actually analysed it
    # False where the declaration *explicitly forbids* redistribution. This is not a
    # judgement call about risk and not a guess about unresolved rights — it is the one
    # case where honouring the declaration and republishing the bytes are incompatible.
    # Two Spine examples are declared this way by their third-party authors:
    # `dragon` (Thiago Brayner) and `hero` (XDTech), both "may not be redistributed for
    # any reason". They stay in the spec so the record of having looked is durable; the
    # pipeline refuses to vendor or pack them.
    redistributable: bool = True
    prohibition: str | None = None      # verbatim clause, when redistributable is False

    def __post_init__(self):
        if self.declared_scope not in SCOPES:
            raise ValueError(
                f"license.declared_scope must be one of {SCOPES}, got {self.declared_scope!r}"
            )
        if self.commercial_use not in (True, False, "unknown"):
            raise ValueError("license.commercial_use must be true, false, or \"unknown\"")
        if not self.redistributable and not self.prohibition:
            raise ValueError(
                "license.redistributable = false requires license.prohibition quoting the "
                "clause, so the reason survives without re-reading the upstream file"
            )

    @property
    def is_file_adjacent(self) -> bool:
        """File-adjacent licences are preserved in place as well as in ``LICENSES/``.

        Spineboy's terms permit redistribution of the images "as long as they are
        accompanied by this license file"; the safe reading of *accompanied* is next to
        the images, not merely somewhere in the tarball.
        """
        return self.declared_scope == "file-adjacent"

    def to_json(self):
        out = {
            "declared": self.declared,
            "declaredScope": self.declared_scope,
            "commercialUse": self.commercial_use,
            "redistributable": self.redistributable,
        }
        for key, val in (
            ("declaredFrom", self.declared_from),
            ("covers", self.covers),
            ("sourceCode", self.source_code),
            ("concluded", self.concluded),
            ("prohibition", self.prohibition),
        ):
            if val is not None:
                out[key] = val
        return out


@dataclass
class SourceSpec:
    id: str
    kind: str
    include: list
    license: LicenseSpec
    repo: str | None = None
    ref: str | None = None
    commit: str | None = None
    url: str | None = None          # for kind="recovered"
    retrieved: str | None = None
    # "tarball" (default) is one request and right for most repos. "blobs" lists the git
    # tree and fetches only the files the globs select — necessary where the repository
    # dwarfs the slice we want (glTF-Sample-Assets is 1.4 GB), and where many sources share
    # one repo, since it avoids re-walking a huge archive per source.
    fetch: str = "tarball"
    strip: str = ""                 # upstream prefix removed from the archive path
    dest: str = ""                  # archive-relative prefix added back on
    exclude_paths: list = field(default_factory=list)
    annotations: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"source.kind must be one of {SOURCE_KINDS}, got {self.kind!r}")
        if self.kind == "upstream" and not self.repo:
            raise ValueError(f"source {self.id!r}: kind=upstream requires repo")
        if self.fetch not in ("tarball", "blobs"):
            raise ValueError(
                f"source {self.id!r}: fetch must be \"tarball\" or \"blobs\", "
                f"got {self.fetch!r}"
            )
        if self.kind == "recovered" and self.license.declared != "UNKNOWN":
            raise ValueError(
                f"source {self.id!r}: kind=recovered has no upstream declaration to "
                f"report, so license.declared must be \"UNKNOWN\""
            )
        self._matcher = compile_globs(self.include)
        self._excluder = compile_globs(self.exclude_paths) if self.exclude_paths else None

    def selects(self, upstream_path: str) -> bool:
        if self._excluder is not None and self._excluder.match(upstream_path):
            return False
        return bool(self._matcher.match(upstream_path))

    def dest_for(self, upstream_path: str) -> str:
        rel = upstream_path
        if self.strip and rel.startswith(self.strip):
            rel = rel[len(self.strip):]
        return f"{self.dest}{rel}".lstrip("/")


@dataclass
class PackSpec:
    name: str
    kind: str
    summary: str
    sources: list
    path: Path | None = None

    @property
    def annotations(self) -> dict:
        merged = {}
        for source in self.sources:
            merged.update(source.annotations)
        return merged


def _license(raw, source_id):
    if not raw:
        raise ValueError(f"source {source_id!r}: missing [source.license]")
    known = {f.name for f in LicenseSpec.__dataclass_fields__.values()}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"source {source_id!r}: unknown license keys {sorted(unknown)}")
    return LicenseSpec(**raw)


def load_spec(path: Path) -> PackSpec:
    with open(path, "rb") as handle:
        doc = tomllib.load(handle)

    pack = doc.get("pack")
    if not pack:
        raise ValueError(f"{path}: missing [pack]")

    sources = []
    for raw in doc.get("source", []):
        raw = dict(raw)
        source_id = raw.get("id", "<unnamed>")
        lic = _license(raw.pop("license", None), source_id)
        annotations = raw.pop("annotations", {})
        raw.pop("exclude", None)  # reserved: per-source exclusion lives on files
        sources.append(SourceSpec(license=lic, annotations=annotations, **raw))

    if not sources:
        raise ValueError(f"{path}: no [[source]] blocks")

    ids = [s.id for s in sources]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate source ids")

    return PackSpec(
        name=pack["name"],
        kind=pack.get("kind", "fixtures"),
        summary=pack.get("summary", ""),
        sources=sources,
        path=path,
    )


def load_all(root: Path):
    return [load_spec(p) for p in sorted(root.glob("*.toml"))]
