"""Ingest: resolve a pinned upstream, vendor the bytes, and record what was declared.

Produces two durable outputs per pack:

* ``vendor/<pack>/…`` — the bytes themselves, committed. Pinning a commit gives
  reproducibility; vendoring gives *survival*. A pin alone does not outlive a repository
  being deleted, which is the failure mode mirroring was reaching for in the first place.
* ``locks/<pack>.lock.json`` — the generated per-file record: hash, size, format version,
  upstream path, and the licence declaration that covered it.

Licence texts are snapshotted at the pinned commit into ``licenses/``. If an upstream
relicenses, restructures, or disappears, our account of what they said stays verifiable —
the difference between *saying* we trusted the source and being able to show what we
trusted.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import functools
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import formats

USER_AGENT = "flight-oracles-ingest"
CACHE = Path(os.environ.get("ORACLES_CACHE", ".cache"))


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _request(url, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if accept:
        req.add_header("Accept", accept)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    return req


@functools.lru_cache(maxsize=None)
def resolve_commit(repo: str, ref: str) -> str:
    """Resolve a branch/tag to an immutable commit SHA.

    Prefers ``git ls-remote`` over the REST API for two reasons: it is not subject to the
    60-requests-per-hour unauthenticated API limit, and it works wherever git credentials
    do. Memoised because a pack may hold hundreds of sources against one repository —
    glTF-Sample-Assets is 146 blocks, which would otherwise be 146 identical lookups and
    an immediate rate-limit failure.
    """
    try:
        out = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{repo}.git", ref, f"refs/heads/{ref}",
             f"refs/tags/{ref}"],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout
        for line in out.splitlines():
            sha, _, name = line.partition("\t")
            if name in (ref, f"refs/heads/{ref}", f"refs/tags/{ref}") and len(sha) == 40:
                return sha
    except (subprocess.SubprocessError, OSError):
        pass  # fall through to the API

    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    with urllib.request.urlopen(_request(url, "application/vnd.github+json")) as resp:
        return json.load(resp)["sha"]


def fetch_tarball(repo: str, commit: str) -> Path:
    """Download (and cache) the repo tarball at *commit*.

    One request beats thousands of raw-blob fetches, and it is the only way to pull
    4,900 Ruffle SWFs without arguing with rate limits.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"{repo.replace('/', '__')}@{commit[:12]}.tar.gz"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    _log(f"  fetching {url}")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(_request(url)) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.replace(dest)
    return dest


def _iter_members(tarball: Path):
    """Yield (repo-relative path, bytes) for every regular file in *tarball*."""
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) != 2:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            yield parts[1], handle.read()


def fetch_tree(repo: str, commit: str) -> list:
    """List every blob in *repo* at *commit*, cached. One request, no download."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"tree-{repo.replace('/', '__')}@{commit[:12]}.json"
    if dest.exists():
        return json.loads(dest.read_text())
    url = f"https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1"
    with urllib.request.urlopen(_request(url, "application/vnd.github+json")) as resp:
        doc = json.load(resp)
    if doc.get("truncated"):
        raise ValueError(
            f"{repo}@{commit[:12]}: git tree response was truncated — blob mode cannot "
            f"enumerate this repository reliably; use the default tarball mode"
        )
    tree = [x for x in doc.get("tree", []) if x.get("type") == "blob"]
    dest.write_text(json.dumps(tree))
    return tree


LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


def _lfs_pointer(data: bytes):
    """Parse a Git LFS pointer, or return None if this is real content.

    raw.githubusercontent serves the *pointer* for LFS-tracked paths, not the object. A
    130-byte text stub sitting where a texture should be would sail through every check we
    have — it hashes fine, it is byte-identical on re-ingest, and only a decoder would ever
    notice. Silent corpus corruption is the worst outcome this pipeline can produce, so
    pointers are detected and resolved rather than stored.
    """
    if not data.startswith(LFS_POINTER):
        return None
    oid = size = None
    for line in data[:512].decode("utf-8", "replace").splitlines():
        if line.startswith("oid sha256:"):
            oid = line.split(":", 1)[1].strip()
        elif line.startswith("size "):
            try:
                size = int(line.split(None, 1)[1])
            except ValueError:
                pass
    return (oid, size) if oid and size is not None else None


def _lfs_fetch(repo: str, oid: str, size: int) -> bytes:
    """Resolve one LFS object through the batch API."""
    body = json.dumps({
        "operation": "download",
        "transfers": ["basic"],
        "objects": [{"oid": oid, "size": size}],
    }).encode()
    req = urllib.request.Request(
        f"https://github.com/{repo}.git/info/lfs/objects/batch", data=body,
        headers={"User-Agent": USER_AGENT,
                 "Accept": "application/vnd.git-lfs+json",
                 "Content-Type": "application/vnd.git-lfs+json"})
    with urllib.request.urlopen(req) as resp:
        doc = json.load(resp)
    objects = doc.get("objects") or []
    if not objects or "actions" not in objects[0]:
        raise ValueError(
            f"{repo}: LFS object {oid[:12]} has no download action — "
            f"{objects[0].get('error') if objects else 'empty batch response'}")
    action = objects[0]["actions"]["download"]
    dl = urllib.request.Request(action["href"], headers=action.get("header", {}))
    with urllib.request.urlopen(dl) as resp:
        data = resp.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != oid:
        raise ValueError(f"{repo}: LFS object hash mismatch (want {oid[:12]}, got {actual[:12]})")
    return data


def _blob_cached(repo: str, commit: str, path: str, blob_sha: str) -> bytes:
    """Fetch one file's bytes, cached by its git blob SHA.

    Keying the cache on the blob SHA rather than the path means the same content
    referenced from several sources is fetched once, and a re-ingest at an unchanged
    pin is free.
    """
    cache_dir = CACHE / "blobs" / blob_sha[:2]
    cached = cache_dir / blob_sha
    if cached.exists():
        return cached.read_bytes()
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{urllib.parse.quote(path)}"
    with urllib.request.urlopen(_request(url)) as resp:
        data = resp.read()
    pointer = _lfs_pointer(data)
    if pointer is not None:
        data = _lfs_fetch(repo, *pointer)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def _iter_blobs(repo: str, commit: str, wanted: list):
    """Yield (repo-relative path, bytes) for *wanted* tree entries, fetched in parallel.

    Sparse alternative to downloading a whole repository. glTF-Sample-Assets is 1.4 GB;
    the slice we actually want is a fraction of that, and no CI run should pay for the
    rest on every build.
    """
    def one(entry):
        return entry["path"], _blob_cached(repo, commit, entry["path"], entry["sha"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        yield from pool.map(one, wanted)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_pack(spec, root: Path, *, update: bool = False) -> dict:
    """Vendor every selected file for *spec* and return its lock document.

    Commit resolution follows the package-manager split: the spec carries a *ref*
    (``main``, ``4.2``) expressing intent, and the lock carries the resolved *commit*.
    A plain re-ingest reuses the locked commit, so it is reproducible; ``--update``
    re-resolves the ref and adopts whatever it points at now. Without this, "pinned"
    would silently mean "latest", and CI would drift from the lock on every run.
    """
    vendor_root = root / "vendor" / spec.name
    licenses_root = root / "licenses"
    licenses_root.mkdir(parents=True, exist_ok=True)

    try:
        pinned = {s["id"]: s.get("commit") for s in load_lock(spec.name, root)["sources"]}
    except FileNotFoundError:
        pinned = {}

    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    lock_sources, lock_files = [], []
    seen_dest = {}

    for source in spec.sources:
        _log(f"[{spec.name}] source {source.id}")

        if not source.license.redistributable:
            # Recorded so the record of having looked is durable, never vendored. This is
            # compliance with an explicit declaration, not a risk judgement.
            _log(f"  SKIPPED — declaration forbids redistribution: "
                 f"{source.license.prohibition}")
            lock_sources.append(
                {
                    "id": source.id,
                    "kind": source.kind,
                    "repo": source.repo,
                    "ref": source.ref,
                    "commit": source.commit,
                    "license": source.license.to_json(),
                    "vendored": False,
                }
            )
            continue

        if source.kind == "recovered":
            # No upstream declaration to snapshot and nobody to notify on a dispute.
            # These are ingested from files already sitting in vendor/.
            lock_sources.append(
                {
                    "id": source.id,
                    "kind": "recovered",
                    "url": source.url,
                    "retrieved": source.retrieved or today,
                    "license": source.license.to_json(),
                }
            )
            continue

        commit = source.commit or pinned.get(source.id)
        if update or not commit:
            resolved = resolve_commit(source.repo, source.ref or "HEAD")
            if commit and resolved != commit:
                _log(f"  updating {source.ref}: {commit[:12]} -> {resolved[:12]}")
            else:
                _log(f"  resolved {source.ref} -> {resolved}")
            commit = resolved
        else:
            _log(f"  pinned at {commit[:12]} (--update to move)")
        if source.fetch == "blobs":
            tree = fetch_tree(source.repo, commit)
            extra = {source.license.declared_from} | {
                layer.get("declaredFrom") for layer in source.license.underlying
            }
            wanted = [
                e for e in tree
                if source.selects(e["path"]) or e["path"] in extra
            ]
            _log(f"  {len(wanted)} of {len(tree)} blobs selected")
            members = _iter_blobs(source.repo, commit, wanted)
        else:
            members = _iter_members(fetch_tarball(source.repo, commit))

        license_blob = None
        # Attribution is the obligation the layered model creates, and naming an instrument
        # without capturing its text is a weak form of it — especially since these are the
        # documents most likely to move or disappear.
        underlying_blobs = {}
        count = 0
        for upstream_path, data in members:
            if source.license.declared_from and upstream_path == source.license.declared_from:
                license_blob = data
            for layer in source.license.underlying:
                if layer.get("declaredFrom") == upstream_path:
                    underlying_blobs[upstream_path] = data
            if not source.selects(upstream_path):
                continue

            dest = source.dest_for(upstream_path)
            if dest in seen_dest:
                raise ValueError(
                    f"{spec.name}: destination collision at {dest!r} "
                    f"(sources {seen_dest[dest]!r} and {source.id!r})"
                )
            seen_dest[dest] = source.id

            target = vendor_root / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

            if _lfs_pointer(data) is not None:
                pointer = _lfs_pointer(data)
                data = _lfs_fetch(source.repo, *pointer)
            fmt = formats.detect(data, dest)
            entry = {
                "path": dest,
                "sourceId": source.id,
                "upstreamPath": upstream_path,
                "sha256": _sha256(data),
                "size": len(data),
            }
            if fmt is not None:
                entry["format"] = dict(fmt)
            entry.update(spec.annotations.get(dest, {}))
            lock_files.append(entry)
            count += 1

        if count == 0:
            raise ValueError(
                f"{spec.name}: source {source.id!r} selected no files — check `include` "
                f"patterns against {source.repo}@{commit[:12]}"
            )
        _log(f"  vendored {count} files")

        snapshot_rel = None
        adjacent = None
        if source.license.declared_from:
            if license_blob is None:
                raise ValueError(
                    f"{spec.name}: source {source.id!r} declares license from "
                    f"{source.license.declared_from!r}, which is not present at "
                    f"{source.repo}@{commit[:12]}"
                )
            snapshot = licenses_root / f"{source.id}@{commit[:12]}.txt"
            snapshot.write_bytes(license_blob)
            snapshot_rel = f"licenses/{snapshot.name}"
            if source.license.is_file_adjacent:
                # Where the licence must sit *beside* the assets in the built archive.
                # Run it through the same strip/dest mapping the assets took, so it lands
                # exactly where it sat upstream relative to them.
                adjacent = source.dest_for(source.license.declared_from)

        layers = []
        for layer in source.license.underlying:
            entry = dict(layer)
            blob = underlying_blobs.get(layer.get("declaredFrom"))
            if blob is not None:
                name = f"{source.id}-underlying-{len(layers)}@{commit[:12]}.txt"
                (licenses_root / name).write_bytes(blob)
                entry["snapshot"] = f"licenses/{name}"
            elif layer.get("declaredFrom"):
                raise ValueError(
                    f"{spec.name}: source {source.id!r} names underlying instrument "
                    f"{layer['declared']!r} at {layer['declaredFrom']!r}, which is not "
                    f"present at {source.repo}@{commit[:12]}"
                )
            layers.append(entry)

        lock_source = {
            "id": source.id,
            "kind": source.kind,
            "repo": source.repo,
            "ref": source.ref,
            "commit": commit,
            "retrieved": today,
            "license": {**source.license.to_json(),
                        **({"underlying": layers} if layers else {})},
        }
        if snapshot_rel:
            lock_source["licenseSnapshot"] = snapshot_rel
        if adjacent:
            lock_source["adjacentPath"] = adjacent
        lock_sources.append(lock_source)

    # An annotation whose path matches nothing is almost always a typo or a path that
    # moved upstream. Silently doing nothing is the worst outcome for a provenance tool:
    # the record would claim a `depicts` or `exclude` that never applied to any file.
    vendored_paths = {e["path"] for e in lock_files}
    orphans = sorted(set(spec.annotations) - vendored_paths)
    if orphans:
        raise ValueError(
            f"{spec.name}: {len(orphans)} annotation(s) match no vendored file — "
            f"fix the path or drop the annotation:\n  " + "\n  ".join(orphans)
        )

    lock_files.sort(key=lambda e: e["path"])
    return {
        "pack": {"name": spec.name, "kind": spec.kind, "summary": spec.summary,
                 **({"mergeGroup": spec.merge_group} if spec.merge_group else {})},
        "sources": lock_sources,
        "files": lock_files,
        "totals": {
            "files": len(lock_files),
            "bytes": sum(e["size"] for e in lock_files),
        },
    }


def write_lock(lock: dict, root: Path) -> Path:
    locks = root / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    path = locks / f"{lock['pack']['name']}.lock.json"
    path.write_text(json.dumps(lock, indent=2, sort_keys=False) + "\n")
    return path


def load_lock(name: str, root: Path) -> dict:
    path = root / "locks" / f"{name}.lock.json"
    if not path.exists():
        raise FileNotFoundError(f"no lock for pack {name!r} — run `ingest` first")
    return json.loads(path.read_text())


def verify_pack(lock: dict, root: Path) -> list:
    """Re-hash vendored bytes against the lock. Returns a list of problems."""
    vendor_root = root / "vendor" / lock["pack"]["name"]
    problems = []
    for entry in lock["files"]:
        path = vendor_root / entry["path"]
        if not path.exists():
            problems.append(f"missing: {entry['path']}")
            continue
        actual = _sha256(path.read_bytes())
        if actual != entry["sha256"]:
            problems.append(
                f"hash mismatch: {entry['path']} "
                f"(lock {entry['sha256'][:12]}, vendor {actual[:12]})"
            )
    return problems


def drift_pack(spec, lock: dict) -> list:
    """Re-resolve pinned upstreams and report divergence from the lock.

    Early warning for the takedown/restructure scenario: one cron job rather than an
    org full of forks. Reports rather than raises — a 404 is a finding, not a crash.
    """
    findings = []
    by_id = {s["id"]: s for s in lock["sources"]}
    for source in spec.sources:
        if source.kind != "upstream":
            continue
        locked = by_id.get(source.id)
        if locked is None:
            findings.append(f"{source.id}: present in spec but absent from lock")
            continue
        try:
            head = resolve_commit(source.repo, source.ref or "HEAD")
        except urllib.error.HTTPError as exc:
            findings.append(f"{source.id}: {source.repo}@{source.ref} unreachable (HTTP {exc.code})")
            continue
        except urllib.error.URLError as exc:
            findings.append(f"{source.id}: {source.repo}@{source.ref} unreachable ({exc.reason})")
            continue
        if head != locked["commit"]:
            findings.append(
                f"{source.id}: {source.ref} moved {locked['commit'][:12]} -> {head[:12]} "
                f"(pin still valid; re-ingest to adopt)"
            )
    return findings


def verify_merge_group(locks, root: Path) -> list:
    """Resolve every external URI a glTF declares, across a merge group's vendored trees.

    A merge group only works if the union is complete: geometry in one pack, its textures in
    another, reunited on extraction. An include-glob edited a year from now could drop a
    texture and nothing else would notice — each pack would verify fine and the models would
    simply render wrong. That is the property worth checking, so it is checked.
    """
    from urllib.parse import unquote

    roots = [root / "vendor" / lock["pack"]["name"] for lock in locks]
    problems = []
    for lock in locks:
        base_root = root / "vendor" / lock["pack"]["name"]
        for entry in lock["files"]:
            if not entry["path"].endswith(".gltf"):
                continue
            try:
                doc = json.loads((base_root / entry["path"]).read_bytes())
            except (ValueError, OSError):
                continue
            rel_dir = Path(entry["path"]).parent
            uris = [b.get("uri") for b in doc.get("buffers", []) if b.get("uri")]
            uris += [i.get("uri") for i in doc.get("images", []) if i.get("uri")]
            for uri in uris:
                if uri.startswith("data:"):
                    continue
                target = rel_dir / unquote(uri)
                if not any((r / target).exists() for r in roots):
                    problems.append(f"{lock['pack']['name']}/{entry['path']} -> {uri}")
    return problems
