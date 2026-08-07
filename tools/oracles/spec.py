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

SOURCE_KINDS = ("upstream", "recovered", "derived")

# How far material may travel once it leaves the build — see LicenseSpec.onward_use.
ONWARD_USE = ("unrestricted", "non-commercial", "testing-only", "unknown")

# Declarations carrying a term that must be read before adoption, not merely a restriction
# on republishing. These are NOT forbidden — the guard exists so they cannot be adopted by
# accident, since the hazard is invisible to anyone screening on the SPDX identifier alone.
# Setting `hazard_reviewed = true` on the source unblocks it and records that someone looked.
DECLARATIONS_NEEDING_REVIEW = {
    "LicenseRef-UGent-Academic": (
        "UGent Academic License s3(b): every licensee grants Ghent University a 'perpetual, "
        "worldwide, exclusive, no-charge, royalty-free, irrevocable' licence to commercially "
        "exploit any Derivative Works. s2 separately forbids distributing the Work, so this "
        "is redistributable = false regardless.\n\n"
        "SCOPE - a decoder is NOT a derivative of what it decodes, any more than a DVD player "
        "is a derivative of a DVD. Neither flight nor this pipeline nor a test suite becomes a "
        "derivative by processing a fixture, and structural oracles (parse trees, traces, bone "
        "transforms) are measurements about a file rather than adaptations of its expression. "
        "The exposure is narrow: PIXEL GOLDENS rendered from this material plausibly are "
        "derivatives, and s3(b) would assign exclusive commercial rights in them irrevocably. "
        "Adopt for structural work if useful; do not render goldens from it."
    ),
}


# Supported glob syntax is exactly ``*``, ``**`` and ``?``. Anything else is rejected rather
# than escaped, because the failure mode of escaping is silent: a pattern containing a
# character class was translated to a search for that class as literal text, matched nothing,
# and excluded nothing — which looked identical to "there was nothing to exclude". That went
# unnoticed until content-based format detection disagreed with the path-based selection.
_UNSUPPORTED_GLOB = "[]{}!"


def compile_globs(patterns):
    """Translate glob patterns to a regex, supporting ``**`` across separators."""
    alts = []
    for pattern in patterns:
        bad = sorted({c for c in pattern if c in _UNSUPPORTED_GLOB})
        if bad:
            raise ValueError(
                f"glob {pattern!r} uses unsupported syntax {bad} — only *, ** and ? are "
                f"understood. These would be matched as literal characters, silently "
                f"selecting nothing; write separate patterns instead"
            )
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
    # Acknowledges a DECLARATIONS_NEEDING_REVIEW entry was read and a decision taken.
    hazard_reviewed: bool = False
    # An explicit human conclusion that the declared terms are permissive, for licences with
    # no recognised SPDX identifier. Set only after reading the text; requires `concluded` to
    # record what was read, so it is a conclusion on the record rather than an assertion.
    permissive: bool = False
    # How far the material may travel once it leaves the build. Distinct from
    # `commercial_use`, which asks a different question: this one is about whether it may
    # be *deployed at all* beyond testing.
    #
    #   unrestricted    may appear anywhere, including commercial work
    #   non-commercial  may be shown publicly, but not commercially (spineboy, Stanford)
    #   testing-only    may not leave the build (VirtualCity: 3DRT's exemption is scoped to
    #                   "testing your glTF tools such as loaders and importers")
    #   unknown         the operative grant does not say (the Khronos arrangements)
    #
    # Collapsing testing-only into commercial_use = false would have put a tool-testing-only
    # model in the same bucket as spineboy, which Esoteric plainly intends to be shown.
    onward_use: str = "unrestricted"
    # Layers beneath the operative grant: the instrument(s) the material carried before the
    # immediate upstream published it.
    #
    # A single `declared` field cannot express the common real case where a publisher
    # redistributes third-party material under terms they negotiated. Khronos admits
    # "semi-restrictive" assets to glTF-Sample-Assets "provided arrangements are made", and
    # requires every asset to carry a licence that lets Khronos publish it *and* lets others
    # use it in public. That arrangement is the grant a downstream consumer actually relies
    # on; the SPDX id in the model's metadata records where the material came from.
    #
    # Flattening the two loses information whichever way you pick: name only the origin and
    # you understate the rights and misattribute the terms to the publisher; name only the
    # operative grant and you drop attribution the origin is owed. So both are recorded,
    # `declared` is the layer relied on, and `underlying` is attributed in NOTICE.md.
    underlying: list = field(default_factory=list)

    def __post_init__(self):
        if self.declared_scope not in SCOPES:
            raise ValueError(
                f"license.declared_scope must be one of {SCOPES}, got {self.declared_scope!r}"
            )
        hazard = DECLARATIONS_NEEDING_REVIEW.get(self.declared)
        if hazard and not self.hazard_reviewed:
            raise ValueError(
                f"license.declared = {self.declared!r} carries a term needing review before "
                f"adoption.\n\n{hazard}\n\nSee docs/sourcing-policy.md. Set "
                f"license.hazard_reviewed = true to proceed once the decision is recorded - "
                f"do not work around this by relabelling the declaration."
            )
        if self.commercial_use not in (True, False, "unknown"):
            raise ValueError("license.commercial_use must be true, false, or \"unknown\"")
        if self.onward_use not in ONWARD_USE:
            raise ValueError(
                f"license.onward_use must be one of {ONWARD_USE}, got {self.onward_use!r}"
            )
        # Where nothing may be redistributed at all, "how far may it travel" has no answer.
        # Forcing a value would put a misleading default in the lock, so the field is simply
        # not applicable and is omitted from the record.
        if not self.redistributable:
            pass
        elif self.onward_use == "unrestricted" and self.commercial_use is False:
            raise ValueError(
                "license.onward_use = \"unrestricted\" contradicts commercial_use = false; "
                "use \"non-commercial\" if the material may be shown but not sold"
            )
        if not self.redistributable and not self.prohibition:
            raise ValueError(
                "license.redistributable = false requires license.prohibition quoting the "
                "clause, so the reason survives without re-reading the upstream file"
            )
        if self.permissive and not self.concluded:
            raise ValueError(
                "license.permissive = true requires license.concluded recording what was "
                "read and what it was concluded to be — otherwise the claim is unsourced"
            )
        for i, layer in enumerate(self.underlying):
            if not isinstance(layer, dict) or not layer.get("declared"):
                raise ValueError(
                    f"license.underlying[{i}] needs at least a `declared` identifier - an "
                    f"unnamed layer attributes nothing"
                )
            if not layer.get("note"):
                raise ValueError(
                    f"license.underlying[{i}] ({layer['declared']}) needs a `note` saying "
                    f"how the operative grant relates to it. Recording a restrictive layer "
                    f"without explaining why we may still publish is worse than omitting it"
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
        if self.redistributable:
            out["onwardUse"] = self.onward_use
        if self.permissive:
            out["permissive"] = True
        if self.underlying:
            out["underlying"] = list(self.underlying)
        return out


@dataclass
class SourceSpec:
    id: str
    kind: str
    license: LicenseSpec
    # Not required for kind = "derived": those generate from an already-ingested pack
    # rather than selecting paths out of an upstream.
    include: list = field(default_factory=list)
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
    # kind = "derived": generate from an already-ingested pack rather than fetch.
    from_pack: str | None = None
    from_source: str | None = None
    # Which of the parent's files to derive from. A parent can hold more than one kind of
    # file — `ruffle-authored` carries .swf alongside the .as sources, .toml configs and
    # .txt expectations that document each case — and mutating a config tests nothing about
    # the decoder. Without this the derivative silently widens whenever the parent does.
    from_include: list = field(default_factory=list)
    strategies: list = field(default_factory=list)
    sample: int = 0                 # 0 = every file in the source
    strip: str = ""                 # upstream prefix removed from the archive path
    dest: str = ""                  # archive-relative prefix added back on
    exclude_paths: list = field(default_factory=list)
    annotations: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"source.kind must be one of {SOURCE_KINDS}, got {self.kind!r}")
        if self.kind == "upstream" and not self.repo:
            raise ValueError(f"source {self.id!r}: kind=upstream requires repo")
        if self.kind != "derived" and not self.include:
            raise ValueError(f"source {self.id!r}: include patterns are required")
        if self.fetch not in ("tarball", "blobs"):
            raise ValueError(
                f"source {self.id!r}: fetch must be \"tarball\" or \"blobs\", "
                f"got {self.fetch!r}"
            )
        if self.kind == "derived":
            if not (self.from_pack and self.from_source):
                raise ValueError(
                    f"source {self.id!r}: kind=derived requires from_pack and from_source. "
                    f"Deriving from ONE source block keeps the inherited declaration "
                    f"unambiguous — a mutation of a GPL fixture is still GPL-derived"
                )
            if not self.strategies:
                raise ValueError(f"source {self.id!r}: kind=derived requires strategies")
            if not self.from_include:
                raise ValueError(
                    f"source {self.id!r}: kind=derived requires from_include naming which "
                    f"of the parent's files to mutate. A parent may hold configs, sources "
                    f"and expectations beside the format itself, and corrupting those tests "
                    f"nothing"
                )
            self._from_matcher = compile_globs(self.from_include)
        if self.kind == "recovered" and self.license.declared != "UNKNOWN":
            raise ValueError(
                f"source {self.id!r}: kind=recovered has no upstream declaration to "
                f"report, so license.declared must be \"UNKNOWN\""
            )
        self._matcher = compile_globs(self.include)
        self._excluder = compile_globs(self.exclude_paths) if self.exclude_paths else None

    def selects_parent(self, path: str) -> bool:
        """Whether a parent pack's file is eligible to be derived from."""
        return bool(self._from_matcher.match(path))

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
    # Packs sharing a merge group must be extracted into the SAME directory.
    #
    # glTF's external-resource form references its buffers and images by relative URI, so
    # splitting geometry from textures — which we did for size — breaks resolution unless
    # they are reunited on disk. Recording the group lets a consumer honour that instead of
    # discovering it as a pile of missing textures.
    merge_group: str | None = None

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
        merge_group=pack.get("merge_group"),
    )


def dependencies(pack) -> set:
    """Packs that must be ingested before *pack* — the parents of its derived sources."""
    return {s.from_pack for s in pack.sources if s.kind == "derived" and s.from_pack}


def in_dependency_order(specs):
    """Order packs so every derived source's parent is ingested first.

    Alphabetical order is not safe: `malformed-fixtures` derives from `swf-ruffle-fixtures`
    and `rive-fixtures`, both of which sort after it. That went unnoticed for as long as
    vendor/ happened to be warm from earlier runs — the parents were already on disk, so the
    order never mattered. The first genuinely cold run failed on it, which is precisely the
    class of bug a warm working copy hides.
    """
    by_name = {s.name: s for s in specs}
    ordered, visiting, done = [], set(), set()

    def visit(name, trail):
        if name in done:
            return
        if name in visiting:
            cycle = " -> ".join(trail + [name])
            raise ValueError(f"derived-pack dependency cycle: {cycle}")
        pack = by_name.get(name)
        if pack is None:
            return          # not in this selection; the caller reports it usefully
        visiting.add(name)
        for parent in sorted(dependencies(pack)):
            visit(parent, trail + [name])
        visiting.discard(name)
        done.add(name)
        ordered.append(pack)

    for pack in specs:
        visit(pack.name, [])
    return ordered


def load_all(root: Path):
    return in_dependency_order([load_spec(p) for p in sorted(root.glob("*.toml"))])
