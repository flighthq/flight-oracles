# Sourcing policy

How `flight-oracles` acquires upstream fixture and oracle data, what it records about it, and
how anything can be removed on request.

Grounded in licenses read from upstream on 2026-08-05. This is engineering judgment about a
project's posture, not legal advice.

## What this data is for

These archives are **fixtures**, not source and not assets to build products from. They exist
to be funnelled through the flight sdk packages to test format compatibility — does our SWF
parser agree with Ruffle's, does our Rive renderer produce the same frame, does our Spine
runtime match the reference. The use is functional and non-expressive: we care that a file
*decodes correctly*, not what it depicts.

That intent is stated in every archive's README, because it is the honest description of the
use and the one that matters most if anyone asks.

## The problem

Downstream repos inline their fixtures today. `flighthq-ports/awayjs-examples` carries ~65 MB
of assets in-tree (140 JPGs, 31 PNGs, 4 AWD, 4 OBJ, MD5/MD2/3DS meshes) purely so its
examples can run. Every consumer wanting the same coverage pays that cost again, and nobody
can tell from the tree where any of it came from or what it's licensed under.

## Governing principle: report the source's assertion, remove cheaply

We do not pre-emptively exclude files on a guess about rights we can't resolve, and we do not
second-guess an upstream's stated license. We record **what the source asserted**, we capture
the evidence of that assertion, and we make any individual file removable in one edit.

The distinction that makes this work at scale: a manifest entry is not a claim about the
world, it is a claim about a document. Not *"this file is MIT"* — which we cannot verify for
409 files and would be overclaiming — but *"retrieved from `rive-app/rive-runtime` at commit
`abc123`, whose LICENSE stated MIT."* That is mechanically derivable, automatically true, and
stays true even if upstream's assertion turns out to have been wrong.

This is the **declared vs. concluded** split that SPDX and every package ecosystem already
use, so the field names are conventional and existing tooling understands them:

- **`license.declared`** — always present, derived mechanically from the source. What they
  said.
- **`license.concluded`** — optional and rare. Present only where a human actually analysed
  the file. Its absence is not a gap to be flagged; it is the honest default.

### Not all declarations are equally specific

A repository-root LICENSE is a declaration about *the repository*, not necessarily about
every file in it. `rive-app/rive-runtime`'s MIT is plainly aimed at the C++ renderer; reading
it as a statement about a `.riv` binary in a test directory is a small inferential step we
are taking, not something upstream said. By contrast `examples/spineboy/license.txt` sits
beside the assets and speaks about them explicitly.

`license.declaredScope` records which kind we had, resolved by taking the most specific
declaration found:

| Scope | Source of the declaration |
| --- | --- |
| `file-adjacent` | SPDX header in the file, or a LICENSE beside it (spineboy) |
| `directory` | A LICENSE governing the containing directory (`renderer/LICENSE`) |
| `repository-root` | Only the repo's top-level LICENSE (most `.riv` assets) |

This is mechanically derivable, costs nothing to record, and lets consumers weigh a
declaration rather than treating all of them as equivalent.

It rejects two easier designs:

- **Include everything with no metadata** — leaves consumers unable to make their own
  decisions and leaves us unable to act on a request.
- **Blanket exclusion rules** — "drop anything that looks like third-party IP" must be
  maintained by hand against 400+ files, degrades silently as upstreams change, and
  substitutes our guess for the record. A fetch script has the same flaw: policy encoded in
  code nobody re-reads.

### Capture the assertion, don't just cite it

For every source we snapshot its LICENSE file **as it existed at the pinned commit** into
`LICENSES/`. If upstream relicenses, restructures, or disappears, our account of what they
said remains verifiable. This is the difference between *saying* we trusted the source and
being able to show exactly what we trusted.

### Honesty includes "we don't know"

Some files have no resolvable license — a `.swf` recovered from a defunct site has unknown
author and unknown terms. The entry says exactly that: where it was found, when, and
`declared: UNKNOWN`. A labelled unknown is more useful to a consumer than an omission.

These entries are also structurally distinct in a way worth marking: they have **no upstream
asserting anything and nobody to notify** if a dispute arrives (see below). The `source.kind`
field distinguishes `upstream` (a project making a declaration) from `recovered` (found, with
no declaration available), because the invalidation loop only has an upstream leg for the
former.

### Authorship and subject matter are separate facts

If you model Mickey Mouse you own the model and not the character, and where one ends and the
other begins is genuinely blurry. The manifest doesn't resolve that blur — where anyone
happens to notice, it records both facts side by side as optional annotation, not as a
liability judgment we are obliged to make for every file:

```yaml
- path: rivs/adventuretime_marceline-pb.riv
  source:
    kind: upstream
    repo: rive-app/rive-runtime
    commit: <sha>
    path: renderer/webgpu_player/rivs/adventuretime_marceline-pb.riv
    retrieved: 2026-08-05
  sha256: <sha256>
  license:
    declared: MIT                              # what the source said
    declaredBy: LICENSES/rive-runtime@<sha>.txt  # snapshot of them saying it
    covers: "Rive's authorship of the .riv (rig, curves, state machine)"
  depicts:                                     # optional annotation
    subject: "Marceline and Princess Bubblegum, Adventure Time"
    rightsHolder: "Cartoon Network"
    status: unresolved
  commercialUse: unknown
```

## Invalidation

If a file is challenged, the challenge is evidence that an upstream declaration was wrong —
so it flows back to the source rather than stopping with us.

- The entry gets a `dispute:` block recording who, when, and the outcome.
- **We notify the upstream.** They are distributing the same file under the same declaration
  and have both the relationship and the standing to resolve it. Routing it to them is what
  the declared-license model is for. The dispute template carries the upstream contact and a
  dispute cannot be closed without the notification link — a promise this easy to skip has to
  be enforced by the process rather than by intent.
- **The pass is batch-aware.** Because every entry records `source.repo` and `commit`, one
  challenge surfaces every other file from that origin for review. A complaint about one Rive
  file is information about the other 408, and the manifest can answer that query directly.
- Removal, if warranted, is the one-line `exclude:` below.

## Per-file exclusion

Better than a fetch script precisely because it's declarative and verified rather than
maintained by hand.

- **No asset is ever a loose blob.** Every published byte resolves through a manifest entry.
  There is no path by which a file reaches an archive without metadata.
- **Removal is one line.** Set `exclude:` on the entry with a reason, re-tag, done.
  ```yaml
  exclude:
    reason: "Removal requested by rights holder, 2026-09-01"
    ref: "https://github.com/.../issues/12"
  ```
- **CI enforces it.** The pack step fails if an excluded entry's SHA-256 appears anywhere in
  a built archive. The guarantee is mechanical, not procedural — it can't rot.
- **Past releases are re-issuable.** Any prior tag can be rebuilt against the current
  exclusion list, so "v1.2.0 but without that file" ships as v1.2.1 within minutes.
- **Exclusions are public.** They stay in the manifest with their reason rather than being
  deleted, so the record of what was removed and why is auditable.

## Build variants from one manifest

The same manifest produces more than one archive, so consumers choose their own risk posture
without us choosing for them:

- **`<pack>-full`** — everything not explicitly excluded. The default for flight sdk's own
  compatibility suite.
- **`<pack>-permissive`** — filtered to entries whose *declared* license is a recognised
  permissive SPDX id, with no unresolved `depicts` and `commercialUse: true`.

Both derive from identical metadata, so there is no second policy to maintain and no way for
the two to drift.

The name is deliberately descriptive of the filter, not of a conclusion. An earlier draft
called it `-clear`, which implies a clearance we have no basis to grant — if a consumer ships
commercially on the strength of that name and one declaration was wrong, the name itself was
a representation. `-permissive` says what the filter did: selected on declared licenses. The
archive README states plainly that this is filtering on recorded metadata, not legal
clearance.

## Sources and what we know about them

- **Spine `examples/spineboy/`** — `examples/spineboy/license.txt` grants redistribution
  directly: *"The images in this project may be redistributed as long as they are accompanied
  by this license file. The images may not be used for commercial use of any kind. The
  project file is released into the public domain."* Note the split: the `.spine` project
  file is public domain, the `images/` are restricted. Ships with `commercialUse: false`,
  which keeps it out of `-permissive`. The same per-example `license.txt` pattern runs throughout
  `spine-runtimes/examples/`, so `raptor`, `goblins`, `dragon`, `owl` and the rest each get
  evaluated the same way.
- **Rive `.riv`** — MIT via root `LICENSE` and `renderer/LICENSE`. A handful
  (`adventuretime_marceline-pb`, `spotify_kids_demo`, `spotify_kids_app_icon`) additionally
  carry a `depicts` block as above.
- **Ruffle SWF tests** — dual Apache-2.0/MIT.
- **`from_avmplus/`** (MPL-2.0), **`from_shumway/`** (Apache-2.0) — file-level permissive,
  satisfied by carrying the license text.
- **`from_gnash/`** — GPL-3.0 by origin, and this one has an actual mechanical condition
  rather than a risk question. For generated SWFs (`misc-ming.all`, `misc-swfmill.all`,
  `misc-mtasc.all`, `misc-swfc.all`) the corresponding source is the generator script in the
  Gnash repo; the manifest entry carries a `sourceCode:` pointer to it.
- **Recovered SWFs** — `source.kind: recovered`, `license.declared: UNKNOWN`, with the URL and
  retrieval date recorded. No upstream declaration to snapshot and no upstream to notify.

### Pin the format version, not just the commit

A commit SHA pins *which file we took*; it does not pin *what format that file is in*. If
upstream re-exports its `.riv` assets to a newer runtime format, the same logical fixture
starts exercising a different code path than the one we think we're testing, and nothing in
the manifest would show it. Each entry therefore records the container format version
(`.riv` runtime version, Spine skeleton version, SWF version byte) parsed from the file
itself at ingest. Drift detection compares it alongside the SHA-256.

## Don't fork; extract, pin, vendor

The instinct behind mirroring is right — upstreams get taken down, renamed, restructured. But
a fork is the wrong instrument.

**Ratio.** The 409 `.riv` files we want total a few MB; `rive-app/rive-runtime` is a full C++
renderer. Forking it means appearing to maintain a graphics runtime we won't maintain.

**Appearances.** Forking `EsotericSoftware/spine-runtimes` puts the Spine runtime code under
our org, and its
[`LICENSE`](https://github.com/EsotericSoftware/spine-runtimes/blob/4.2/LICENSE) permits
derivative works only where "each user of the Products must obtain their own Spine Editor
license." That reads as us distributing a Spine runtime and attaching that obligation
downstream. We want `examples/spineboy/`, not the runtime.

**A fork can't be curated.** It republishes wholesale, which is exactly the per-file control
this policy is built on.

Extract the paths we need, pin by upstream commit SHA, verify by SHA-256, vendor the bytes.
Pinning gives reproducibility; vendoring gives survival — pinning alone doesn't survive a repo
deletion, which is the failure mode mirroring was reaching for.

## Recommendation for SWF: generate as well as gather

Recovered SWFs are worth keeping and labelling honestly. They're also worth *supplementing*
with fixtures we compile ourselves in CI — `open-flash/flex-sdk` mirrors the Apache Flex SDK
under Apache-2.0, and Haxe/OpenFL is another route. Self-built fixtures give unambiguous
provenance and coverage targeted at the exact tag or opcode under test, reviewable as source
rather than an opaque blob. They're the backbone; the gathered corpus covers the real-world
edge cases synthetic fixtures won't reach.

## Oracles inherit their fixture's record

Golden renders, per-frame PNGs, and expected parse trees are derivative of the fixtures that
produced them. A render of spineboy inherits spineboy's non-commercial term; a render of a
`depicts`-flagged `.riv` inherits that flag. Goldens copy the manifest fields of their input,
not of their generator, and an excluded fixture's goldens are excluded with it.

## Packaging

### Many small packs, not one archive

Split by corpus **and** by kind, so fixtures and goldens are never in the same archive:

```
spine-fixtures          rive-fixtures          swf-ruffle-fixtures
                        rive-goldens           swf-generated-fixtures
```

Each versioned independently, with an `index.json` on the release listing every pack and its
digest so consumers resolve programmatically rather than hardcoding filenames.

**Follow upstream's coupling, not our taxonomy.** The split above is a default, not a rule to
enforce against the sources. Where an upstream ships a fixture and its expected output
together — Unicode's `BidiTest.txt` carries input and required output on one line, Ruffle
stores `test.swf` beside `output.txt`, glTF-Asset-Generator pairs assets with a
results manifest — they belong in **one** pack. Separating them would mean dismantling a
directory that arrives coupled and inventing a join key to put it back. Goldens we generate
ourselves are the case that genuinely splits, because their size and churn differ, not
because they are a different kind of thing.

The decisive reason is **cache invalidation downstream**, not the 2 GB per-asset cap.
Consumers cache by archive digest; in a monolith, changing one SWF fixture invalidates the
whole cache and every CI job re-downloads everything, goldens included. Split packs make that
cost proportional to what actually changed.

The rest points the same way: a SWF parser test shouldn't pull Rive goldens; the spineboy pack
changes almost never while the Ruffle corpus changes often; and a disputed file means
re-cutting one pack rather than the world. Goldens in particular are per-frame PNGs across
hundreds of fixtures and will dominate total bytes while fixtures stay in the kilobytes.

### Licenses: shared within the archive, with one exception

A single `LICENSES/` directory per archive, one file per distinct source declaration named
`<source>@<sha>.txt`, referenced from each manifest entry by path. Duplicating MIT beside 409
files is ~400 KB of identical text, makes diffs unreadable, and invites someone editing one
copy into drift. Dedup is largely self-resolving since each source's copyright line differs,
making them genuinely distinct declarations.

*Shared within the archive*, never a URL to go fetch — every archive stays self-contained.

**The exception is any `file-adjacent` declaration**, spineboy being the live case. Its terms
say the images may be redistributed *"as long as they are accompanied by this license file"*,
and the safe reading of "accompanied by" is adjacent to the images, not merely present
somewhere in the tarball. Those licenses are preserved in place (`spineboy/license.txt`) *and*
referenced from the manifest. `declaredScope: file-adjacent` identifies them automatically, so
this needs no separate list to maintain.

### Every archive also carries

- `manifest.json` — the full per-file record.
- `NOTICE.md` — generated human-readable attribution rollup, so the picture is legible without
  parsing JSON.
- `README.md` — the compatibility-testing intent, the non-commercial notice where it applies,
  and how to request removal.

### Build mechanics

- **Deterministic tar** — sorted entries, `mtime=0`, uid/gid 0, fixed permissions — so a
  rebuild at the same manifest is byte-identical.
- `.tar.gz` for universal tooling, with `.zip` emitted alongside if Haxe/OpenFL consumers
  prefer it. Goldens are PNGs and already compressed, so the codec matters far less than the
  split; don't spend effort optimising it.
- `SHA256SUMS` attached alongside, plus build provenance attestation.
- **No Git LFS.** Release assets don't bloat clones or consume an LFS bandwidth quota.

## Removal requests

The README and repo both carry a plain statement: we've recorded everything we know about
where each file came from, some licenses are unknown, and if you hold rights in something
here and want it gone, open an issue or email and we'll cut a release without it. A visible,
low-friction path is what makes the posture legible as good faith rather than an assertion
about it.

## Drift detection

A scheduled workflow re-resolves every pinned upstream URL and compares SHA-256. On mismatch
or 404 it opens an issue — early warning for the takedown scenario, at the cost of one cron
job rather than an org full of forks.
