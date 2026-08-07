# Fixture coverage

An exhaustive fixture target set, derived from what `flighthq/flight` actually parses rather
than from what is convenient to find.

Method: flight has 143 packages. The `*-formats` packages, plus `swf`, `abc`, `image-codec`,
`font`, `audio`, `video`, `texture-formats`, `compression` and `xml`, are the decode surface.
Every format one of them claims is a fixture obligation. Sources below were checked for
licence on 2026-08-05.

## The decode surface is the floor, not the ceiling

**Corrected 2026-08-07.** An earlier revision of this document used flight's current
parsers as a *filter* as well as a starting point: a format flight did not parse, or parsed
only shallowly, was written off as not worth sourcing. The section on fonts made that case
at length and was wrong within the year — downstream began validating WOFF2, at which point
the six four-byte files this document recommended supplied nothing at all.

The error is worth naming because it is not specific to fonts. Fixture demand is set by
where a consumer is *going*, and a corpus takes weeks of licence work while a parser takes
days; gating the slow half on the current state of the fast half guarantees the corpus
arrives after it was needed. Nothing about that reasoning was visible at the time — the
argument looked like admirable restraint, and the evidence that would have refuted it did
not exist yet.

So the standing rule is now the opposite: **source the format, let downstream decide
whether it needs it.** The obligations below are still obligations. They are no longer the
boundary. What still constrains sourcing is unchanged and unrelated to demand — licence
that cannot be established, size that cannot be justified, and corpora that do not exist.

The `-full` / `-demo` / `-permissive` variants are what make this affordable: a consumer
fetches the pack it wants, so a pack it never fetches costs it nothing. Breadth is paid for
in this repository's release size, not in every consumer's build.

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
| ✅ `rive-fixtures-unit` | .riv (388 files) | `scene2d-formats` | rive-app/rive-runtime | MIT (repo-root) |
| ✅ `gltf-khronos-fixtures` | glTF, 28 KHR/EXT ext. | `scene3d-formats` | KhronosGroup/glTF-Sample-Assets | **per-model LICENSE.md** |
| ✅ `gltf-khronos-textures` | raster textures | demo/render | KhronosGroup/glTF-Sample-Assets | per-model |
| ✅ `gltf-khronos-binary` | GLB container | `scene3d-formats` | KhronosGroup/glTF-Sample-Assets | per-model |
| ✅ `gltf-generated-fixtures` | glTF conformance matrix | `scene3d-formats` | KhronosGroup/glTF-Asset-Generator | MIT |
| ✅ `lottie-fixtures` | Lottie JSON/.lottie | `scene2d-formats` | LottieFiles/lottie-docs, airbnb/lottie-web | CC-BY-4.0 / MIT |
| ✅ `dragonbones-fixtures` | DragonBones JSON | `skeleton2d-formats` | DragonBones/DragonBonesJS | MIT |
| ✅ `mesh-legacy-fixtures` | OBJ, MTL, MD2, MD5, 3DS, AWD2 | `scene3d-formats` | flighthq-ports/awayjs-examples (AWD2) + per-format | MIT |
| ✅ `texture-container-fixtures` | KTX2, KTX1, Basis, DDS, ASTC, PVR* | `texture-formats` | KTX-Software, basis_universal, ARM-software/astc-encoder | NOASSERTION / Apache-2.0 |
| ✅ `draco-fixtures` | Draco geometry, 6 bitstream versions | `scene3d-formats` | google/draco | Apache-2.0 |
| ✅ `font-fixtures` | TTF, OTF, TTC, WOFF, WOFF2, variable, MATH | `font` | adobe-fonts/source-sans, JetBrains/JetBrainsMono, googlefonts/fontations, web-platform-tests/wpt | OFL-1.1, Apache-2.0, BSD-3-Clause |
| ✅ `font-malformed-fixtures` | malformed/fuzzed fonts, all wrappers | `font` | khaledhosny/ots | **undeclared** |
| ✅ `text-conformance-fixtures` | UAX #9/#14/#29 | `textbidi`, `textsegment` | Unicode UCD | Unicode-3.0 |
| ✅ `text-rendering-fixtures` | shaping, 744 expected outlines | `textshaper`, `textlayout` | unicode-org/text-rendering-tests | Unicode-3.0 |
| ✅ `image-fixtures` | PNG only — PngSuite | `image-codec` | pnggroup/libpng | LicenseRef-PngSuite-Permissive |
| ✅ `image-codec-fixtures` | JPEG, GIF, WebP, AVIF, BMP, TIFF, ICO, TGA, QOI, HDR, EXR, farbfeld, JXL, PNM, PCX, XCF | `image-codec` | image-rs/image, libsdl-org/SDL_image, webmproject/libwebp-test-data | MIT, Zlib, BSD-3-Clause, **undeclared** |
| ✅ `spritesheet-fixtures` | TexturePacker, Starling, cocos plist, libgdx, Aseprite | `spritesheet-formats`, `textureatlas-formats` | per-tool samples + aseprite/aseprite | varies, MIT |
| ✅ `psd-fixtures` | PSD and PSB | (not yet parsed) | psd-tools/psd-tools | MIT |
| ✅ `tilemap-fixtures` | Tiled TMX/TMJ | `tilemap-formats` | mapeditor/tiled | NOASSERTION |
| ✅ `particle-fixtures` | libgdx, PEX, pixi, Unity, ParticleDesigner, Spine | `particles-formats` | per-tool samples | varies |
| ✅ `bitmapfont-fixtures` | BMFont .fnt/XML/JSON | `bitmapfont-formats` | AngelCode BMFont | varies |
| ✅ `svg-path-fixtures` | SVG path `d` grammar, 371 expected-output pairs | `path-formats` | svg/svgo, feathericons/feather | MIT |
| ✅ `xml-conformance-fixtures` | XML incl. malformed, with expected diagnostics | `xml` | GNOME/libxml2 | MIT |
| ✅ `media-container-fixtures` | MP4, WebM, Ogg, WAV, MP3, WebVTT | `audio`, `video` | web-platform-tests/wpt | BSD-3-Clause |
| ○ `audio-codec-fixtures` | AAC, FLAC, Opus, Vorbis bitstreams, SWF-ADPCM | `audio` | Xiph test vectors, per-codec | varies |
| ○ `video-codec-fixtures` | H.264, VP8/VP9, AV1 bitstreams, MKV, MOV, 3GPP | `video` | per-codec vector sets | varies |
| ○ `swf-generated-fixtures` | targeted SWF tags | `swf` | self-compiled (Apache Flex SDK) | Apache-2.0 |
| ✅ `compression-fixtures` | brotli, zstd, snappy, zlib | `compression` | google/brotli, google/snappy, facebook/zstd, madler/zlib | MIT, BSD-3-Clause, Zlib |
| ✅ `malformed-fixtures` | truncated/corrupt, all formats | all decoders | derived + PngSuite | derived |

## Fonts: what the four-byte argument got wrong

This section previously argued that fonts needed almost nothing. The observation it rested
on was correct and is still correct: `packages/font/src/fontFormat.ts` is a **four-byte
magic-number sniff** — `00 01 00 00` → truetype, `OTTO` → opentype, `wOFF` → woff,
`wOF2` → woff2, `ttcf` → collection, `true` → truetype — and its sibling
`inferFontFormatFromUrl` is pure string handling on the extension. Neither reads a glyph.
The architectural reason still holds too: `textshaper-canvas` delegates shaping to the
platform, so what flight implements itself — itemization, clustering, bidi, segmentation —
is exercised by Unicode character data rather than font binaries.

The conclusion drawn from all that — six synthesized files of four bytes each, sourcing a
real corpus "would buy nothing" — did not survive. A downstream font-formats library is now
validating WOFF2, and against that, four bytes establish that a file *claims* to be WOFF2
and nothing else. The corpus needed to have existed before the parser did.

**`font-fixtures` and `font-malformed-fixtures` now hold it.** What they are built around:

### The wrapper matrix is the oracle

Adobe ships Source Sans 3 as the same fourteen faces in OTF, TTF, WOFF-of-OTF, WOFF-of-TTF,
WOFF2-of-OTF and WOFF2-of-TTF, plus a variable font in all six. The join key is in the
filename — `WOFF2/OTF/SourceSans3-Black.otf.woff2` names `OTF/SourceSans3-Black.otf` — so a
decoder can decompress a wrapper and check it against the sfnt it was built from, with
nothing to generate and no manifest to maintain.

How hard that check can be pushed differs between the wrappers, and assuming the stronger
one produces false failures:

| | Relationship to the source sfnt |
| --- | --- |
| **WOFF** | Each table is zlib-compressed independently. Decoded table bytes are **identical** to the source sfnt's. Verified here: all 19 tables of `SourceSans3-Regular.ttf.woff` match the TTF byte for byte, and the header's `totalSfntSize` equals the TTF's file size exactly. |
| **WOFF2** | A brotli stream over a **reordered** table set, with `glyf`/`loca` (and optionally `hmtx`) **transformed** rather than merely compressed. A conforming decoder produces functionally equivalent tables, **not** identical bytes. Compare parsed structure, or restrict byte comparison to untransformed tables. |

The lock records which tables each WOFF2 declared transformed, so that distinction is a
per-file fact rather than an assumption.

### Micro-fonts cover what real fonts cannot

A real font carries whichever `cmap` subtable its designer's tool emitted. `fontations`'
test data is the opposite: a few hundred bytes each, built to exercise **one** thing —
`cmap` formats 4, 6, 10, 12 and 14; COLRv1; CBDT; sbix; `gvar`; `cvar`; VARC; `morx` — plus
the only TTC here, and `.ttx` files that are fontTools' XML serialisation of the same fonts,
which is as close to a structural expectation as a font corpus gets without rendering.

### The negative half decides whether support is real

`font-malformed-fixtures` takes the OpenType Sanitiser's corpus. OTS is the validator inside
Chrome and Firefox — every web font either passes it or is not rendered — so its test
material is what actually reached browsers, not hypothetical damage. Its two directories
carry **different** expectations, and reading them as one set gets both wrong: `bad/` must be
rejected, while `fuzzing/` need not be — the property there is that nothing hangs, crashes
or allocates unboundedly, which is exactly the contract `swfDocument.test.ts` states for
flight and which no well-formed corpus can establish.

Its `good/` directory is deliberately left behind: 57 MB of real-world fonts named by content
hash with no declaration of any kind, where the positive half is already better served by
fonts that arrive with licences attached.

### Diagnostic fonts, and a hypothesis that did not survive checking

A reasonable guess about where W3C fonts would matter here: that SVG fixtures name specific
W3C fonts, making those fonts a dependency of rendering the SVGs correctly. **Checked, and
it is not the case.** Across all 302 vendored SVG files and every XHTML/HTML document in the
corpus, exactly four files reference `font-family` at all, and they name `monospace` and
`Helvetica` — generic and system families, nothing W3C-specific. Only two vendored SVGs
contain a `<text>` element, so almost none of this corpus needs a font to render at all.

The instinct was right about the destination and wrong about the route. W3C fonts belong
here, just not because an SVG asked for them: **web-platform-tests ships a `fonts/`
directory of 203 test fonts**, and it is a category none of the three sources above cover —
fonts whose output is a *measurement* rather than a rendering:

| | What it is for |
| --- | --- |
| `Ahem.ttf` | Every glyph is a solid block on a known em square, so rendered output is arithmetic. It is the font behind a large share of CSS and SVG layout tests. |
| `pass.woff` / `fail.woff` | The W3C WebFonts Working Group's WOFF test pair — name tables "WOFF Test TTF" and "WOFF Test TTF Fallback". Load one as the webfont and the other as the fallback, and which one rendered answers "did the WOFF decode" with no inspection. The same construction is what a WOFF2 support claim wants. |
| `CanvasTest-*.ttf` | Deliberately odd vertical metrics — ascent 256, descent 0, no space glyph — so a metrics reader is checked against numbers. |
| `math/*.woff` (81) | MATH-table fonts, one per construction. Nothing else here carries a MATH table. |
| `baseline-diagnostic` | Baseline alignment, with the metrics documented in its README. |
| `CSSTest` (52) | Modified Gentium Basic differing mostly in name table and cmap — built to test font *matching* rather than rendering. |

Six source blocks, because the declarations genuinely differ: web-platform-tests' BSD-3-Clause
over the fonts it built, and separate OFL-1.1 declarations from SIL (CSSTest), Adobe (the
orientation-test fonts), Google (five Noto subsets), Eli Heuer (a monospace Arabic face for
bidi-against-line-breaking) and Sajid Anwar (baseline-diagnostic). Each ships beside its own
licence text.

This is also the first source to use `subtree` — see the media section — since reaching 4.9 MB
of fonts inside a 2.6 GB repository is not possible any other way.

### Detection now reads font containers properly

`formats.py` reports sfnt flavour, TTC membership, WOFF/WOFF2 flavour and `totalSfntSize`,
which tables were transformed, and for every container the outline flavour (`glyf`/`CFF`/
`CFF2`), whether it is variable (`fvar`), and which colour technology it uses (COLR, CBDT,
sbix, SVG). WOFF2's table directory is parsed **without brotli** — it sits uncompressed
after the 48-byte header — so those facts are recorded for compressed fonts too, with no
dependency added.

That makes the manifest queryable in the way the container-format facts elsewhere already
are: "every fixture carrying a `CFF2` table" is a decoder obligation, and a corpus you
cannot ask that question of is a pile of files.

One thing the corpus establishes immediately: **19 files in the OTS set carry `ttcf` magic
under a `.ttf` extension.** Content-based detection catches it; `inferFontFormatFromUrl`
cannot, by construction.

If a real font is needed for an end-to-end *rendering* path rather than a decode path,
`flighthq/flight-assets` still ships several — that is example media and remains its home.

## Raster codecs: a target set that had been read as a shipped set

`image-fixtures` was listed in this table against "PNG, JPEG, GIF, WebP, AVIF, BMP, TIFF,
ICO". It is PngSuite, and PngSuite is PNG. The other seven had nothing behind them, and the
row read as though they did — a target set entered as a shipped one, which is the failure
mode a coverage table exists to prevent.

`image-codec-fixtures` closes it, and closes more than the row claimed: JPEG, GIF, WebP,
AVIF, BMP, TIFF, ICO, plus TGA, QOI, HDR, EXR, farbfeld, JPEG XL, PNM, PCX, CUR, ANI and XCF.

### The reference renderings are the oracle, joined by a suffix

`image-rs/image` stores each input under `images/<codec>/…` and its decoded rendering under
`reference/<codec>/…` with `.png` appended:

    images/gif/anim/mixed-disposal.gif
    reference/gif/anim/mixed-disposal.gif.png            <- the composited result
    reference/gif/anim/mixed-disposal.gif.anim_01.png    <- and each frame

So the join is "append `.png`", with `.anim_NN` for frames. That is a per-file expectation
across twelve codecs, and the per-frame half matters most: disposal and blend modes produce
a plausible frame one and diverge at frame two, which is the animation bug that ships.

The renderings are PNG — TIFF where the content is floating point — and carry a CRC of the
image data in the filename, so a consumer is comparing decoded pixels rather than file bytes.

### Three licence postures inside one upstream

image-rs is MIT/Apache-2.0, but it imported two corpora that arrived with their own terms and
kept those declarations in place, so it is split across three source blocks:

- **The TrueVision TGA 2.0 suite** carries a `LICENSE` saying the material was "publicly
  available, free of charge and under **no specific licensing terms**" from a TrueVision FTP
  server that no longer exists, and that everything is "copyright to TrueVision, Inc." A
  statement that no terms were specified is not a grant, so it ships declared UNKNOWN. It is
  still the canonical TGA corpus — colour-mapped, RLE, 16-bit, attribute-bit and origin-flag
  cases nothing else here reaches — so it is kept and labelled rather than dropped or
  laundered under the crate's MIT.
- **The APNG cases** came from web-platform-tests and carry WPT's BSD-3-Clause.
- **Everything else** is the crate's own regression material under MIT.

`libwebp-test-data` is the fourth posture: 131 WebP files covering each alpha filter and
compression method separately, the lossless transforms, and a run of named decoder bugs — and
**no licence file of any kind**. libwebp itself is BSD-3-Clause, but that declaration is about
the library and was never carried into the data repository, so claiming it would be inventing
the grant. UNKNOWN, build input only.

### Detection, and what it is for

Sixteen probes were added, each reporting what a decoder branches on rather than what a file
browser shows: JPEG's SOF marker (baseline / progressive / arithmetic, the distinction where
a baseline-only decoder produces a blurry picture instead of an error), BMP's DIB header size
— which *is* its version, and the corpus turns out to span six of them — TIFF's byte order
and whether it is BigTIFF, WebP's `VP8 `/`VP8L`/`VP8X` variant and the extended flag byte that
is the only place alpha and animation are declared before the frames, and ISO base media
brands, which cover AVIF and HEIF now and MP4, MOV and 3GP when video arrives.

Two false positives were worth the guards they cost, and both are the same shape — a magic
number short enough to occur by accident:

- **`\x00\x00\x01\x00` claimed 81 glTF binary buffers as icons.** ICO has no magic string,
  only a reserved zero and a count. Requiring each directory entry's payload to actually
  begin with a PNG signature or a real DIB header rules them out; containment alone did not.
- **`BM` claimed six binary BMFont descriptors as bitmaps.** AngelCode's binary `.fnt` starts
  `BMF` and a version byte. Ruled out explicitly rather than by probe ordering, because the
  ordering that fixes it is invisible to whoever edits the list next.

Both are recorded here because the lesson generalises past these two: a two-to-four byte
signature is a hypothesis, and the corroboration has to come from a structure that cannot
line up by chance.

## Audio and video: the container is the decode surface

`audio` and `video` were the two packages the old gate excluded most firmly, on the
reasoning that flight implements no codecs. It does not — and that is beside the point. A
decode surface meets a **container** long before it meets a bitstream: reading an MP4 means
walking ISO base media boxes, a WebM means walking EBML, a WAV means walking RIFF chunks.
All three are parseable and testable with no codec involved, and all three are where the
security-shaped bugs live, because that is the layer that reads lengths and offsets out of
the file and believes them.

`media-container-fixtures` is that layer. Codec *bitstream* conformance — the AV1, VP9,
H.264 and Opus vector sets — is a separate and much larger question, deliberately not
attempted here.

web-platform-tests is the source because it is the corpus browsers are held to, its media
directory is kilobytes per case rather than clips, and the same content ships as **both**
containers under matching names — `test-1s.mp4` / `test-1s.webm`, `white.mp4` /
`white.webm`, `counting.mp4` / `counting.webm`. That is the cross-container pairing the
wrapper matrix is for fonts: two containers, one payload, so a demuxer's output can be
compared across them rather than merely inspected.

Several files also state their own coverage in their names —
`test-a-128k-44100Hz-1ch.webm` is audio-only, `test-v-128k-320x240-24fps-8kfr.webm` is
video-only, `test-av-384k-…` is both muxed together. Audio-only and video-only are the two
cases a demuxer written against a muxed file gets wrong.

### `subtree`: a pipeline change this source forced

wpt is 2.6 GB with over 61,000 tree entries. The tarball is absurd for 15 MB of media, and
a recursive tree listing comes back **truncated** — which blob mode refuses outright rather
than silently selecting a fraction of what the globs asked for. Neither fetch mode could
reach this repository at all.

`subtree` scopes a blob-mode listing to one directory via the tree API's `<commit>:<path>`
form, which returns that subtree untruncated. Paths are re-prefixed on the way out, so
`include`, `strip` and `exclude_paths` are written exactly as they would be otherwise, and
a licence declared at the repository root — outside the scoped listing — is fetched by path
rather than reported as missing from the commit.

The spec rejects an `include` pattern that does not sit under the subtree, because a pattern
that *cannot* match produces the same silence as a pattern that matched nothing, and this
repository has been bitten by that shape of bug before.

### Detection

EBML with its DocType (WebM is a profile of Matroska, so the magic is identical and only
DocType separates them — a demuxer keying off magic alone cannot tell it has the wrong
one), Ogg with the codec named by its first packet, MP3 and ADTS AAC, FLAC, and WebVTT. ISO
base media and RIFF were already added for the image codecs and cover MP4, MOV, 3GP and WAV
without further work — which is most of the reason to have written them generically.

Two of these needed the same discipline as the image probes: MP3 has **no signature at
all**, only an eleven-bit frame sync that occurs freely in binary data, so it is gated on
the extension unless an ID3v2 tag is present; and Ogg's first packet is not at a fixed
offset, since the page header is 27 bytes *plus one lacing byte per segment* — assuming
otherwise found no codec on any real file.

## What is blocked, and by what

Kept as a list rather than left as an absence, because the failure mode is someone spending
a day rediscovering that a corpus does not exist. Each entry names the specific obstacle, so
it is clear what would have to change.

**The corpus does not exist upstream.** Searching harder will not help:

| | Checked |
| --- | --- |
| **Ogmo Editor 3** | `Ogmo-Editor-3/OgmoEditor3-CE` is MIT and reachable, and contains **zero `.ogmo` project files** — it is the editor's source, not a corpus. Reopening it on licence grounds was right; there is simply nothing there. |
| **MSDF atlas** | `Chlumsky/msdf-atlas-gen` is MIT and 148 KB: source, CMake and submodules, no sample output. The atlas would have to be generated by building the tool. |
| **Spriter `.scml`** | No maintained corpus surfaced under any obvious name, unchanged from the earlier sweep. |
| **Spine particles** | Still believed never to have shipped — see the section below. |

**Blocked by licence, not availability:**

| | Obstacle |
| --- | --- |
| **Live2D Cubism** | Sample models are distributed under a separate agreement from the runtime, and neither is a redistribution grant. This is the one case where the answer is "no", not "not yet". |
| **COLLADA CTS** | Khronos's full conformance suite is 176 MB and NOASSERTION at the repository level. Worth *resolving* with Khronos rather than working around — they have granted arrangements before, which is exactly what the layered `license.underlying` model already records for four glTF models. |

**Blocked by tooling this pipeline deliberately does not have:**

| | Obstacle |
| --- | --- |
| **W3C WOFF2 conformance suite** | `w3c/woff2-tests` publishes the *generators*, not the generated files — the suite itself was served from w3c-test.org and no capturable mirror surfaced. Running the generators needs fontTools, and this pipeline is stdlib-only on purpose. Its seed fonts are in the repository but carry no licence file at all. **The nearest substitute is already held**: wpt's `pass.woff`/`fail.woff` pair applies the same construction to WOFF. |
| **`swf-generated-fixtures`** | Targeted SWF tags need a Flash compiler to emit. The Apache Flex SDK still exists, but this would be the first pack whose inputs are *built* rather than fetched, which is a different kind of reproducibility problem — the compiler becomes part of the pin. |
| **EOT** | Microsoft's legacy webfont wrapper. No corpus with a usable declaration surfaced; the format predates the conventions that would make one findable, and the tools that produced it are gone. Left as a known gap rather than a target. |

**Blocked by not being in git at all.** This is the one obstacle the pipeline's whole model
cannot absorb, and it is worth stating because it looks like laziness otherwise. Codec
bitstream conformance vectors are published as tarballs on project web servers, not as
repositories:

| | Where they actually live |
| --- | --- |
| **Opus, Vorbis, Theora** | `opus-codec.org` / `people.xiph.org` tarballs. `xiph/opus` itself carries no vectors. |
| **VP8 / VP9** | Google Cloud Storage buckets that libvpx's build scripts download. |
| **AV1 video** | AOM's argon and stress suites, likewise hosted rather than versioned. |
| **FFmpeg FATE** | `ffmpeg.org/fate-suite`, rsync-distributed. |

Everything here is pinned by commit, and a tarball on a web server has no commit to pin.
The `kind = "recovered"` source type exists for material fetched by URL, but it deliberately
records `declared: UNKNOWN` and has nobody to notify on a dispute — which is the right
posture for genuinely orphaned files and the wrong one for a standards body's current
conformance suite. Adopting these means either mirroring them into a repository first, or
extending the model with URL pinning plus a content hash. That is a design decision, not an
afternoon.

**AV1 as a still image was reachable** and is now `avif-fixtures`, which is the closest
thing to codec-bitstream coverage this repository has: an AVIF file is an AV1 keyframe in an
ISO base media container, so the 170 images there exercise a real AV1 decoder path even
though they are filed as images.

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

The original sequencing here — glTF, then Unicode, then malformed, then the long tail — is
done, and every pack it named has shipped. What remains is the queue after the decode-surface
gate was dropped, ordered by coverage per unit of licence work:

1. ~~**`image-codec-fixtures`**~~ — **done**, see below. It was the largest live gap and it
   was mislabelled: `image-fixtures` is PngSuite and nothing else, while `image-codec`
   claims eight formats.
2. ~~**`audio-fixtures`** and **`video-fixtures`**~~ — **containers done**, see
   `media-container-fixtures` below. Codec *bitstream* conformance is the remaining half and
   is a much larger question: the vector sets are per-codec, large, and separately licensed.
   MKV, MOV and 3GPP containers are also still unsourced — wpt carries almost no MKV.
3. **`text-rendering-fixtures`** — unicode-org/text-rendering-tests, which carries expected
   output and would be the fifth oracle-bearing pack here. Now that real fonts are held, the
   shaping suite has fonts to shape.
4. **`draco-fixtures`**, **`swf-generated-fixtures`** — narrower, and both are self-contained.
5. **The candidates not taken below, re-judged.** Several were declined on the old reasoning
   (alignment with what flight parses) rather than on licence or size, and those declines
   should be revisited on their own merits.

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

Detection now reports every one of them. It did not always: for a while this document
claimed detection for six — Collada 1.4.0/1.4.1, FBX 7400/7500/7700, PLY 1.0 with
ASCII/binary encoding, STL ASCII/binary, BVH with frame counts, IQM v2 — while the other
fourteen sat in the locks with no format at all. Now added: LWO (by IFF form type, which is
also what separates it from Modo's LXO), LWS, DirectX `.x` with its text/binary/zip
encoding, AC3D, NFF, COB with its byte order, M3D, X3D, AMF, VRML, OFF, A3D, zipped Collada,
and 3DS MAX ASCII export.

Two of those are worth singling out.

**`.ase` is three unrelated formats.** Here it is 3DS MAX ASCII Export; elsewhere it is
Aseprite's binary sprite format or Adobe's swatch exchange. The probe reads content and does
not consult the extension at all, which is the only way that ends well.

**assimp ships UTF-16 copies of its ASCII models on purpose** — `SphereWithLight_UTF16LE.ac`,
`ThreeCubesGreen_UTF16BE.ASE` — because a reader that byte-compares against `AC3D` fails on
every one of them. Those are the files most worth identifying, and a byte-comparison probe is
precisely what cannot identify them. A BOM-aware pass transcodes the head first and records
the encoding it found, which also picked up **19 UTF-16 XML documents** in
`xml-conformance-fixtures` that had been sitting unidentified for the same reason.

### Candidates not taken, and why

Re-read after the decode-surface gate was dropped. Three declines below rest on licence or
on a corpus not existing, and those still hold — no policy change makes an undeclared
upstream declared. The two that rested on **alignment** — "we do not do 2D levels", "this
is manufacturing-oriented" — were the same reasoning the fonts section made, and are
reopened accordingly: both are small and cleanly licensed, which is the whole test now.

| Format | Domain | Status |
| --- | --- | --- |
| ~~**USD / USDZ**~~ | scene graph | **Closed** — see `usd-fixtures`. The obstacle was the wrong repository: `OpenUSD` is the implementation, while `usd-wg/assets` is the working group's asset repository under Apache-2.0, already curated. |
| **COLLADA CTS** | scene graph | Khronos's full conformance suite (176 MB) would deepen Collada well past assimp's 40 files. NOASSERTION — worth resolving. |
| **Spriter** (`.scml`) | 2D bone | A direct peer of Spine and DragonBones, open XML. No maintained corpus surfaced under an obvious name. |
| **Live2D Cubism** | 2D bone | Very widely used, but the runtime licence is restrictive and sample models are distributed under a separate agreement. Would need the layered treatment at best. |
| **Ogmo Editor 3** | tilemap | MIT, small. **Reopened** — was gated on 2D level support widening, which is not a reason to withhold a small MIT corpus. |
| **MSDF atlas** | text | `msdf-atlas-gen` (MIT) emits a JSON atlas that is becoming the default for GPU text. Aligned with `glyphatlas`. |
| ~~**3MF**~~ | mesh | **Closed** — see `3mf-fixtures`. |
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

## Which remaining gaps are real: a classification

Three of the formats still listed as "unfixtured" cannot be fixtured, and the reasons differ.
Sorting them mattered more than continuing to search.

**A serializer is a hint, not proof.** An earlier note here suggested that a format flight
both reads and writes is one flight owns. That is too crude: `libgdxSerialize`,
`starlingPexSerialize`, `cocosPlistSerialize`, `texturePackerSerialize` and
`bitmapFontFnt` all write *foreign* formats, and every one of those has a corpus here. The
real test is whether a third party emits it.

### Owned shapes — no corpus exists, by construction

| Format | Evidence |
| --- | --- |
| `shape-formats/shapeJson` | Its own header: "Serializes a shape's full drawing-command stream to a **native JSON string** that `parseShapeJson` restores." It is flight's serialisation of flight's in-memory `Shape`. No namesake, no third party, nothing to source. |
| `particles-formats/unityParse` | `UnityParticleDocument` is a normalised shape (see the section above); Unity writes YAML with different field names. |

Neither is a gap. What they need is round-trip property testing — `format` → `parse` →
compare — which is a different discipline from fixtures and which `shapeJson.test.ts`
already does. Worth noting that `shapeJson`'s header documents a deliberate one-way door:
JSON has no `NaN` or `Infinity` literal, so a non-finite coordinate serialises to `null` and
then refuses to parse back, chosen over silently restoring different geometry. A corpus could
not test that better than a property test.

### A cited spec that appears not to exist

`particles-formats/spineParse` reads `SpineParticleDocument`, whose schema cites "the Spine
4.x particle effect format (`.p` JSON variant) as documented by Esoteric Software" at
`esotericsoftware.com/spine-particle-effects`.

Three things point the other way. `spine-runtimes` contains **zero** `.p` files across both
branches we hold — the only particle-named file in it is an Unreal `.uasset`. The cited URL
does not resolve for us (403, though that may be our own network policy rather than a
missing page). And Esoteric's forum carries threads from 2018 and 2023 in which users are
*requesting* a particle system, which is not what a shipped feature looks like.

So this is most likely a parser for a format that was never released. That is worth
confirming with Esoteric before either sourcing fixtures or keeping the parser — and it is
emphatically not a fixture-sourcing problem.

### Genuinely open, and findable

| Format | Note |
| --- | --- |
| ~~`path-formats/svgPathData`~~ | **Closed** — see `svg-path-fixtures`. Coverage was measured at exactly zero (no `.svg` file and no path `d=` attribute anywhere across 26 packs) before the pack existed. |
| ~~`xml/xmlParse`~~ | **Closed** — see `xml-conformance-fixtures`. |

With that, every format flight parses has fixtures behind it, or is classified above as one
for which no corpus can exist.

### `xml-conformance-fixtures`, and why not the W3C suite

The canonical corpus is the W3C XML Conformance Test Suite, but it is published as a tarball
from w3.org rather than a repository, and no GitHub mirror with capturable provenance
surfaced. libxml2's own regression corpus is the better practical answer: MIT, in-repo,
maintained by the most widely deployed XML parser there is — and oracle-bearing.

`test/X` pairs with `result/X`. 1,184 files: **583 inputs, 601 expectations, 239 exact
pairs**, of which **83 are `.err` files recording the precise diagnostic a malformed document
should produce**, line numbers included. That makes it the fourth oracle-bearing corpus here,
and the only one whose expectations are *errors* rather than successful output:

    input     HTML/encoding-error.html
    expected  ./test/HTML/encoding-error.html:5: HTML parser error :
              Invalid bytes in character encoding

Selected by alignment: `errors/`, `valid/`, `VC/`, `VCM/`, `recurse/` (the billion-laughs
family — the one XML failure mode that is a denial of service rather than a parse error),
`XPath/` for `xmlQuery`, `XInclude/`, `c14n/`, and the `HTML/`+`SVG/` real-world documents.
Excluded `schemas/`, `relaxng/` and `schematron/` — 691 files testing XSD, RELAX NG and
Schematron validation, none of which flight implements.

### `svg-path-fixtures`, and why svgo rather than an icon set

672 files, 1,093 path `d=` attributes, **371 of them carrying their own expected output** —
the third oracle-bearing corpus here after the Unicode data and Ruffle's traces.

SVGO is an optimiser, so its tests are chosen to break path parsing. The `convertPathData`
cases cover the grammar's genuinely nasty corners, each of which a naive tokeniser gets
wrong:

    M10-3.05176e-005      scientific notation, no separator before the exponent
    M10-50.2.30-2         three numbers, no separators — ".2.30" is two decimals, not one
    M10-50l.2.30          implicit command continuation with leading-dot numbers
    M 10 , 50             arbitrary whitespace and comma mixing
    M-10-50               the negative sign doubling as the separator

Feather's 287 icons supply the other half: tool-written path data at volume, which is what
production input actually looks like once a program rather than a test author produced it.
