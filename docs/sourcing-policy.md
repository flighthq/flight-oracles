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

## Governing principle: record honestly, remove cheaply

We do not pre-emptively exclude files on a guess about rights we can't resolve. We record
what we actually know, we mark clearly what we *don't* know, and we make any individual file
removable from the build in one edit.

This is a deliberate rejection of two easier designs:

- **Blanket include-everything with no metadata** — leaves consumers unable to make their own
  decisions, and leaves us unable to act quickly on a request.
- **Blanket exclusion rules** — a rule like "drop anything that looks like third-party IP"
  has to be maintained by hand against 400+ files, degrades silently as upstreams change, and
  substitutes our guess for the truth. A fetch script has the same flaw: it encodes a policy
  in code that nobody re-reads.

Per-file honest metadata plus per-file exclusion is more work up front and far less work to
keep correct.

### Honesty includes "we don't know"

Some files have no resolvable license. A `.swf` recovered from a defunct site has an unknown
author and unknown terms. The correct manifest entry says exactly that — where it was found,
when, and that the license is unknown — rather than omitting the file to avoid the awkward
field. An `UNKNOWN` we've labelled is more useful to a downstream consumer than a gap.

### Authorship and subject matter are separate facts

If you model Mickey Mouse, you own the model and not the character, and where one ends and
the other begins is genuinely blurry. The manifest doesn't try to resolve that blur — it
records both facts side by side:

```yaml
- path: rivs/adventuretime_marceline-pb.riv
  source:
    repo: rive-app/rive-runtime
    commit: <sha>
    path: renderer/webgpu_player/rivs/adventuretime_marceline-pb.riv
    retrieved: 2026-08-05
  sha256: <sha256>
  license:
    found: MIT
    file: LICENSES/rive-runtime-MIT.txt
    covers: "Rive's authorship of the .riv (rig, curves, state machine)"
  depicts:
    subject: "Marceline and Princess Bubblegum, Adventure Time"
    rightsHolder: "Cartoon Network"
    status: unresolved
    note: "Upstream's MIT grant covers their authorship; rights in the depicted
           characters are separate and not established here."
  commercialUse: unknown
```

Three honest fields — `license.found`, `license.covers`, `depicts` — say more than any
include/exclude decision could, and they let a consumer with stricter requirements filter on
them.

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
- **`<pack>-clear`** — filtered to entries with a known permissive license, no unresolved
  `depicts`, and `commercialUse: true`. For consumers who need a clean provenance story.

Both derive from identical metadata, so there is no second policy to maintain and no way for
the two to drift.

## Sources and what we know about them

- **Spine `examples/spineboy/`** — `examples/spineboy/license.txt` grants redistribution
  directly: *"The images in this project may be redistributed as long as they are accompanied
  by this license file. The images may not be used for commercial use of any kind. The
  project file is released into the public domain."* Note the split: the `.spine` project
  file is public domain, the `images/` are restricted. Ships with `commercialUse: false`,
  which keeps it out of `-clear`. The same per-example `license.txt` pattern runs throughout
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
- **Recovered SWFs** — `license.found: UNKNOWN`, with the URL and retrieval date recorded.

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

- **One archive per pack** — keeps downloads scoped and clear of the 2 GB per-file cap on
  GitHub release assets.
- Each archive carries `manifest.json`, a `LICENSES/` directory of verbatim upstream texts, a
  generated human-readable `NOTICE.md`, and a README stating the compatibility-testing intent
  and how to request removal.
- **Deterministic tar** — sorted entries, `mtime=0`, uid/gid 0, fixed permissions — so a
  rebuild at the same manifest is byte-identical.
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
