"""flight-oracles pipeline CLI.

    python3 -m oracles ingest [pack…] [--update]   resolve, vendor, and lock
    python3 -m oracles verify [pack…]              re-hash vendored bytes against the lock
    python3 -m oracles pack   [pack…] --version V  build release archives
    python3 -m oracles drift  [pack…]              re-resolve pins, report divergence
    python3 -m oracles show   [pack…]              summarise what is locked

Stdlib only, on purpose: a pipeline that must run unattended in CI for years is worth
more than nicer manifest ergonomics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import ingest as ingest_mod
from . import pack as pack_mod
from . import references as refs_mod
from . import spec as spec_mod


def _root(args) -> Path:
    return Path(args.root).resolve()


def _specs(args):
    all_specs = spec_mod.load_all(_root(args) / "sources")
    if not args.packs:
        return all_specs
    by_name = {s.name: s for s in all_specs}
    missing = set(args.packs) - set(by_name)
    if missing:
        sys.exit(f"unknown pack(s): {', '.join(sorted(missing))}")
    return [by_name[n] for n in args.packs]


def cmd_ingest(args):
    root = _root(args)
    for spec in _specs(args):
        lock = ingest_mod.ingest_pack(spec, root, update=args.update)
        path = ingest_mod.write_lock(lock, root)
        total = lock["totals"]
        print(f"{spec.name}: {total['files']} files, {total['bytes'] / 1e6:.2f} MB -> {path}")
    return 0


def _locked(spec, root, args):
    """Load a pack's lock, or None if it has not been ingested yet.

    A spec can legitimately exist without a lock — it declares intent to adopt a corpus
    that nobody has pulled the trigger on (see rive-fixtures-unit and its size decision).
    Skipping with a notice beats dying when the user asked for "all packs".
    """
    try:
        return ingest_mod.load_lock(spec.name, root)
    except FileNotFoundError:
        if args.packs:  # named explicitly — silence would be wrong
            sys.exit(f"{spec.name}: not ingested yet — run `ingest {spec.name}`")
        print(f"{spec.name}: skipped (not ingested)")
        return None


def cmd_verify(args):
    root = _root(args)
    failed = False
    groups = {}
    for spec in _specs(args):
        lock = _locked(spec, root, args)
        if lock is None:
            continue
        if spec.merge_group:
            groups.setdefault(spec.merge_group, []).append(lock)
        problems = ingest_mod.verify_pack(lock, root)
        if problems:
            failed = True
            print(f"{spec.name}: {len(problems)} problem(s)")
            for problem in problems[:20]:
                print(f"  {problem}")
            if len(problems) > 20:
                print(f"  … {len(problems) - 20} more")
        else:
            print(f"{spec.name}: OK ({lock['totals']['files']} files)")

    # Two packs drawn from one repository at different commits describe different snapshots
    # of it. That is almost never intended — it happens when packs are ingested weeks apart
    # and the ref moves underneath — and nothing else would surface it, because each pack
    # verifies perfectly against its own lock.
    # Keyed on (repo, ref), not repo alone: two packs deliberately tracking different
    # branches of one repository — spine-fixtures on 4.2 and spine-fixtures-38 on 3.8 —
    # SHOULD sit at different commits. What is almost never intended is one ref resolving
    # differently across packs, which happens when they are ingested weeks apart while the
    # branch moves underneath, and which nothing else would surface because each pack
    # verifies perfectly against its own lock.
    pins = {}
    for spec in _specs(args):
        try:
            lock = ingest_mod.load_lock(spec.name, root)
        except FileNotFoundError:
            continue
        for src in lock["sources"]:
            if src.get("repo") and src.get("commit"):
                key = (src["repo"], src.get("ref") or "HEAD")
                pins.setdefault(key, {}).setdefault(src["commit"], set()).add(spec.name)
    for (repo, ref), commits in sorted(pins.items()):
        if len(commits) > 1:
            failed = True
            print(f"{repo}@{ref}: one ref pinned at {len(commits)} different commits —")
            for commit, packs in sorted(commits.items()):
                print(f"  {commit[:12]}  {', '.join(sorted(packs))}")
            print("  re-ingest the lagging pack(s) with --update to align them")

    # Descriptors that name files nobody shipped. Resolution is checked across every
    # ingested pack at once, so a deliberate split (geometry here, textures there) resolves
    # while a genuine omission does not.
    all_locks = []
    for spec in _specs(args):
        try:
            all_locks.append(ingest_mod.load_lock(spec.name, root))
        except FileNotFoundError:
            continue
    if all_locks:
        dangling = refs_mod.unresolved(all_locks, root)
        if dangling:
            by_pack = {}
            for pack, src, ref in dangling:
                by_pack.setdefault(pack, []).append((src, ref))
            print(f"unresolved references: {len(dangling)} across {len(by_pack)} pack(s)")
            for pack in sorted(by_pack):
                items = by_pack[pack]
                print(f"  {pack}: {len(items)}")
                for src, ref in items[:3]:
                    print(f"    {src} -> {ref}")
            print("  (a descriptor-only pack is a valid choice; an accidental one is not)")
        else:
            print("references: OK (every descriptor's external files are present)")

    for name, locks in sorted(groups.items()):
        if len(locks) < 2:
            print(f"merge group {name}: only one pack ingested — resolution unchecked")
            continue
        problems = ingest_mod.verify_merge_group(locks, root)
        if problems:
            failed = True
            print(f"merge group {name}: {len(problems)} unresolved reference(s)")
            for item in problems[:15]:
                print(f"  {item}")
            if len(problems) > 15:
                print(f"  … {len(problems) - 15} more")
        else:
            total = sum(l["totals"]["files"] for l in locks)
            print(f"merge group {name}: OK (every external URI resolves across "
                  f"{len(locks)} packs, {total} files)")
    return 1 if failed else 0


def _source_commit(root: Path):
    """The commit this build came from, if the tree is a git checkout.

    Recorded because a release otherwise says nothing about its own provenance. 0.1.0 was
    built from a commit main had already moved past — a tag pins a commit, and the fix that
    landed afterwards was not in it. Diagnosing that meant rebuilding an archive and
    comparing digests; this makes it a field.
    """
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15, check=True)
        commit = out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                           capture_output=True, text=True, timeout=15).stdout.strip()
    info = {"commit": commit}
    if dirty:
        # A release built from uncommitted changes cannot be reproduced from any commit.
        info["dirty"] = True
    return info


def cmd_pack(args):
    root = _root(args)
    out_dir = root / args.out
    index = {"version": args.version, "packs": []}
    source = _source_commit(root)
    if source:
        index["builtFrom"] = source
        note = " (WORKING TREE DIRTY)" if source.get("dirty") else ""
        print(f"building {args.version} from commit {source['commit'][:12]}{note}", flush=True)
        if source.get("dirty"):
            print("  warning: uncommitted changes present — this build is not reproducible "
                  "from any commit", flush=True)
    for spec in _specs(args):
        lock = _locked(spec, root, args)
        if lock is None:
            continue
        print(f"{spec.name}: verifying {lock['totals']['files']} files "
              f"({lock['totals']['bytes'] / 1e6:.0f} MB)...", flush=True)
        problems = ingest_mod.verify_pack(lock, root)
        if problems:
            sys.exit(
                f"{spec.name}: vendored bytes do not match the lock "
                f"({len(problems)} problem(s)) — run `verify` for detail"
            )
        artifacts = pack_mod.build_pack(
            lock, root, out_dir, args.version,
            progress=lambda msg: print(msg, flush=True),
        )
        if lock["pack"].get("mergeGroup"):
            for art in artifacts:
                art["mergeGroup"] = lock["pack"]["mergeGroup"]
        for art in artifacts:
            print(f"{art['file']}  {art['files']} files  "
                  f"{art['size'] / 1e6:.2f} MB  sha256:{art['sha256'][:12]}")
        index["packs"].extend(artifacts)

    (out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    sums = "".join(f"{a['sha256']}  {a['file']}\n" for a in sorted(
        index["packs"], key=lambda a: a["file"]))
    (out_dir / "SHA256SUMS").write_text(sums)
    print(f"\nwrote {out_dir / 'index.json'} and SHA256SUMS ({len(index['packs'])} artifacts)")
    return 0


def cmd_drift(args):
    root = _root(args)
    findings = []
    for spec in _specs(args):
        lock = _locked(spec, root, args)
        if lock is None:
            continue
        for finding in ingest_mod.drift_pack(spec, lock):
            findings.append(f"{spec.name}: {finding}")
    if findings:
        print("\n".join(findings))
        return 2 if args.fail_on_drift else 0
    print("no drift")
    return 0


def cmd_show(args):
    root = _root(args)
    for spec in _specs(args):
        lock = _locked(spec, root, args)
        if lock is None:
            continue
        print(f"\n=== {spec.name} ({lock['pack']['kind']}) ===")
        print(f"  {lock['totals']['files']} files, {lock['totals']['bytes'] / 1e6:.2f} MB")
        for source in lock["sources"]:
            lic = source["license"]
            count = sum(1 for f in lock["files"] if f["sourceId"] == source["id"])
            commercial = {True: "yes", False: "NO", "unknown": "unknown"}[
                lic.get("commercialUse", "unknown")]
            print(f"  - {source['id']}: {count} files")
            print(f"      declared {lic['declared']} ({lic['declaredScope']}), "
                  f"commercial-use {commercial}")
            if source.get("commit"):
                print(f"      {source['repo']}@{source['commit'][:12]}")
        fmts = {}
        for entry in lock["files"]:
            fmt = entry.get("format") or {}
            key = (fmt.get("kind"), fmt.get("version"))
            fmts[key] = fmts.get(key, 0) + 1
        print("  formats: " + ", ".join(
            f"{k[0] or 'unrecognised'}"
            + (f" v{k[1]}" if k[1] else "")
            + f" ×{v}"
            for k, v in sorted(fmts.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ))
        flagged = [f for f in lock["files"] if f.get("depicts")]
        if flagged:
            print(f"  depicts-annotated: {len(flagged)}")
        excluded = [f for f in lock["files"] if f.get("exclude")]
        if excluded:
            print(f"  excluded: {len(excluded)}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="oracles", description=__doc__)
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, help=fn.__doc__, **kw)
        p.add_argument("packs", nargs="*", help="pack names (default: all)")
        p.set_defaults(fn=fn)
        return p

    p = add("ingest", cmd_ingest)
    p.add_argument("--update", action="store_true",
                   help="re-resolve refs to current HEAD instead of using the pinned commit")

    add("verify", cmd_verify)

    p = add("pack", cmd_pack)
    p.add_argument("--version", required=True, help="release version, e.g. 0.1.0")
    p.add_argument("--out", default="dist")

    p = add("drift", cmd_drift)
    p.add_argument("--fail-on-drift", action="store_true")

    add("show", cmd_show)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
