# Fixture coverage

An exhaustive fixture target set, derived from what `flighthq/flight` actually parses rather
than from what is convenient to find.

Method: flight has 143 packages. The `*-formats` packages, plus `swf`, `abc`, `image-codec`,
`font`, `audio`, `video`, `texture-formats`, `compression` and `xml`, are the decode surface.
Every format one of them claims is a fixture obligation. Sources below were checked for
licence on 2026-08-05.

## Why this matters more than it looks

`packages/scene2d-formats/src/riveDocument.test.ts` opens with an unusually honest comment:

> The fixtures here are bytes this suite writes, which on its own would only show the decoder
> agrees with itself. … And the grammar itself was verified against 64 real editor-authored
> `.riv` files, which decoded completely (82,543 core objects); the empty-table and
> built-in-width cases below exist because that corpus disproved an earlier reading in which
> the file's own table was the only source of property widths.

A real corpus already did the decisive work — it *disproved a wrong reading of the format* —
and then vanished. What survives is a code comment. The same pattern appears in
`packages/swf/src/swfDocument.test.ts` ("the corpus sweep runs the same property over real
files") and in `spineBinaryParse.ts`, which claims only Spine 4.x because "it is what the
layout was verified against."

That is precisely the gap this repository closes: making those corpora durable, versioned,
and citable, so validation is a CI job rather than a one-time manual exercise whose result
survives only as prose.

## Fixtures and oracles belong in one repository

Not as a filing preference — the coupling is in the upstream sources themselves:

- Unicode's `BidiTest.txt` puts the input and its required output **on the same line**. There
  is no fixture to separate from the oracle; they are the same bytes.
- Khronos `glTF-Asset-Generator` ships assets beside a manifest describing each case's
  expected result, in one tree.
- Ruffle stores `test.swf` and its `output.txt` in the same directory.
- PngSuite's corrupt files are only meaningful alongside their documented expected behaviour.

Splitting these across repositories would mean tearing apart directories that arrive coupled
and inventing a join key to reassemble them. The provenance chain argues the same way: an
oracle inherits its fixture's declaration, so the two must move and version together or the
inheritance silently breaks.

**Pack boundaries should follow how upstream ships it, not a fixture/oracle taxonomy we
impose.** Where upstream couples them, one pack. Where we later *generate* goldens ourselves
— rendered output — that becomes a separate pack, because it has different size, churn, and
regeneration characteristics, not because it is a different category of thing.

(`flighthq/flight-conformance` exists as an empty stub. If it is meant to hold the conformance
*runner* rather than the data, these stay complementary; worth settling before either grows.)

## Consumption: the flight-assets shape does not fit archives

`flighthq/flight-assets` uses a flat `assets.manifest.json` of `{url, path}` entries — 46 of
them, one per file, each pointing at an individual release asset. `scripts/warm-assets.ts`
walks consumers holding such a manifest and calls `downloadConsumerAssets` into
`.cache/assets/<consumer>`.

That shape is right for loose media that is never archived, and wrong here.
`swf-ruffle-fixtures` alone is 4,810 files: it would need 4,810 manifest entries, or a single
entry pointing at a tarball the downloader has no idea how to unpack. It also carries no
digests, so nothing is verified on arrival.

A fixture consumer should reference a **pack and version**, not files:

```jsonc
// fixtures.manifest.json
{
  "release": "v0.3.0",
  "packs": [
    { "pack": "gltf-khronos-fixtures", "variant": "permissive" },
    { "pack": "swf-ruffle-fixtures",   "variant": "full" }
  ]
}
```

The resolver fetches that release's `index.json`, matches each pack and variant to its
artifact, verifies the recorded SHA-256, and extracts to `.cache/fixtures/<pack>/`. One entry
per corpus instead of thousands, integrity checked, and the version pinned by a single string.

The payoff beyond ergonomics: the extracted tree contains the archive's own `manifest.json`,
so a test can query provenance locally — skip entries carrying `depicts`, assert a decoder
handles every `format.version` present, or exclude non-commercial sources from a published
demo — without any of that knowledge being hardcoded in flight.

This can live beside the flight-assets pattern rather than replacing it; the two solve
different problems and both can be warmed by the same top-level script.

## Coverage table

Status: ✅ shipped · ◐ declared, not ingested · ○ not started

| Pack | Formats | flight packages | Upstream | Declared |
|---|---|---|---|---|
| ✅ `spine-fixtures` | Spine JSON/skel/atlas | `skeleton2d-formats` | EsotericSoftware/spine-runtimes | per-example, non-commercial |
| ✅ `swf-ruffle-fixtures` | SWF v4–v50 | `swf`, `abc` | ruffle-rs/ruffle | Apache-2.0/MIT + GPL/MPL subtrees |
| ✅ `rive-fixtures` | .riv | `scene2d-formats` | rive-app/rive-runtime | MIT (repo-root) |
| ◐ `rive-fixtures-unit` | .riv (380 files) | `scene2d-formats` | rive-app/rive-runtime | MIT (repo-root) |
| ✅ `gltf-khronos-fixtures` | glTF, 28 KHR/EXT ext. | `scene3d-formats` | KhronosGroup/glTF-Sample-Assets | **per-model LICENSE.md** |
| ◐ `gltf-khronos-textures` | raster textures | demo/render | KhronosGroup/glTF-Sample-Assets | per-model |
| ◐ `gltf-khronos-binary` | GLB container | `scene3d-formats` | KhronosGroup/glTF-Sample-Assets | per-model |
| ○ `gltf-generated-fixtures` | glTF conformance matrix | `scene3d-formats` | KhronosGroup/glTF-Asset-Generator | MIT |
| ○ `lottie-fixtures` | Lottie JSON/.lottie | `scene2d-formats` | LottieFiles/lottie-docs, airbnb/lottie-web | CC-BY-4.0 / MIT |
| ○ `dragonbones-fixtures` | DragonBones JSON | `skeleton2d-formats` | DragonBones/DragonBonesJS | MIT |
| ○ `mesh-legacy-fixtures` | OBJ, MTL, MD2, MD5, 3DS, AWD2 | `scene3d-formats` | flighthq-ports/awayjs-examples (AWD2) + per-format | MIT |
| ○ `texture-container-fixtures` | KTX2, Basis, DDS, ATF | `texture-formats` | KTX-Software, basis_universal | NOASSERTION / Apache-2.0 |
| ○ `draco-fixtures` | Draco-compressed meshes | `scene3d-formats` | google/draco | Apache-2.0 |
| ○ `font-signature-fixtures` | TTF/OTF/WOFF/WOFF2/TTC signatures | `font` | **synthesized** — see below | n/a |
| ○ `text-conformance-fixtures` | UAX #9/#14/#29 | `textbidi`, `textsegment` | Unicode UCD | Unicode-3.0 |
| ○ `text-rendering-fixtures` | shaping cases | `textshaper`, `textlayout` | unicode-org/text-rendering-tests | NOASSERTION |
| ○ `image-fixtures` | PNG, JPEG, GIF, WebP, AVIF, BMP, TIFF, ICO | `image-codec` | PngSuite, libwebp, av1-avif | varies |
| ○ `spritesheet-fixtures` | TexturePacker, Starling, cocos plist, libgdx, Aseprite | `spritesheet-formats`, `textureatlas-formats` | per-tool samples | varies |
| ○ `tilemap-fixtures` | Tiled TMX/TMJ | `tilemap-formats` | mapeditor/tiled | NOASSERTION |
| ○ `particle-fixtures` | libgdx, PEX, pixi, Unity, ParticleDesigner, Spine | `particles-formats` | per-tool samples | varies |
| ○ `bitmapfont-fixtures` | BMFont .fnt/XML/JSON | `bitmapfont-formats` | AngelCode BMFont | varies |
| ○ `svg-path-fixtures` | SVG path `d` grammar | `path-formats` | W3C SVG test suite | W3C |
| ○ `xml-fixtures` | XML incl. malformed | `xml` | W3C XML conformance suite | W3C |
| ○ `audio-fixtures` | WAV, MP3, AAC, FLAC, Ogg, WebM, MP4, SWF-ADPCM | `audio` | per-codec samples | varies |
| ○ `video-fixtures` | MP4, WebM, Ogg, MOV, 3GPP, MKV | `video` | per-codec samples | varies |
| ○ `swf-generated-fixtures` | targeted SWF tags | `swf` | self-compiled (Apache Flex SDK) | Apache-2.0 |
| ○ `malformed-fixtures` | truncated/corrupt, all formats | all decoders | derived + PngSuite | derived |

## Fonts need almost nothing — flight does not implement shaping

Worth stating explicitly, because "font formats" reads like a large sourcing job and is not.

`packages/font/src/fontFormat.ts` is the whole font-file obligation, and it is a **four-byte
magic-number sniff**: `00 01 00 00` → truetype, `OTTO` → opentype, `wOFF` → woff,
`wOF2` → woff2, `ttcf` → collection, `true` → truetype. Its sibling
`inferFontFormatFromUrl` is pure string handling on the extension. Neither reads a glyph.

So the fixtures are six files of four bytes each, plus a couple of near-miss cases to prove
the sniffer rejects rather than guesses. Those are **synthesized, not sourced** — no upstream
corpus, no licence question, no megabytes. `google/fonts` at 3.2 GB would buy nothing.

The reason is architectural: `textshaper-canvas` delegates glyph shaping to the platform
(`canvasTextShaper.ts` over canvas text measurement). What flight implements itself is
*itemization, clustering, bidi, and segmentation* — `textShaperItemize.ts`,
`textShaperCluster.ts`, `textbidi`, `textsegment`. Those are exercised by **Unicode character
data, not by font binaries**, which is exactly what `text-conformance-fixtures` supplies.

If a real font is ever needed for an end-to-end path, `flighthq/flight-assets` already ships
several — that is example media, and it is the right home for it.

## Three findings worth acting on

### 1. Several upstream corpora already carry their expected outputs

The oracle phase does not have to start from scratch, and does not have to start with pixels:

- **Unicode UCD conformance files** — `BidiTest.txt`, `BidiCharacterTest.txt`,
  `GraphemeBreakTest.txt`, `WordBreakTest.txt`, `LineBreakTest.txt`, `NormalizationTest.txt`.
  Each line *is* an input paired with its required output. For `textbidi` and `textsegment`
  these are complete oracles, textual, deterministic, and unambiguously licensed.
- **KhronosGroup/glTF-Asset-Generator** (MIT) — procedurally generated conformance assets.
  *Correction to an earlier draft of this document:* its `Manifest.json` lists models and
  camera placement, not per-property expected results. The oracle is coarser and structural
  — the corpus splits into `Output/Positive` (must parse) and `Output/Negative` (must be
  rejected), so the directory a file sits in is the expected outcome. That is still a real
  oracle, just a binary one, and the negative cases are the valuable half: they are the
  malformations a lenient parser accepts and then renders as garbage.
- **unicode-org/text-rendering-tests** — shaping cases with expected output, the standard
  conformance suite for text shapers.
- **PngSuite** — the canonical PNG conformance corpus, including deliberately corrupt files
  with documented expected behaviour.

That makes text and glTF the cheapest places to begin oracles, and both avoid the
golden-render stability problem entirely because their expectations are structural.

### 2. Negative fixtures are a first-class need here, not an afterthought

`swfDocument.test.ts` states the error contract plainly: *"The package's whole error contract
is a null sentinel, so the property that matters is that no input produces an exception."*
That property cannot be established from well-formed files. It needs a corpus of truncated,
mutated, and adversarial inputs across every format — which is why `malformed-fixtures` is
listed as a pack rather than a nice-to-have.

Most of it is derivable rather than sourced: truncate at every tag boundary, flip length
prefixes, nest to absurd depth, declare huge counts against short buffers. Generating these
deterministically from the healthy corpus is cheap, and pairs naturally with the seeded-
mutation approach the SWF suite already uses. Where an upstream provides curated corrupt
files — PngSuite does — take theirs too, since they encode known real-world breakage.

### 3. Version coverage is a gap the current corpora do not close

Several decoders make explicit version claims that need fixtures *outside* the supported
range to test the rejection path:

- `spineBinaryParse.ts` supports only Spine 4.x and rejects 3.8 "rather than guessed, because
  a mismatched layout desynchronizes the stream and yields plausible-looking garbage."
  Our `spine-fixtures` pack is 4.2 only — there is nothing to prove the rejection works.
  `spine-runtimes` keeps `3.8` as a live branch, so this is one more source block.
- SWF: our Ruffle corpus spans v4–v50 already, which is genuinely good coverage.
- glTF 1.0 vs 2.0 — a 1.0 asset should be rejected cleanly.
- Rive: `.riv` format version 7.0 across the whole current corpus. Older-format files would
  need to come from older upstream commits, which the pinning model makes easy — a second
  source block at an earlier commit.

Rejection fixtures are cheap to source and disproportionately valuable, because a decoder
that silently mis-parses an unsupported version is the failure mode with no symptom.

## Suggested sequencing

1. **`gltf-khronos-fixtures`** — largest coverage win per unit of work, and it earns its place
   twice: 148 models against a package implementing 17 extensions, *and* a ready-made source
   of demo and example content. The per-model `LICENSE.md` layout is exactly the
   `declaredScope: file-adjacent` case the pipeline already handles.

   Dual use raises the stakes on the licence metadata, in a good way. Most models are
   CC-BY-4.0 or CC0; CC-BY **requires attribution wherever the work appears**, so a demo
   shipping one owes credit in the running application, not merely in the archive's
   `NOTICE.md`. The per-model declarations make that mechanical: the `-permissive` variant
   separates the no-attribution CC0 models cleanly, and `NOTICE.md` is already generated in a
   form a demo build can consume for its credits screen. Sourcing them here rather than in
   `flight-assets` means demo content inherits the same provenance record as test content.
2. **`text-conformance-fixtures`** — tiny, unambiguous, and delivers working oracles
   immediately for `textbidi`/`textsegment`.
3. **`malformed-fixtures`** — mostly generated, validates the null-sentinel contract across
   every decoder at once.
4. **Spine 3.8 rejection block** — one source block, closes a stated gap.
5. **`lottie-fixtures`**, **`gltf-generated-fixtures`**, then the long tail.

`rive-fixtures-unit` remains a size decision (~139 MB) rather than a work item.

## Sizing note

Several candidate upstreams are large: glTF-Sample-Assets is 1.6 GB, basis_universal 391 MB,
av1-avif 546 MB, google/fonts 3.2 GB. None should be adopted wholesale. The per-source
`include` globs exist for this — select the variants and cases the decoders actually
exercise, and record what was left out.

## Adjacent formats: the forward-looking sweep

Everything above is scoped to what flight already parses. This section is the opposite —
formats it does *not* parse, sourced anyway because the corpus is the slow part of adding
support, not the parser.

Two are ingested, and one source covers most of the rest.

### Ingested

| Pack | Format | Why this one |
| --- | --- | --- |
| `ldtk-fixtures` | LDtk | The living peer of Tiled. Its `tests/oldVersions` holds the **same project saved by fourteen successive releases** — 22 distinct `jsonVersion` values from v0.6.0 to v1.5.3. Format migration is the hard part of supporting an editor format, and this is a migration suite nobody has to construct. |
| `effekseer-fixtures` | Effekseer | The one serious open particle format missing from the six dialects flight already reads. Ships an editor project (`.efkproj`) plus **two generations of runtime binary** (`.efk`, `.efkefc`) — precisely where version handling goes wrong. |
| `interchange-fixtures` | 20 formats | See below. |

### `assimp/assimp` is the find

Its `test/models` tree is the closest thing the ecosystem has to a cross-format conformance
corpus: 55 format directories, 933 files, BSD-3-Clause, maintained as regression material by
a project whose entire job is reading them. Sourcing from an importer's own test suite means
the files were chosen because they *break* importers.

Twenty formats taken, aligned by domain:

- **Scene graph** — Collada (glTF's predecessor, still the default export from most DCC
  tools), FBX (Autodesk, ubiquitous, binary), X3D and WRL, DirectX `.x`
- **Mesh** — PLY, STL, AMF, M3D, 3DS, LWO, ASE, AC, NFF, COB, OBJ
- **Bone** — **BVH** (Biovision motion capture: plain text, and the universal interchange for
  skeletal animation), **IQM** (Inter-Quake Model, open skeletal mesh), LWS, MD2
- **Negative** — `invalid/`, assimp's own deliberately broken files. Authored invalidity to
  sit beside the mechanical mutations in `malformed-fixtures`.

Skipped: glTF/glTF2 (Khronos's own corpora are better and already here), BLEND (Blender's
internal memory layout, a moving target tied to one application), IRR/IRRMesh/MDL
(engine-specific rather than interchange).

Detection now reports Collada 1.4.0/1.4.1, FBX 7400/7500/7700, PLY 1.0 with ASCII/binary
encoding, STL ASCII/binary, BVH with frame counts, and IQM v2.

### Candidates not taken, and why

| Format | Domain | Status |
| --- | --- | --- |
| **USD / USDZ** | scene graph | The strategic 3D format. `OpenUSD` is 282 MB and NOASSERTION at the repo level; a usable slice needs picking, not a blanket glob. |
| **COLLADA CTS** | scene graph | Khronos's full conformance suite (176 MB) would deepen Collada well past assimp's 40 files. NOASSERTION — worth resolving. |
| **Spriter** (`.scml`) | 2D bone | A direct peer of Spine and DragonBones, open XML. No maintained corpus surfaced under an obvious name. |
| **Live2D Cubism** | 2D bone | Very widely used, but the runtime licence is restrictive and sample models are distributed under a separate agreement. Would need the layered treatment at best. |
| **Ogmo Editor 3** | tilemap | MIT, small. Worth adding next to LDtk if 2D level support widens. |
| **MSDF atlas** | text | `msdf-atlas-gen` (MIT) emits a JSON atlas that is becoming the default for GPU text. Aligned with `glyphatlas`. |
| **3MF** | mesh | `3mf-samples` is BSD-2-Clause and clean; manufacturing-oriented, so alignment is weaker. |
| **Box2D RUBE / physics** | physics | No dominant open serialisation exists. Note that Spine and DragonBones both now carry physics constraints, so physics may reach flight through formats it already reads rather than a new one. |

## A parser named for a format its namesake does not write

Worth recording as a category, because it is the kind of gap that stays invisible: a fixture
hunt that keeps failing may be failing because the format does not exist upstream.

`particles-formats/unityParse.ts` reads `UnityParticleDocument`. Unity's particle system —
Shuriken — is **built into the engine** and has been since Unity 3.5; nothing marketplace is
involved. But what Unity writes to disk is YAML, inside `.unity` scenes and `.prefab` files,
under its own internal field names. Taken from a real scene:

| Unity writes | flight's schema expects |
| --- | --- |
| `lengthInSec` | `duration` |
| `maxNumParticles` | `maxParticles` |
| `startLifetime` as a MinMaxCurve (`minMaxState`, `scalar`, `minCurve`…) | `startLifetime` as `{mode, constant \| constantMin/constantMax}` |
| *(no such field — it is a project setting)* | `physicsGravity` |

`UnitySchema.ts` says so itself: the shape is "based on … field names as exported by Unity's
JsonUtility and common third-party particle-system exporters", with curves "simplified to
constant or two-keyframe linear values". And `unitySerialize.ts` **writes** the same shape —
a format you both read and write is one you own, not one you import.

So `UnityParticleDocument` is a normalised interchange shape, and **there is no upstream
corpus for it by construction**. Three ways to close that, none of which is "search harder":

1. **Own it explicitly.** Document it as flight's interchange shape and name the converter
   that produces it. Fixtures are then authored to the schema, and `unitySerialize` →
   `unityParse` round-trip is the real test. Circular for "does this match Unity", perfectly
   sound for robustness and round-trip fidelity.
2. **Read what Unity actually writes.** Add a YAML path for `.unity`/`.prefab`, at which
   point real Unity projects become a large and freely licensed corpus.
3. **Take `JsonUtility.ToJson()` output.** That API is built into Unity, so it is one line of
   C# rather than a marketplace dependency — but it emits the *internal* names above, so
   something still has to normalise them.

`unity-native-fixtures` now holds the ground truth: **25 ParticleSystem components across 14
files**, from three sources (MIT and Apache-2.0), in both the scene-embedded and
standalone-prefab forms. Every component carries `serializedVersion` and the full twelve-module
set — `InitialModule`, `ShapeModule`, `EmissionModule`, `SizeModule`, `RotationModule`,
`ColorModule`, `UVModule`, `VelocityModule`, `InheritVelocityModule`, `ForceModule`,
`ExternalForcesModule`, `ClampVelocityModule` — all of which the normalised schema flattens
away. `serializedVersion` matters most: Unity bumps it as the component evolves, so it is what
any converter must branch on, and no fixture authored to our own schema would have surfaced it.

It is kept out of `particle-fixtures` on purpose. That pack holds dialects `particles-formats`
actually reads; this one is the reference against which the normalised shape can be judged.

The general lesson: when a format has a *serializer* on our side, check whether the name
refers to something a third party emits or to a shape we invented. The answer changes where
fixtures can come from.
