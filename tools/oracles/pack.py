"""Build release archives from a lock plus the vendored bytes.

Two variants come out of one lock, so consumers pick their own posture and there is no
second policy to drift:

* ``-full``       every entry not explicitly excluded
* ``-permissive`` entries whose *declared* licence is a recognised permissive SPDX id,
                  with no unresolved ``depicts`` and ``commercialUse: true``

The name says what the filter did, not what it concluded. An earlier draft called it
``-clear``, which implies a clearance nobody here is in a position to grant.

Archives are byte-reproducible: entries sorted, ``mtime=0``, uid/gid 0, fixed modes, and
gzip written with a zeroed timestamp. Rebuilding the same lock produces the same bytes.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

__all__ = ["build_pack", "VARIANTS", "ExclusionBreach"]

VARIANTS = ("full", "permissive")

# Deliberately conservative. Weak-copyleft (MPL-2.0) and copyleft (GPL-3.0) declarations
# stay out of -permissive even though they are perfectly fine to redistribute, because
# the point of the variant is "nothing here needs a second thought".
PERMISSIVE_DECLARED = {
    "MIT", "Apache-2.0", "Apache-2.0 OR MIT", "MIT OR Apache-2.0",
    "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "CC0-1.0", "Unlicense",
    "0BSD", "CC-BY-4.0",
}


class ExclusionBreach(RuntimeError):
    """An excluded file's bytes reached a built archive.

    The removal guarantee is what makes "we will take it down" credible, so it is
    enforced mechanically at pack time rather than trusted to process.
    """


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_permissive(entry, source) -> bool:
    lic = source["license"]
    if lic["declared"] not in PERMISSIVE_DECLARED:
        return False
    if lic.get("commercialUse") is not True:
        return False
    depicts = entry.get("depicts")
    if depicts and depicts.get("status") != "resolved":
        return False
    return True


def select(lock, variant):
    """Return (entries, excluded_hashes) for *variant*."""
    sources = {s["id"]: s for s in lock["sources"]}
    kept, excluded = [], set()
    for entry in lock["files"]:
        source = sources[entry["sourceId"]]
        if not source["license"].get("redistributable", True):
            # Ingest should never have vendored these. Belt and braces: a declaration
            # that forbids redistribution outranks every variant.
            raise ExclusionBreach(
                f"{entry['path']}: source {entry['sourceId']!r} declares "
                f"redistributable=false but the file is present in the lock"
            )
        if entry.get("exclude"):
            excluded.add(entry["sha256"])
            continue
        if variant == "permissive" and not _is_permissive(entry, source):
            continue
        kept.append(entry)
    return kept, excluded


def _notice(lock, entries) -> str:
    sources = {s["id"]: s for s in lock["sources"]}
    used = sorted({e["sourceId"] for e in entries})
    out = [f"# Attribution — {lock['pack']['name']}", ""]
    out.append(
        "Every file below is recorded with the source it came from and the licence that "
        "source declared. We report the declaration; we do not adjudicate it."
    )
    out.append("")
    for sid in used:
        src = sources[sid]
        count = sum(1 for e in entries if e["sourceId"] == sid)
        lic = src["license"]
        out.append(f"## {sid}  ({count} files)")
        out.append("")
        if src.get("repo"):
            out.append(f"- Source: `{src['repo']}` @ `{src['commit']}`")
        if src.get("url"):
            out.append(f"- Retrieved from: {src['url']}")
        out.append(f"- Retrieved: {src.get('retrieved', 'unknown')}")
        out.append(f"- Declared licence: **{lic['declared']}** "
                   f"(scope: {lic['declaredScope']})")
        if lic.get("declaredFrom"):
            out.append(f"- Declared in: `{lic['declaredFrom']}`")
        if src.get("licenseSnapshot"):
            out.append(f"- Licence text: `LICENSES/{Path(src['licenseSnapshot']).name}`")
        if lic.get("covers"):
            out.append(f"- Covers: {lic['covers']}")
        if lic.get("commercialUse") is False:
            out.append("- **Commercial use: NOT permitted by the declared licence.**")
        elif lic.get("commercialUse") == "unknown":
            out.append("- Commercial use: unknown")
        if lic.get("sourceCode"):
            out.append(f"- Corresponding source: {lic['sourceCode']}")
        out.append("")

    flagged = [e for e in entries if e.get("depicts")]
    if flagged:
        out.append("## Third-party subject matter")
        out.append("")
        out.append(
            "The declared licence covers the upstream's authorship of these files. Rights "
            "in the subject matter they depict are separate and are not established here."
        )
        out.append("")
        for entry in flagged:
            dep = entry["depicts"]
            out.append(f"- `{entry['path']}` — {dep.get('subject')} "
                       f"({dep.get('rightsHolder', 'rights holder unknown')})")
        out.append("")
    return "\n".join(out)


def _readme(lock, variant, entries) -> str:
    name = lock["pack"]["name"]
    total = sum(e["size"] for e in entries)
    noncommercial = any(
        s["license"].get("commercialUse") is False
        for s in lock["sources"]
        if any(e["sourceId"] == s["id"] for e in entries)
    )
    out = [
        f"# {name}-{variant}",
        "",
        lock["pack"].get("summary", ""),
        "",
        f"{len(entries)} files, {total / 1e6:.2f} MB.",
        "",
        "## What this is for",
        "",
        "These are **fixtures**: inputs for testing format compatibility in the flight sdk "
        "packages. They are not source, and they are not assets to build products from. The "
        "use is functional — we care that a file decodes correctly, not what it depicts.",
        "",
        "## Provenance",
        "",
        "`manifest.json` records, per file: the source it came from, that source's pinned "
        "commit, the SHA-256, the container format version, and the licence the source "
        "declared. `NOTICE.md` is the human-readable rollup. `LICENSES/` holds each "
        "upstream licence text captured at the pinned commit.",
        "",
    ]
    if variant == "permissive":
        out += [
            "## About this variant",
            "",
            "Filtered to entries whose *declared* licence is a recognised permissive SPDX "
            "identifier, with no unresolved third-party subject matter and commercial use "
            "permitted. This is a filter over recorded metadata — it is not legal clearance, "
            "and it does not verify that any upstream's declaration was correct.",
            "",
        ]
    if noncommercial:
        out += [
            "## Commercial use",
            "",
            "**This archive contains files whose declared licence prohibits commercial use.** "
            "See `NOTICE.md` for which sources. Downstream consumers do not inherit a "
            "permissive licence just because the surrounding tooling is MIT.",
            "",
        ]
    out += [
        "## Corrections and removal",
        "",
        "We record what we know about where each file came from, and some declarations are "
        "marked unknown because they are. If you hold rights in something here and want it "
        "removed, open an issue on the flight-oracles repository — removal is a one-line "
        "change and a re-cut release, and we notify the upstream we obtained it from.",
        "",
    ]
    return "\n".join(out)


def _archive_members(lock, variant, entries, root):
    """Yield (archive path, bytes) for every member, in a stable order."""
    vendor = root / "vendor" / lock["pack"]["name"]
    sources = {s["id"]: s for s in lock["sources"]}
    used = sorted({e["sourceId"] for e in entries})

    members = {}
    for entry in entries:
        members[entry["path"]] = (vendor / entry["path"]).read_bytes()

    # Canonical SPDX texts for every declared licence in play.
    #
    # The snapshot captured from an upstream is the document that *makes* the declaration,
    # which is often a README pointing at a licence by URL — Ruffle's from_gnash/README.md
    # says "licensed under GPL 3.0" and links to gnu.org. That records what was declared,
    # but it does not discharge the obligation: GPL-3.0 and MPL-2.0 both require the
    # licence text itself to accompany a distribution. So we carry both — the declaration
    # as found, and the licence it names.
    spdx_dir = root / "licenses" / "spdx"
    for sid in used:
        declared = sources[sid]["license"]["declared"]
        for token in declared.replace(" OR ", " ").replace(" AND ", " ").split():
            text = spdx_dir / f"{token}.txt"
            if text.exists():
                members[f"LICENSES/{token}.txt"] = text.read_bytes()

    # Shared licence directory: one file per distinct declaration.
    for sid in used:
        snap = sources[sid].get("licenseSnapshot")
        if not snap:
            continue
        blob = (root / snap).read_bytes()
        members[f"LICENSES/{Path(snap).name}"] = blob
        # A file-adjacent declaration is also preserved in place. Spineboy's terms permit
        # redistribution "as long as they are accompanied by this license file", and the
        # safe reading of *accompanied* is beside the assets, not merely inside the tarball.
        adjacent = sources[sid].get("adjacentPath")
        if adjacent:
            members[adjacent] = blob

    manifest = {
        "pack": lock["pack"],
        "variant": variant,
        "sources": [sources[s] for s in used],
        "files": entries,
        "totals": {"files": len(entries), "bytes": sum(e["size"] for e in entries)},
    }
    members["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    members["NOTICE.md"] = (_notice(lock, entries) + "\n").encode()
    members["README.md"] = (_readme(lock, variant, entries) + "\n").encode()
    return sorted(members.items())


def _write_tar_gz(members, dest: Path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    with open(dest, "wb") as out:
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=9) as gz:
            gz.write(raw.getvalue())


def _write_zip(members, dest: Path):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)


def build_pack(lock, root: Path, out_dir: Path, version: str, *, zip_too: bool = True):
    """Build every variant of one pack. Returns a list of artifact records."""
    out_dir.mkdir(parents=True, exist_ok=True)
    name = lock["pack"]["name"]
    artifacts = []

    for variant in VARIANTS:
        entries, excluded_hashes = select(lock, variant)
        if not entries:
            continue
        members = _archive_members(lock, variant, entries, root)

        # The removal guarantee, enforced rather than trusted.
        present = {_sha256(data) for _, data in members}
        breach = present & excluded_hashes
        if breach:
            raise ExclusionBreach(
                f"{name}-{variant}: {len(breach)} excluded file(s) reached the archive: "
                + ", ".join(sorted(h[:12] for h in breach))
            )

        stem = f"{name}-{variant}-{version}"
        targets = [(out_dir / f"{stem}.tar.gz", _write_tar_gz)]
        if zip_too:
            targets.append((out_dir / f"{stem}.zip", _write_zip))
        for dest, writer in targets:
            writer(members, dest)
            digest = _sha256(dest.read_bytes())
            artifacts.append(
                {
                    "pack": name,
                    "variant": variant,
                    "file": dest.name,
                    "sha256": digest,
                    "size": dest.stat().st_size,
                    "files": len(entries),
                }
            )
    return artifacts
