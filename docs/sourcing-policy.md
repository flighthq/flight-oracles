# Sourcing policy

How `flight-oracles` acquires upstream fixture and oracle data, what it is allowed to
republish, and why.

Status: **proposed** — the tiering model and the "extract, don't fork" recommendation are
awaiting sign-off. Everything below is grounded in licenses read from upstream on
2026-08-05; each claim cites the file it came from.

## The problem

Downstream repos currently inline their fixtures. `flighthq-ports/awayjs-examples` carries
~65 MB of assets in-tree (140 JPGs, 31 PNGs, 4 AWD, 4 OBJ, MD5/MD2/3DS meshes) purely so
its examples can run. Every consumer that wants the same coverage pays that cost again, and
nobody can tell from the tree where any of it came from or what it is licensed under.

We want the opposite: fixtures sourced from their real upstreams, provenance recorded,
license carried with the bytes, and the whole thing delivered as a versioned archive that a
test suite can download and pin.

## The core decision: don't fork. Extract, pin, and vendor selectively.

The instinct behind "should we fork and maintain a mirror" is right — upstream repos do get
taken down, renamed, and restructured, and a build that reaches out to a live URL is a build
that breaks on someone else's schedule. But a **fork is the wrong instrument** for it, on
three grounds.

**Ratio.** We want 409 `.riv` files from `rive-app/rive-runtime`. Those files total a few MB.
The repo is a full C++ renderer. Forking it to obtain its test assets means carrying, and
appearing to maintain, an entire graphics runtime we have no intention of maintaining.

**A fork republishes everything, including things upstream cannot license to us.**
`rive-app/rive-runtime` is MIT at the root and MIT again at `renderer/LICENSE`. It also
contains `renderer/webgpu_player/rivs/adventuretime_marceline-pb.riv`,
`spotify_kids_demo.riv`, and `spotify_kids_app_icon.riv`. Rive's MIT grant covers Rive's
copyright in its own work; it does not and cannot convey rights in Cartoon Network's
characters or Spotify's marks. A blanket mirror rebroadcasts those under our name. A curated
allowlist simply does not include them.

**Appearances.** Forking `EsotericSoftware/spine-runtimes` would put the Spine runtime code
under our org. That license
([`LICENSE`](https://github.com/EsotericSoftware/spine-runtimes/blob/4.2/LICENSE), updated
2025-04-05) permits integration and derivative works only where "each user of the Products
must obtain their own Spine Editor license." A fork reads as us distributing a Spine runtime
and quietly attaching that obligation to our downstreams. We don't want the runtime at all —
we want `examples/spineboy/`.

So: **extract the specific paths we need, pin them by upstream commit SHA, verify by
SHA-256, and vendor the bytes we are permitted to vendor.** Pinning a SHA gives
reproducibility; vendoring the bytes gives survival. Pinning alone does not survive a repo
deletion, which is precisely the failure mode the fork idea was reaching for.

## Redistribution tiers

Every source entry is classified. The tier drives whether its bytes land in a published
archive.

### Tier A — vendored and republished

License explicitly permits redistribution. Bytes are committed here and shipped inside
release archives, always accompanied by the upstream license text.

- **Spine `examples/spineboy/`** — `examples/spineboy/license.txt` states: *"The images in
  this project may be redistributed as long as they are accompanied by this license file.
  The images may not be used for commercial use of any kind. The project file is released
  into the public domain."* This is a direct grant to redistribute, with two conditions we
  must honor mechanically: the license file travels in the archive, and the
  **non-commercial** restriction is surfaced to consumers. Note the split — the `.spine`
  project file is public domain; the `images/` are the restricted part. The same
  `license.txt` pattern appears per-example throughout `spine-runtimes/examples/`, so other
  examples (`raptor`, `goblins`, `dragon`, `owl`, …) can be evaluated the same way, one at a
  time.
- **Rive-authored `.riv` assets** — MIT via the repo's root `LICENSE`, minus the third-party
  IP named above.
- **Ruffle-authored SWF tests** — `ruffle-rs/ruffle` is dual Apache-2.0/MIT.

### Tier B — pinned, fetched at build, never republished

License permits use but not redistribution, or provenance is documented but the chain of
rights is not ours to pass along. The manifest records URL + commit SHA + expected SHA-256;
the consumer or CI fetches it. We ship the recipe, not the bytes.

- Ruffle's imported corpora — `tests/tests/swfs/from_gnash/`, `from_avmplus/`,
  `from_shumway/`. These carry their *origin's* terms, not Ruffle's: Gnash is GPL-3.0,
  avmplus is MPL-2.0, Shumway is Apache-2.0. Each subdirectory has its own `README.md`
  documenting provenance — Ruffle already practices exactly the per-source provenance
  discipline we're adopting, and it's worth copying their format.

### Tier C — excluded

No license, or a license upstream had no right to grant.

- `adventuretime_marceline-pb.riv`, `spotify_kids_demo.riv`, `spotify_kids_app_icon.riv` and
  anything else carrying third-party characters or marks.
- **"SWF fixtures found online."** This is the single riskiest category in the whole plan. An
  unattributed SWF from a link-rotted fan site has no license, no author of record, and no
  way to answer a takedown. It should not enter the pipeline.

## Recommendation for SWF: generate, don't scavenge

For SWF specifically, the best fixtures are ones we compile ourselves in CI from source we
control. `open-flash/flex-sdk` mirrors the Apache Flex SDK under Apache-2.0; Haxe/OpenFL is
another route. Building from source gives unambiguous licensing, exactly-targeted coverage
of the tag or opcode under test, and a fixture that is readable and reviewable as source
rather than an opaque blob.

Use Ruffle's corpus on top of that for real-world edge cases the synthetic fixtures won't
reach — under Tier A for Ruffle-authored tests, Tier B for the imported ones.

## Oracles are derivative works

The distinction that makes this an *oracle* repo rather than a fixture repo — golden
renders, per-frame PNGs, expected parse trees — carries a licensing consequence worth
stating plainly: **a golden derived from a fixture is a derivative of that fixture.** A
rendered PNG of spineboy inherits spineboy's non-commercial restriction. It does not become
ours to license freely just because our pipeline produced the pixels.

Practical consequence: goldens are tiered by their *input*, not by who generated them, and a
Tier B fixture cannot have its goldens published either.

## Packaging

- **One archive per pack**, not one mega-archive — keeps downloads scoped and stays clear of
  the 2 GB per-file cap on GitHub release assets.
- Each archive contains `manifest.json` (per-file: source URL, upstream commit SHA, SHA-256,
  SPDX identifier or license name, attribution, tier), a `LICENSES/` directory with verbatim
  upstream license texts, and the assets.
- **Deterministic tar** — sorted entries, `mtime=0`, uid/gid 0, fixed permissions — so a
  rebuild at the same manifest produces byte-identical output.
- `SHA256SUMS` attached alongside, plus build provenance attestation.
- **No Git LFS.** Release assets don't bloat clones and don't consume an LFS bandwidth quota.

## Drift detection

A scheduled workflow re-resolves every Tier B pinned URL and compares SHA-256. On mismatch or
404 it opens an issue. This is the early warning for the takedown scenario that motivated the
fork question — and it costs one cron job rather than an org full of forks.
