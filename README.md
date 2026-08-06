# flight-oracles

Sources, verifies, and publishes fixture data for downstream flight sdk projects as
compressed archives attached to GitHub releases.

**This is a build step, not a distribution channel.** The archives are build artifacts that
flight's CI fetches — the role a lockfile or container layer plays. There is no
browse-and-download site, nothing is promoted as downloadable content, and no asset is
offered stripped of its terms. Assets reach the public through flight itself; this repository
is the plumbing that gets them there.

Downstream repos currently inline their fixtures — `flighthq-ports/awayjs-examples` carries
~65 MB in-tree — so every consumer pays that cost again and nobody can tell where any of it
came from. This repository sources fixtures from their real upstreams, records provenance
per file, carries each licence with the bytes it covers, and ships versioned archives a test
suite can pin.

**Oracles** (expected-output data for comparison) are a later phase. Today this is fixtures.

## Current packs

| Pack | Files | Size | Contents |
| --- | ---: | ---: | --- |
| `swf-ruffle-fixtures` | 16,639 | 83.2 MB | SWF v4–v50 **+ 4,291 expected trace outputs** |
| `spine-fixtures` | 1,126 | 57.4 MB | Spine 4.2 exports, 19 examples + spine-unity |
| `gltf-khronos-textures` | 767 | 500.7 MB | Raster textures — merges with `gltf-khronos-fixtures` |
| `malformed-fixtures` | 661 | 7.7 MB | **Derived** — truncation, header damage, bit flips |
| `spine-fixtures-38` | 510 | 28.1 MB | Spine 3.8 — prior format version, rejection testing |
| `gltf-generated-fixtures` | 535 | 53.9 MB | **Conformance** — positive/negative split is the expectation |
| `gltf-khronos-fixtures` | 476 | 293.5 MB | 148 Khronos glTF 2.0 models — 29 KHR/EXT extensions |
| `rive-fixtures-unit` | 388 | 148.3 MB | Rive unit-test corpus — all 12 feature areas |
| `tilemap-fixtures` | 475 | 21.6 MB | Tiled TMX/TSX/TMJ/TSJ — map versions 1.0 through 1.11 |
| `dragonbones-fixtures` | 145 | 14.2 MB | DragonBones skeletons, JSON + binary `.dbbin` |
| `gltf-khronos-binary` | 118 | 432.7 MB | GLB: self-contained models, textures embedded |
| `texture-container-fixtures` | 98 | 36.3 MB | KTX2, KTX1, Basis Universal, DDS |
| `lottie-fixtures` | 79 | 15.3 MB | Lottie animations — 14 versions, v3.1.6–v5.12.2 |
| `image-fixtures` | 60 | 0.1 MB | PngSuite — canonical PNG conformance corpus |
| `rive-fixtures` | 27 | 1.1 MB | Rive WebGPU player demo corpus |
| `mesh-legacy-fixtures` | 195 | 64.0 MB | OBJ/MTL, AWD2, MD5 mesh+anim, MD2, 3DS |
| `atf-fixtures` | 14 | 8.1 MB | Adobe Texture Format — undeclared, build input only |
| `spritesheet-fixtures` | 280 | 21.4 MB | libgdx `.atlas` texture atlas descriptors |
| `bitmapfont-fixtures` | 252 | 21.7 MB | AngelCode BMFont `.fnt` descriptors |
| `text-conformance-fixtures` | 8 | 19.0 MB | **Oracles** — 614,914 Unicode conformance cases |
| `particle-fixtures` | 279 | 19.7 MB | libgdx `.p` particle effect configs |
| `cocos2dx-textures` | 987 | 34.4 MB | Textures for the Cocos descriptors — merge group `cocos2dx` |
| `interchange-fixtures` | 323 | 69.2 MB | **Not yet parsed** — Collada, FBX, PLY, STL, BVH, IQM, X3D +13 |
| `effekseer-fixtures` | 80 | 11.1 MB | Effekseer particles — project plus two runtime generations |
| `ldtk-fixtures` | 69 | 42.9 MB | LDtk 2D levels — 22 format versions, v0.6.0–v1.5.3 |
| `unity-native-fixtures` | 14 | 3.0 MB | **Unity's own YAML** — 25 ParticleSystem components |

26 packs, 24,605 files. Three packs carry expectations as well as inputs:
`text-conformance-fixtures` (614,914 Unicode cases), `swf-ruffle-fixtures` (4,291 trace
outputs paired in place) and `gltf-generated-fixtures` (positive/negative conformance split).

**Git LFS is resolved, not stored.** `raw.githubusercontent` serves LFS *pointers* rather
than objects, and a 130-byte text stub where a texture belongs passes every other check —
it hashes consistently and only a decoder would notice. Pointers are detected and resolved
through the LFS batch API, with the object verified against the `oid` it claims.

**Merge groups.** `gltf-khronos-fixtures`+`gltf-khronos-textures`, and the three Cocos
descriptor packs + `cocos2dx-textures`, must each be extracted into the **same directory** — glTF references its
buffers and images by relative URI, so splitting them for size only works if they are
reunited on disk. `verify` checks that every external URI in the group resolves. For
self-contained textured models, use `gltf-khronos-binary` instead: one file per model,
nothing to resolve.

Three variants build from each pack. **`-full`** is the build input: everything usable for
testing, including material whose terms permit that use and nothing further.
**`-demo`** may be shown publicly: excludes testing-only and unknown-scope material but keeps
non-commercial assets an author intends to be displayed. **`-permissive`** may travel into
commercial work — declared-permissive licence, no unresolved third-party subject matter,
commercial use permitted.

`.zip` is emitted alongside `.tar.gz` only for packs under 150 MB; above that the payloads
are already-compressed images and the zip is a near-identical duplicate. `spine-fixtures` produces no `-permissive` archive — every Spine example is
declared non-commercial.

Two models are **not vendored at all**, because their declarations explicitly forbid
redistribution: Spine's `dragon` (Thiago Brayner) and `hero` (XDTech), both "may not be
redistributed for any reason". Each stays in its spec with the clause quoted, so the record
of having checked survives.

Licences are **layered**. `license.declared` is the grant relied on; `license.underlying`
records the instrument the material carried before its publisher released it, attributed in
`NOTICE.md` with its text shipped in `LICENSES/`. Four glTF models use this: Khronos admits
"semi-restrictive" assets "provided arrangements are made" and requires every asset to permit
public use, so the arrangement is the operative grant and Adobe Stock / CRYENGINE / Poser /
3DRT are attributed beneath it.

## Usage

```bash
export PYTHONPATH=tools

python3 -m oracles ingest [pack…]           # fetch at pinned commits, vendor, write locks
python3 -m oracles ingest <pack> --update   # re-resolve refs and adopt newer upstream
python3 -m oracles verify [pack…]           # re-hash vendored bytes against the locks
python3 -m oracles pack --version v0.1.0    # build dist/ archives + index.json + SHA256SUMS
python3 -m oracles drift [pack…]            # re-resolve pins, report divergence
python3 -m oracles show [pack…]             # summarise what is locked

python3 -m unittest discover -s tools/tests
```

Stdlib only — no dependencies to install, in CI or anywhere else.

## How it works

**`sources/*.toml`** are hand-authored and record *intent*: which upstream, which ref, which
paths, and what that upstream declared about the licence. The `[[source]]` block is the unit
of declaration — where one repo declares different things for different subtrees, that is
several blocks.

**`locks/*.lock.json`** are generated and record *facts*: resolved commit, per-file SHA-256,
size, container format version, and the declaration that covered each file. Hand-maintaining
5,000 file entries is not something anyone will keep doing correctly, so the split matters.

The spec carries a ref, the lock carries the commit. A plain `ingest` reuses the locked
commit and is reproducible; `--update` moves the pin deliberately.

**`licenses/`** holds each upstream's licence text captured *at the pinned commit*. If an
upstream relicenses or disappears, what we relied on stays verifiable.

**`vendor/`** holds the bytes. Currently gitignored — see the note in `.gitignore`, which is
a repository-weight decision rather than a technical one.

Archives are byte-reproducible: sorted entries, zeroed mtimes, fixed modes and ownership.
Rebuilding the same lock produces the same digest.

## Provenance model

We report what each source **declared**; we do not adjudicate it. A manifest entry is a claim
about a document — *"rive-runtime's LICENSE said MIT at commit abc123"* — not a claim about
the world. That is mechanically derivable for thousands of files and stays true even if the
declaration turns out to have been wrong.

`declaredScope` records how specific the declaration was (`file-adjacent`, `directory`,
`repository-root`), because a repository-root LICENSE is a statement about a repository, not
about every binary inside it.

Nothing is excluded on a guess. Files with no resolvable licence are recorded as
`declared: UNKNOWN` with where and when they were found, because a labelled unknown is more
useful than an omission. Third-party subject matter gets a `depicts` annotation naming the
subject and rights holder alongside the declaration — authorship and subject matter are
separate facts, and the manifest records both rather than resolving the blur.

**One thing is excluded, and not as a judgement call:** where a declaration *explicitly
forbids* redistribution, honouring it and republishing are incompatible. Two Spine examples
are declared this way by third-party authors — `dragon` (Thiago Brayner) and `hero` (XDTech),
both "may not be redistributed for any reason". They stay in `sources/spine-fixtures.toml`
with the clause quoted, so the record of having checked is durable, and the pipeline refuses
to vendor or pack them.

File-adjacent licences travel beside their assets as well as in `LICENSES/`, because
spineboy's terms permit redistribution "as long as they are accompanied by this license
file" and the safe reading of *accompanied* is adjacent, not merely present.

See [`docs/sourcing-policy.md`](docs/sourcing-policy.md) for the full reasoning, and
[`docs/fixture-coverage.md`](docs/fixture-coverage.md) for the exhaustive fixture target set
derived from flight's decode surface.

## Removal requests

Every file records where it came from and the licence found there, and some are marked
unknown because they are. If you hold rights in something here and want it removed, open an
issue. Removal is a one-line `exclude:` in the lock and a re-cut release; the pack step fails
the build if an excluded file's bytes reach an archive, so the guarantee is mechanical rather
than procedural. We also notify the upstream we obtained it from.

## Licence

Pipeline code: MIT. **The fixture archives are not MIT** — each carries its own upstream
declarations, and several are non-commercial only. See each archive's `NOTICE.md`.
