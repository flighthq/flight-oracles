# Sourcing policy

How `flight-oracles` acquires upstream fixture and oracle data, what it republishes, and why.

Grounded in licenses read from upstream on 2026-08-05; each claim cites the file it came
from. This is engineering judgment about a project's posture, not legal advice.

## What this data is for

These archives are **fixtures**, not source and not assets to build products from. They exist
to be funnelled through the flight sdk packages to test format compatibility — does our SWF
parser agree with Ruffle's, does our Rive renderer produce the same frame, does our Spine
runtime match the reference. The use is functional and non-expressive: we care that a file
*decodes correctly*, not what it depicts.

That intent should be stated in every archive's README, because it is the honest description
of the use and the one that matters most if anyone ever asks.

## The problem

Downstream repos currently inline their fixtures. `flighthq-ports/awayjs-examples` carries
~65 MB of assets in-tree (140 JPGs, 31 PNGs, 4 AWD, 4 OBJ, MD5/MD2/3DS meshes) purely so its
examples can run. Every consumer wanting the same coverage pays that cost again, and nobody
can tell from the tree where any of it came from or what it's licensed under.

## Governing principle: provenance and prompt removal

Every file we publish carries, in a machine-readable manifest: the upstream URL, the upstream
commit SHA, its SHA-256, the license as found, and attribution. Verbatim license texts ship
in a `LICENSES/` directory alongside.

If someone tells us we shouldn't be carrying a file, we point at the recorded provenance and
remove it. That is the whole mitigation, and it is the same posture every serious test corpus
in this ecosystem runs on — Ruffle documents provenance per-subdirectory in
`tests/tests/swfs/from_*/README.md` for exactly this reason.

**This only works if removal is genuinely cheap**, so it is a hard design requirement, not an
aspiration:

- No asset is ever committed as a loose blob. Everything resolves through a manifest entry.
- Deleting one manifest entry and re-tagging produces a release without that file.
- No downstream consumer pins anything finer-grained than a release tag, so they pick up the
  removal by bumping a version.

## The core decision: don't fork. Extract, pin, vendor.

The instinct behind "should we fork and mirror" is right — upstream repos get taken down,
renamed, and restructured, and a build reaching a live URL breaks on someone else's schedule.
But a fork is the wrong instrument.

**Ratio.** We want 409 `.riv` files from `rive-app/rive-runtime`. They total a few MB; the
repo is a full C++ renderer. Forking it to obtain test assets means carrying, and appearing
to maintain, a graphics runtime we have no intention of maintaining.

**Appearances.** Forking `EsotericSoftware/spine-runtimes` would put the Spine runtime code
under our org. That license
([`LICENSE`](https://github.com/EsotericSoftware/spine-runtimes/blob/4.2/LICENSE), updated
2025-04-05) permits derivative works only where "each user of the Products must obtain their
own Spine Editor license." A fork reads as us distributing a Spine runtime and attaching that
obligation to our downstreams. We want `examples/spineboy/`, not the runtime.

**A fork can't be curated.** It republishes whatever upstream has, wholesale, forever — which
removes the per-file judgment the section below depends on.

So: extract the specific paths we need, pin them by upstream commit SHA, verify by SHA-256,
and vendor the bytes. Pinning gives reproducibility; vendoring gives survival. Pinning alone
does not survive a repo deletion, which is the failure mode the fork idea was reaching for.

## What we ship

**Default: everything we pull, with provenance.** Including:

- **Spine `examples/spineboy/`** — `examples/spineboy/license.txt` grants this directly:
  *"The images in this project may be redistributed as long as they are accompanied by this
  license file. The images may not be used for commercial use of any kind. The project file
  is released into the public domain."* Two conditions we honor mechanically: the license
  file ships in the archive, and the non-commercial restriction is surfaced loudly (see
  below). Note the split — the `.spine` project file is public domain; the `images/` are the
  restricted part. The same per-example `license.txt` pattern runs throughout
  `spine-runtimes/examples/`, so `raptor`, `goblins`, `dragon`, `owl` and the rest can each
  be evaluated the same way.
- **Rive `.riv` assets** — MIT via the repo's root `LICENSE` and `renderer/LICENSE`.
- **Ruffle SWF tests** — `ruffle-rs/ruffle` is dual Apache-2.0/MIT.
- **Ruffle's imported corpora** — `from_avmplus/` (MPL-2.0) and `from_shumway/`
  (Apache-2.0). Both file-level permissive; carrying the license text satisfies them.

### One corpus with a real mechanical obligation

`tests/tests/swfs/from_gnash/` is GPL-3.0 by origin. This isn't a complaint-risk question —
GPL carries *conditions*. For generated SWFs (`misc-ming.all`, `misc-swfmill.all`,
`misc-mtasc.all`, `misc-swfc.all`) the corresponding source is the generator script, and
those live in the Gnash repo. Satisfiable by recording a source pointer in the manifest
entry; not satisfiable by ignoring it. Ship it, with that pointer.

### The non-commercial flag

Spineboy's terms bind downstream consumers, and flight sdk's test suite is the funnel that
delivers them. Any file whose license restricts commercial use gets a `commercialUse: false`
field in the manifest and a prominent notice in the archive README. Our downstreams are MIT;
consumers will otherwise reasonably assume the archive is too.

## What we don't ship

Not a risk ranking — these are the files where the provenance-and-removal mechanism *cannot
be executed*, which is the same principle applied consistently.

**Unattributable files.** "SWF fixtures found online" from link-rotted fan sites and forum
attachments. There is no provenance line to write, no license as found, and no author to
point an inquiry at. The mitigation this policy rests on is simply unavailable.

**Files upstream had no right to grant.** `adventuretime_marceline-pb.riv`,
`spotify_kids_demo.riv`, `spotify_kids_app_icon.riv` in `rive-app/rive-runtime`. The
provenance line is writable but reads "MIT from Rive, who did not own the underlying
character or mark" — a footnote we'd re-explain indefinitely. The deciding factor is cost:
there are 406 other `.riv` files exercising the identical renderer paths. Excluding three
buys back nothing we need.

## Recommendation for SWF: generate, don't scavenge

The gap left by excluding unattributable SWFs is best filled by compiling fixtures ourselves
in CI. `open-flash/flex-sdk` mirrors the Apache Flex SDK under Apache-2.0; Haxe/OpenFL is
another route. Building from source gives unambiguous provenance, coverage targeted at the
exact tag or opcode under test, and a fixture reviewable as source rather than an opaque
blob. Ruffle's corpus then covers the real-world edge cases synthetic fixtures won't reach.

## Oracles inherit their fixture's terms

Golden renders, per-frame PNGs, and expected parse trees are derivative of the fixtures that
produced them. A rendered PNG of spineboy inherits spineboy's non-commercial restriction; it
doesn't become freely licensable because our pipeline made the pixels. Goldens carry the
manifest fields of their input, not of their generator.

## Packaging

- **One archive per pack**, not one mega-archive — keeps downloads scoped and stays clear of
  the 2 GB per-file cap on GitHub release assets.
- Each archive contains `manifest.json` (per file: source URL, upstream commit SHA, SHA-256,
  license, attribution, `commercialUse`, any source pointer), a `LICENSES/` directory of
  verbatim upstream texts, and a README stating the compatibility-testing intent.
- **Deterministic tar** — sorted entries, `mtime=0`, uid/gid 0, fixed permissions — so a
  rebuild at the same manifest is byte-identical.
- `SHA256SUMS` attached alongside, plus build provenance attestation.
- **No Git LFS.** Release assets don't bloat clones or consume an LFS bandwidth quota.

## Drift detection

A scheduled workflow re-resolves every pinned upstream URL and compares SHA-256. On mismatch
or 404 it opens an issue. This is the early warning for the takedown scenario that motivated
the fork question — one cron job rather than an org full of forks.
