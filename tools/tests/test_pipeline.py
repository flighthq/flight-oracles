"""Tests for the flight-oracles pipeline.

Focused on the properties the sourcing policy actually promises, because those are the
ones whose silent failure would be worst: a redistribution prohibition being honoured, an
excluded file never reaching an archive, file-adjacent licences travelling beside their
assets, and archives rebuilding byte-identically.

Run: python3 -m unittest discover -s tools/tests
"""

from __future__ import annotations

import json
import struct
import sys
import pathlib
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oracles import derive, formats, pack, references, spec  # noqa: E402


# --- font builders -----------------------------------------------------------------
#
# Fonts are built here rather than checked in, because the properties under test are in
# the headers — a directory offset, a flag byte, an integer encoding — and a committed
# binary would prove the detector agrees with one file rather than with the format.


def _sfnt(flavor: bytes, tags) -> bytes:
    """A bare sfnt: flavour, table count, then a 16-byte record per table."""
    head = flavor + struct.pack(">HHHH", len(tags), 0, 0, 0)
    return head + b"".join(tag + struct.pack(">III", 0, 0, 0) for tag in tags)


def _woff(flavor: bytes, tags, total_sfnt: int = 0) -> bytes:
    """WOFF 1.0: a 44-byte header, then a 20-byte record per table."""
    head = (b"wOFF" + flavor + struct.pack(">I", 0)
            + struct.pack(">HH", len(tags), 0)
            + struct.pack(">I", total_sfnt)
            + struct.pack(">HH", 0, 0)
            + struct.pack(">IIIII", 0, 0, 0, 0, 0))
    assert len(head) == 44, len(head)
    return head + b"".join(tag + struct.pack(">IIII", 0, 0, 0, 0) for tag in tags)


def _uint_base128(value: int) -> bytes:
    """The WOFF2 variable-length integer: 7 bits a byte, high bit continues."""
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


def _woff2(flavor: bytes, tables) -> bytes:
    """WOFF2: a 48-byte header, then a variable-length record per table.

    *tables* is a sequence of (tag, transform version) pairs. A transformLength follows
    origLength exactly when the table is transformed, which for glyf and loca means
    version 0 and for everything else means version other than 0.
    """
    head = (b"wOF2" + flavor + struct.pack(">I", 0)
            + struct.pack(">HH", len(tables), 0)
            + struct.pack(">II", 0, 0)
            + struct.pack(">HH", 0, 0)
            + struct.pack(">IIIII", 0, 0, 0, 0, 0))
    assert len(head) == 48, len(head)
    known = {tag: i for i, tag in enumerate(formats._WOFF2_KNOWN_TAGS)}
    out = bytearray(head)
    for tag, version in tables:
        index = known.get(tag, 0x3F)
        out.append((version << 6) | index)
        if index == 0x3F:
            out += tag
        out += _uint_base128(64)
        transformed = (version == 0) if tag in (b"glyf", b"loca") else (version != 0)
        if transformed:
            out += _uint_base128(32)
    return bytes(out)


class TestFormats(unittest.TestCase):
    def test_swf_uncompressed(self):
        data = b"FWS" + bytes([6]) + (1234).to_bytes(4, "little") + b"\x00" * 8
        info = formats.detect(data, "x.swf")
        self.assertEqual(info["kind"], "swf")
        self.assertEqual(info["version"], "6")
        self.assertEqual(info["compression"], "none")
        self.assertEqual(info["uncompressedLength"], 1234)

    def test_swf_compression_variants(self):
        for sig, expect in ((b"CWS", "zlib"), (b"ZWS", "lzma")):
            data = sig + bytes([13]) + (99).to_bytes(4, "little") + b"\x00" * 8
            self.assertEqual(formats.detect(data, "x.swf")["compression"], expect)

    def test_riv_varuint_version(self):
        # RIVE + varuint major(7) + varuint minor(0)
        self.assertEqual(formats.detect(b"RIVE\x07\x00rest", "a.riv")["version"], "7.0")

    def test_riv_multibyte_varuint(self):
        # 0x80 0x01 == 128 under LEB128; catches a naive single-byte read.
        info = formats.detect(b"RIVE\x80\x01\x02", "a.riv")
        self.assertEqual(info["major"], 128)
        self.assertEqual(info["minor"], 2)

    def test_glb_container(self):
        import struct
        info = formats.detect(b"glTF" + struct.pack("<II", 2, 512), "a.glb")
        self.assertEqual(info["kind"], "glb")
        self.assertEqual(info["version"], "2")
        self.assertEqual(info["totalLength"], 512)

    def test_gltf_records_extensions(self):
        # Extension coverage is the reason this corpus exists, so it has to be queryable
        # from the manifest rather than only by re-reading every file.
        blob = json.dumps({
            "asset": {"version": "2.0"},
            "extensionsUsed": ["KHR_materials_sheen", "KHR_draco_mesh_compression"],
            "extensionsRequired": ["KHR_draco_mesh_compression"],
        }).encode()
        info = formats.detect(blob, "a.gltf")
        self.assertEqual(info["kind"], "gltf")
        self.assertEqual(info["version"], "2.0")
        self.assertEqual(info["extensionsUsed"],
                         ["KHR_draco_mesh_compression", "KHR_materials_sheen"])
        self.assertEqual(info["extensionsRequired"], ["KHR_draco_mesh_compression"])

    def test_gltf_not_confused_with_spine_json(self):
        # Both are JSON objects; the probes must key off their own marker field.
        gltf = json.dumps({"asset": {"version": "2.0"}}).encode()
        spine = json.dumps({"skeleton": {"spine": "4.2.11"}}).encode()
        self.assertEqual(formats.detect(gltf, "x.gltf")["kind"], "gltf")
        self.assertEqual(formats.detect(spine, "x.json")["kind"], "spine-json")
        self.assertIsNone(formats.detect(b'{"unrelated":1}', "x.json"))

    def test_ktx2_container(self):
        self.assertEqual(
            formats.detect(b"\xabKTX 20\xbb\r\n\x1a\n" + b"\x00" * 32, "t.ktx2")["kind"],
            "ktx2")

    def test_spine_json_version(self):
        blob = json.dumps({"skeleton": {"spine": "4.2.11"}}).encode()
        self.assertEqual(formats.detect(blob, "x.json")["version"], "4.2.11")

    def test_lottie_version_and_shape(self):
        blob = json.dumps({"v": "5.7.4", "fr": 30, "ip": 0, "op": 60,
                           "layers": [{}, {}]}).encode()
        info = formats.detect(blob, "a.json")
        self.assertEqual(info["kind"], "lottie")
        self.assertEqual(info["version"], "5.7.4")
        self.assertEqual(info["layerCount"], 2)

    def test_lottie_needs_both_version_and_layers(self):
        # A JSON Schema describing Lottie is not a Lottie animation; only the pair of
        # markers separates them.
        self.assertIsNone(formats.detect(json.dumps({"v": "5.7.4"}).encode(), "s.json"))
        self.assertIsNone(formats.detect(json.dumps({"layers": []}).encode(), "s.json"))

    def test_dragonbones_json_and_binary(self):
        blob = json.dumps({"version": "5.5", "armature": [{}]}).encode()
        info = formats.detect(blob, "x_ske.json")
        self.assertEqual((info["kind"], info["version"], info["armatures"]),
                         ("dragonbones", "5.5", 1))
        self.assertEqual(formats.detect(b"DBDT\x00\x00", "x.dbbin")["kind"],
                         "dragonbones-binary")

    def test_dragonbones_atlas_sidecar_distinguished(self):
        blob = json.dumps({"imagePath": "x.png", "SubTexture": []}).encode()
        self.assertEqual(formats.detect(blob, "x_tex.json")["kind"], "dragonbones-atlas")

    def test_tiled_xml_and_json_serialisations(self):
        tmx = b'<?xml version="1.0"?><map version="1.10" orientation="orthogonal">'
        info = formats.detect(tmx, "a.tmx")
        self.assertEqual((info["kind"], info["version"], info["orientation"]),
                         ("tmx", "1.10", "orthogonal"))
        tmj = json.dumps({"version": "1.10", "orientation": "isometric"}).encode()
        self.assertEqual(formats.detect(tmj, "a.tmj")["kind"], "tmj")
        self.assertEqual(formats.detect(tmx.replace(b"map", b"tileset"), "a.tsx")["kind"],
                         "tsx")

    def test_tiled_probes_key_off_extension_not_content(self):
        # TMX and TSX are both XML with a version attribute; only the extension separates
        # a map from a tileset, and a tileset parsed as a map would silently yield nothing.
        xml = b'<tileset version="1.5">'
        self.assertEqual(formats.detect(xml, "x.tsx")["kind"], "tsx")
        # The same bytes under a .xml name must NOT be claimed as a tileset. Since the
        # generic XML fallback was added it is identified as plain xml rather than nothing,
        # which is the same guarantee stated more usefully.
        self.assertEqual(formats.detect(xml, "x.xml")["kind"], "xml")

    def test_bmfont_text_serialisation(self):
        info = formats.detect(b"info face=\"Arial\" size=32\n", "a.fnt")
        self.assertEqual((info["kind"], info["version"]), ("fnt", "text"))

    def test_pex_is_distinguished_from_the_plist_form(self):
        # PEX and the ParticleDesigner plist carry the same emitter model in different
        # serialisations. Reporting both as "some XML"/"some plist" would lose the one fact
        # a multi-dialect parser needs.
        pex = (b'<?xml version="1.0"?><particleEmitterConfig>'
               b'<texture name="fire_particle.png"/><emitterType value="0"/>'
               b'</particleEmitterConfig>')
        info = formats.detect(pex, "fire.pex")
        self.assertEqual(info["kind"], "pex")
        self.assertEqual(info["texture"], "fire_particle.png")
        self.assertEqual(info["emitterType"], 0)

    def test_plist_dialects_are_distinguished(self):
        # Both Cocos dialects are property lists; only the payload says which model it
        # carries, and a parser handed the wrong one should refuse rather than half-succeed.
        sheet = b'<plist><dict><key>frames</key><dict/></dict></plist>'
        particle = b'<plist><dict><key>emitterType</key><real>0</real></dict></plist>'
        self.assertEqual(formats.detect(sheet, "a.plist")["kind"], "plist-spritesheet")
        self.assertEqual(formats.detect(particle, "a.plist")["kind"], "plist-particle")
        charmap = b'<plist><dict><key>textureFilename</key><string>f.png</string>' \
                  b'<key>itemWidth</key><integer>48</integer></dict></plist>'
        self.assertEqual(formats.detect(charmap, "a.plist")["kind"], "plist-charmap")
        self.assertEqual(formats.detect(b"<plist><dict/></plist>", "a.plist")["kind"], "plist")

    def test_svg_counts_path_data_and_expectation_pairs(self):
        doc = (b'<svg xmlns="http://www.w3.org/2000/svg" version="1.1">'
               b'<path d="M10-3.05176e-005"/><path d="M10-50l.2.30"/>'
               b'<rect x="1"/></svg>')
        info = formats.detect(doc, "a.svg")
        self.assertEqual(info["kind"], "svg")
        self.assertEqual(info["version"], "1.1")
        self.assertEqual(info["pathCount"], 2)     # the rect is not path data
        self.assertNotIn("expectationPairs", info)

    def test_svgo_fixture_pair_is_marked(self):
        # svgo ships input and expected output in one file. Flagging that is what tells a
        # consumer the file carries its own answer rather than being a plain document.
        doc = b'<svg><path d="M 10,50"/></svg>\n@@@\n<svg><path d="M10 50"/></svg>'
        info = formats.detect(doc, "convertPathData.01.svg.txt")
        self.assertEqual(info["kind"], "svg")
        self.assertEqual(info["expectationPairs"], 1)

    def test_svg_without_path_data_reports_zero(self):
        self.assertEqual(formats.detect(b'<svg><rect/></svg>', "a.svg")["pathCount"], 0)

    def test_xml_is_the_fallback_not_the_first_match(self):
        # SVG, Tiled, Starling atlases, PEX and BMFont XML are all XML. Identifying them as
        # "xml" would lose the fact that matters, so the generic probe must run last.
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
        tmx = b'<?xml version="1.0"?><map version="1.10"/>'
        self.assertEqual(formats.detect(svg, "a.svg")["kind"], "svg")
        self.assertEqual(formats.detect(tmx, "a.tmx")["kind"], "tmx")
        plain = b'<?xml version="1.0" encoding="UTF-8"?><doc><a/></doc>'
        info = formats.detect(plain, "a.xml")
        self.assertEqual((info["kind"], info["version"], info["encoding"]),
                         ("xml", "1.0", "UTF-8"))

    def test_xml_doctype_is_recorded(self):
        doc = b'<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.0//EN"><html/>'
        self.assertTrue(formats.detect(doc, "a.html")["hasDoctype"])

    def test_unknown_returns_none_rather_than_raising(self):
        # Not knowing a format is a fact to record, never a reason to drop a fixture.
        self.assertIsNone(formats.detect(b"\x00\x01\x02\x03nonsense", "mystery.bin"))

    def test_truncated_input_does_not_raise(self):
        for blob in (b"", b"F", b"RIVE", b"FWS", b"\x89PNG\r\n\x1a\n",
                     b"wOFF", b"wOF2", b"ttcf", b"OTTO"):
            formats.detect(blob, "t.bin")

    def test_sfnt_flavour_and_tables(self):
        ttf = _sfnt(b"\x00\x01\x00\x00", [b"glyf", b"loca", b"fvar", b"COLR"])
        info = formats.detect(ttf, "a.ttf")
        self.assertEqual((info["kind"], info["sfntVersion"]), ("ttf", "truetype"))
        self.assertEqual((info["outlines"], info["variable"], info["color"]),
                         ("glyf", True, ["colr"]))
        otf = formats.detect(_sfnt(b"OTTO", [b"CFF ", b"cmap"]), "a.otf")
        self.assertEqual((otf["kind"], otf["outlines"]), ("otf", "cff"))
        self.assertNotIn("variable", otf)

    def test_sfnt_magic_alone_is_not_enough(self):
        # 'true' is a valid sfnt flavour and also four bytes that turn up in text. Without
        # a table directory that actually fits, this must decline rather than guess.
        self.assertIsNone(formats.detect(b"true, and then some prose", "notes.txt"))
        self.assertIsNone(formats.detect(b"OTTO" + b"\xff\xff" + b"\x00" * 6, "a.otf"))

    def test_woff_reports_the_wrapped_flavour_not_its_own(self):
        # majorVersion/minorVersion in a WOFF header describe the FONT. WOFF's own version
        # is its signature, so that is what `version` records.
        woff = _woff(b"OTTO", [b"CFF ", b"cmap"], total_sfnt=4096)
        info = formats.detect(woff, "a.woff")
        self.assertEqual((info["kind"], info["version"]), ("woff", "1.0"))
        self.assertEqual((info["flavor"], info["outlines"], info["totalSfntSize"]),
                         ("cff", "cff", 4096))

    def test_woff2_table_directory_is_read_without_brotli(self):
        # Everything identifying the font sits in the uncompressed prologue after the
        # 48-byte header. Reading it from the wrong offset does not fail — it yields a
        # plausible tag list for the wrong tables — so the flavour and the outlines it
        # reports must agree.
        woff2 = _woff2(b"\x00\x01\x00\x00", [(b"glyf", 0), (b"loca", 0), (b"fvar", 0)])
        info = formats.detect(woff2, "a.woff2")
        self.assertEqual((info["kind"], info["version"], info["flavor"]),
                         ("woff2", "2.0", "truetype"))
        self.assertEqual((info["outlines"], info["variable"]), ("glyf", True))
        self.assertEqual(info["transformed"], ["glyf", "loca"])

    def test_woff2_null_transform_carries_no_transform_length(self):
        # Version 0 means *transformed* for glyf and loca and *untransformed* for every
        # other table — the one field in this header where the same value means opposite
        # things, and where getting it wrong desynchronises every later entry.
        woff2 = _woff2(b"OTTO", [(b"CFF ", 0), (b"cmap", 0), (b"glyf", 3)])
        info = formats.detect(woff2, "a.woff2")
        self.assertEqual(info["outlines"], "cff")
        self.assertNotIn("transformed", info)

    def test_ttc_reports_collection_membership(self):
        member = _sfnt(b"\x00\x01\x00\x00", [b"glyf", b"cmap"])
        head = b"ttcf" + struct.pack(">HHI", 1, 0, 2)
        offsets = struct.pack(">II", 12 + 8, 12 + 8 + len(member))
        info = formats.detect(head + offsets + member + member, "a.ttc")
        self.assertEqual((info["kind"], info["version"], info["numFonts"]),
                         ("ttc", "1.0", 2))
        self.assertEqual(info["outlines"], "glyf")

    def test_content_beats_extension_for_fonts(self):
        # OTS's corpus carries collections named .ttf on purpose. The extension is the
        # thing being tested, so it cannot be the thing we trust.
        member = _sfnt(b"\x00\x01\x00\x00", [b"glyf"])
        blob = b"ttcf" + struct.pack(">HHI", 1, 0, 1) + struct.pack(">I", 16) + member
        self.assertEqual(formats.detect(blob, "deceptive.ttf")["kind"], "ttc")

    def test_ttx_is_identified_as_more_than_generic_xml(self):
        doc = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
               b'<ttFont sfntVersion="\\x00\\x01\\x00\\x00" ttLibVersion="4.41">\n'
               b"  <GlyphOrder>\n  </GlyphOrder>\n"
               b"  <head>\n  </head>\n  <glyf>\n  </glyf>\n  <OS_2>\n  </OS_2>\n"
               b"  <cvt_>\n  </cvt_>\n</ttFont>\n")
        info = formats.detect(doc, "a.ttx")
        self.assertEqual((info["kind"], info["ttLibVersion"]), ("ttx", "4.41"))
        self.assertEqual(info["sfntVersion"], "truetype")
        # GlyphOrder is fontTools bookkeeping, not a table: head, glyf, OS/2, cvt .
        self.assertEqual((info["numTables"], info["outlines"]), (4, "glyf"))


class TestSpecValidation(unittest.TestCase):
    def _license(self, **kw):
        base = dict(declared="MIT", declared_scope="repository-root")
        base.update(kw)
        return spec.LicenseSpec(**base)

    def test_rejects_unknown_scope(self):
        with self.assertRaises(ValueError):
            self._license(declared_scope="vibes")

    def test_prohibition_required_when_not_redistributable(self):
        # The reason must survive without re-reading the upstream file.
        with self.assertRaises(ValueError):
            self._license(redistributable=False)
        self._license(redistributable=False, prohibition="may not be redistributed")

    def test_declaration_needing_review_blocks_until_acknowledged(self):
        # A tripwire, not a ban: the UGent s3(b) derivative-works term is invisible to anyone
        # screening on the SPDX id, so it must not be adoptable by accident.
        with self.assertRaises(ValueError) as caught:
            self._license(declared="LicenseRef-UGent-Academic")
        self.assertIn("needing review", str(caught.exception))

    def test_review_acknowledgement_unblocks(self):
        lic = self._license(declared="LicenseRef-UGent-Academic", hazard_reviewed=True)
        self.assertEqual(lic.declared, "LicenseRef-UGent-Academic")

    def test_review_guidance_scopes_the_hazard_to_rendered_output(self):
        # The scope correction matters as much as the flag: a decoder is not a derivative of
        # what it decodes, and structural oracles are measurements rather than adaptations.
        guidance = spec.DECLARATIONS_NEEDING_REVIEW["LicenseRef-UGent-Academic"]
        self.assertIn("DVD player", guidance)
        self.assertIn("PIXEL GOLDENS", guidance)

    def test_onward_use_is_validated(self):
        with self.assertRaises(ValueError):
            self._license(onward_use="wherever")

    def test_unrestricted_cannot_contradict_noncommercial(self):
        with self.assertRaises(ValueError):
            self._license(onward_use="unrestricted", commercial_use=False)
        self._license(onward_use="non-commercial", commercial_use=False)

    def test_onward_use_omitted_when_nothing_may_be_redistributed(self):
        # "How far may it travel" has no answer for material that never enters the build;
        # a default value in the lock would be misleading rather than merely unused.
        lic = self._license(redistributable=False, prohibition="may not be redistributed")
        self.assertNotIn("onwardUse", lic.to_json())

    def test_underlying_layer_requires_an_identifier(self):
        with self.assertRaises(ValueError):
            self._license(underlying=[{"note": "n"}])

    def test_underlying_layer_requires_a_note(self):
        # Recording a restrictive layer without saying why we may still publish reads as
        # an unexplained contradiction — worse than not recording it.
        with self.assertRaises(ValueError):
            self._license(underlying=[{"declared": "LicenseRef-Adobe-Stock"}])
        self._license(underlying=[{"declared": "LicenseRef-Adobe-Stock", "note": "why"}])

    def test_underlying_layers_survive_serialisation(self):
        lic = self._license(underlying=[{"declared": "X", "note": "n", "declaredFrom": "L.md"}])
        self.assertEqual(lic.to_json()["underlying"][0]["declaredFrom"], "L.md")

    def test_recovered_source_cannot_claim_a_declaration(self):
        # A recovered file has no upstream asserting anything; claiming MIT would be
        # inventing a declaration that nobody made.
        with self.assertRaises(ValueError):
            spec.SourceSpec(
                id="found", kind="recovered", include=["*.swf"],
                license=self._license(declared="MIT"),
            )
        spec.SourceSpec(
            id="found", kind="recovered", include=["*.swf"],
            license=self._license(declared="UNKNOWN"),
        )

    def test_file_adjacent_flag(self):
        self.assertTrue(self._license(declared_scope="file-adjacent").is_file_adjacent)
        self.assertFalse(self._license(declared_scope="directory").is_file_adjacent)

    def test_fetch_mode_is_validated(self):
        def source(**kw):
            return spec.SourceSpec(id="s", kind="upstream", repo="o/r", include=["**"],
                                   license=self._license(), **kw)
        self.assertEqual(source().fetch, "tarball")
        source(fetch="blobs")
        with self.assertRaises(ValueError):
            source(fetch="sparse-checkout")


class TestGitLfs(unittest.TestCase):
    """raw.githubusercontent serves LFS *pointers*, not objects.

    A 130-byte text stub sitting where a texture belongs passes every other check we have:
    it hashes consistently, it is byte-identical on re-ingest, and only a decoder would
    notice. KTX-Software stores its whole conformance corpus in LFS, so this is not
    hypothetical — it silently replaced 76 of 98 texture fixtures before being caught.
    """

    POINTER = (b"version https://git-lfs.github.com/spec/v1\n"
               b"oid sha256:" + b"ab" * 32 + b"\nsize 4096\n")

    def test_pointer_is_recognised(self):
        from oracles.ingest import _lfs_pointer
        self.assertEqual(_lfs_pointer(self.POINTER), ("ab" * 32, 4096))

    def test_real_content_is_not_mistaken_for_a_pointer(self):
        from oracles.ingest import _lfs_pointer
        for blob in (b"\x89PNG\r\n\x1a\n", b"RIVE\x07\x00", b"", b"version 2"):
            self.assertIsNone(_lfs_pointer(blob))

    def test_malformed_pointer_is_not_silently_accepted(self):
        from oracles.ingest import _lfs_pointer
        truncated = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\n"
        self.assertIsNone(_lfs_pointer(truncated))   # no size line -> not usable

    def test_format_detection_would_not_have_caught_it(self):
        # The reason this needed its own guard: a pointer is plain text, so every probe
        # returns None and the entry records `format: null` — indistinguishable from a
        # format we simply do not recognise yet.
        self.assertIsNone(formats.detect(self.POINTER, "conftest.ktx"))


class TestDerive(unittest.TestCase):
    """Malformed fixtures are generated, so they must be generated the same way twice."""

    SAMPLE = b"FWS" + bytes([6]) + (999).to_bytes(4, "little") + bytes(range(200))

    def test_derivation_is_deterministic(self):
        # Offsets come from the content's own hash, never a PRNG or a clock — which is what
        # lets these live in the same byte-reproducible pipeline as everything fetched.
        first = derive.derive_all("x.swf", self.SAMPLE, list(derive.STRATEGIES))
        second = derive.derive_all("x.swf", self.SAMPLE, list(derive.STRATEGIES))
        self.assertEqual([(n, b) for n, b, _ in first], [(n, b) for n, b, _ in second])

    def test_every_strategy_actually_changes_the_bytes(self):
        for name in derive.STRATEGIES:
            for label, mutated in derive.STRATEGIES[name](self.SAMPLE):
                self.assertNotEqual(mutated, self.SAMPLE, f"{name}/{label} was a no-op")

    def test_degenerate_inputs_are_included(self):
        labels = {label for label, _ in derive.STRATEGIES["empty"](self.SAMPLE)}
        self.assertEqual(labels, {"empty", "one-byte"})

    def test_short_input_does_not_crash_any_strategy(self):
        for blob in (b"", b"A", b"AB" * 3):
            for name in derive.STRATEGIES:
                list(derive.STRATEGIES[name](blob))

    def test_derived_names_keep_the_extension(self):
        # A decoder chosen by file extension has to still be reachable, or the corpus
        # tests nothing.
        for name, _, _ in derive.derive_all("a/b.swf", self.SAMPLE, ["truncate"]):
            self.assertTrue(name.endswith(".swf"), name)


class TestDerivedSpec(unittest.TestCase):
    def _license(self):
        return spec.LicenseSpec(declared="MIT", declared_scope="repository-root")

    def test_derived_requires_a_single_named_parent(self):
        # Deriving from one source block keeps the inherited declaration unambiguous.
        with self.assertRaises(ValueError):
            spec.SourceSpec(id="d", kind="derived", license=self._license(),
                            strategies=["truncate"], from_pack="p")
        spec.SourceSpec(id="d", kind="derived", license=self._license(),
                        strategies=["truncate"], from_pack="p", from_source="s",
                        from_include=["**/*.swf"])

    def test_derived_requires_a_parent_file_filter(self):
        # Without from_include a derivative silently widens whenever its parent does:
        # swf-ruffle-fixtures gained .toml configs and .as sources, and the malformed pack
        # began corrupting those, which tests nothing about any decoder.
        with self.assertRaises(ValueError) as caught:
            spec.SourceSpec(id="d", kind="derived", license=self._license(),
                            from_pack="p", from_source="s", strategies=["truncate"])
        self.assertIn("from_include", str(caught.exception))

    def test_derived_filter_selects_only_matching_parents(self):
        src = spec.SourceSpec(id="d", kind="derived", license=self._license(),
                              from_pack="p", from_source="s", strategies=["truncate"],
                              from_include=["**/*.swf"])
        self.assertTrue(src.selects_parent("avm1/x/test.swf"))
        self.assertFalse(src.selects_parent("avm1/x/test.toml"))
        self.assertFalse(src.selects_parent("avm1/x/Test.as"))

    def test_derived_requires_strategies(self):
        with self.assertRaises(ValueError):
            spec.SourceSpec(id="d", kind="derived", license=self._license(),
                            from_pack="p", from_source="s")

    def test_non_derived_still_requires_include(self):
        with self.assertRaises(ValueError):
            spec.SourceSpec(id="u", kind="upstream", repo="o/r", license=self._license())


class TestReferences(unittest.TestCase):
    """Descriptors name external files; shipping one without the other renders nothing.

    Six of nine packs shipped descriptors whose images were simply absent — 843 unresolved
    references — because each glob was written for the parser in front of me and nothing
    checked the whole. Every pack verified perfectly against its own lock the entire time.
    """

    def test_atlas_page_extraction(self):
        atlas = "pages.png\nsize: 512,512\nformat: RGBA8888\n  region\n  xy: 1, 1\n"
        self.assertIn("pages.png", list(references.extract("a.atlas", atlas.encode())))

    def test_bmfont_page_extraction(self):
        fnt = b'info face="Arial"\npage id=0 file="arial_0.png"\n'
        self.assertEqual(list(references.extract("a.fnt", fnt)), ["arial_0.png"])

    def test_tmx_image_and_external_tileset(self):
        tmx = (b'<map><tileset source="ts.tsx"/>'
               b'<imagelayer><image source="bg.png"/></imagelayer></map>')
        found = set(references.extract("a.tmx", tmx))
        self.assertEqual(found, {"ts.tsx", "bg.png"})

    def test_pex_texture_reference_is_followed(self):
        pex = b'<particleEmitterConfig><texture name="fire_particle.png"/></particleEmitterConfig>'
        self.assertEqual(list(references.extract("a.pex", pex)), ["fire_particle.png"])

    def test_mtl_options_are_not_mistaken_for_filenames(self):
        # map_Bump lines carry flags before the path; a naive first-token match yields
        # "-bs" or "bump" and then reports a missing file that was never named.
        mtl = b"map_Kd tex.png\nmap_Bump -bm 0.5 normal.png\n"
        self.assertEqual(set(references.extract("a.mtl", mtl)), {"tex.png", "normal.png"})

    def test_parent_relative_references_are_normalised(self):
        # PurePosixPath keeps ".." literally, so "../../x.png" never matched a stored path
        # and every relative-parent reference was reported missing. This is that regression.
        lock = {"pack": {"name": "p"},
                "files": [{"path": "data/x.jpg"}, {"path": "data/maps/m/a.tmx"}]}
        root = pathlib.Path(tempfile.mkdtemp())
        target = root / "vendor" / "p" / "data" / "maps" / "m"
        target.mkdir(parents=True)
        (target / "a.tmx").write_bytes(b'<map><image source="../../x.jpg"/></map>')
        (root / "vendor" / "p" / "data" / "x.jpg").write_bytes(b"\xff\xd8")
        self.assertEqual(references.unresolved([lock], root), [])

    def test_site_absolute_references_are_not_reported(self):
        # A docs site's own URL space cannot be satisfied by anything we place on disk.
        lock = {"pack": {"name": "p"}, "files": [{"path": "a.json"}]}
        root = pathlib.Path(tempfile.mkdtemp())
        d = root / "vendor" / "p"; d.mkdir(parents=True)
        (d / "a.json").write_bytes(
            json.dumps({"assets": [{"p": "/site/static/x.png"}]}).encode())
        self.assertEqual(references.unresolved([lock], root), [])


class TestPackOrdering(unittest.TestCase):
    """Derived packs must be ingested after the packs they derive from.

    Alphabetical order is not safe — malformed-fixtures derives from swf-ruffle-fixtures and
    rive-fixtures, both of which sort after it. A warm vendor/ hid this completely; the first
    cold run in CI failed on it.
    """

    def _pack(self, name, parents=()):
        lic = spec.LicenseSpec(declared="MIT", declared_scope="repository-root")
        sources = [spec.SourceSpec(id=f"{name}-{p}", kind="derived", license=lic,
                                   from_pack=p, from_source="s", strategies=["truncate"],
                                   from_include=["**/*"]) for p in parents]
        if not sources:
            sources = [spec.SourceSpec(id=name, kind="upstream", repo="o/r",
                                       include=["**"], license=lic)]
        return spec.PackSpec(name=name, kind="fixtures", summary="", sources=sources)

    def test_parents_are_ordered_first(self):
        packs = [self._pack("malformed", ["swf", "rive"]), self._pack("rive"),
                 self._pack("swf")]
        order = [p.name for p in spec.in_dependency_order(packs)]
        self.assertLess(order.index("swf"), order.index("malformed"))
        self.assertLess(order.index("rive"), order.index("malformed"))

    def test_cycle_is_reported_not_hung(self):
        packs = [self._pack("a", ["b"]), self._pack("b", ["a"])]
        with self.assertRaises(ValueError) as caught:
            spec.in_dependency_order(packs)
        self.assertIn("cycle", str(caught.exception))

    def test_every_pack_survives_ordering(self):
        packs = [self._pack("malformed", ["swf"]), self._pack("swf"), self._pack("other")]
        self.assertEqual(len(spec.in_dependency_order(packs)), 3)


class TestGlobs(unittest.TestCase):
    def test_double_star_crosses_separators(self):
        rx = spec.compile_globs(["a/**/*.swf"])
        self.assertTrue(rx.match("a/b/c/x.swf"))
        self.assertTrue(rx.match("a/x.swf"))
        self.assertFalse(rx.match("b/x.swf"))

    def test_single_star_does_not_cross_separators(self):
        rx = spec.compile_globs(["a/*.riv"])
        self.assertTrue(rx.match("a/x.riv"))
        self.assertFalse(rx.match("a/b/x.riv"))

    def test_dest_mapping_strips_and_prefixes(self):
        source = spec.SourceSpec(
            id="s", kind="upstream", repo="o/r", include=["ex/**"],
            strip="ex/", dest="out/",
            license=spec.LicenseSpec(declared="MIT", declared_scope="repository-root"),
        )
        self.assertEqual(source.dest_for("ex/a/b.riv"), "out/a/b.riv")


def _lock(**overrides):
    lock = {
        "pack": {"name": "t", "kind": "fixtures", "summary": "test"},
        "sources": [
            {
                "id": "ok", "kind": "upstream", "repo": "o/r", "commit": "c" * 40,
                "retrieved": "2026-01-01",
                "license": {
                    "declared": "MIT", "declaredScope": "repository-root",
                    "commercialUse": True, "redistributable": True,
                    "onwardUse": "unrestricted",
                },
            }
        ],
        "files": [
            {"path": "a.riv", "sourceId": "ok", "sha256": "a" * 64, "size": 1},
            {"path": "b.riv", "sourceId": "ok", "sha256": "b" * 64, "size": 1},
        ],
        "totals": {"files": 2, "bytes": 2},
    }
    lock.update(overrides)
    return lock


class TestSelection(unittest.TestCase):
    def test_exclude_removes_entry_and_records_its_hash(self):
        lock = _lock()
        lock["files"][1]["exclude"] = {"reason": "takedown"}
        kept, excluded = pack.select(lock, "full")
        self.assertEqual([e["path"] for e in kept], ["a.riv"])
        self.assertIn("b" * 64, excluded)

    def test_non_redistributable_in_lock_is_a_hard_error(self):
        # Ingest should never vendor these; if one appears anyway, fail loudly rather
        # than quietly shipping it.
        lock = _lock()
        lock["sources"][0]["license"]["redistributable"] = False
        with self.assertRaises(pack.ExclusionBreach):
            pack.select(lock, "full")

    def test_demo_variant_keeps_noncommercial_but_drops_testing_only(self):
        # The tier that did not exist before: spineboy is redistributable and meant to be
        # shown; a model licensed only for testing glTF loaders is not. Collapsing both into
        # "not permissive" lost that distinction.
        lock = _lock()
        lock["sources"][0]["license"].update(commercialUse=False, onwardUse="non-commercial")
        self.assertEqual(len(pack.select(lock, "demo")[0]), 2)
        lock["sources"][0]["license"]["onwardUse"] = "testing-only"
        self.assertEqual(pack.select(lock, "demo")[0], [])

    def test_demo_variant_drops_unknown_scope(self):
        lock = _lock()
        lock["sources"][0]["license"]["onwardUse"] = "unknown"
        self.assertEqual(pack.select(lock, "demo")[0], [])
        self.assertEqual(len(pack.select(lock, "full")[0]), 2)

    def test_permissive_requires_unrestricted_onward_use(self):
        lock = _lock()
        lock["sources"][0]["license"]["onwardUse"] = "non-commercial"
        self.assertEqual(pack.select(lock, "permissive")[0], [])

    def test_permissive_drops_noncommercial(self):
        lock = _lock()
        lock["sources"][0]["license"]["commercialUse"] = False
        self.assertEqual(pack.select(lock, "permissive")[0], [])
        self.assertEqual(len(pack.select(lock, "full")[0]), 2)

    def test_permissive_drops_unresolved_depicts(self):
        lock = _lock()
        lock["files"][0]["depicts"] = {"subject": "x", "status": "unresolved"}
        kept, _ = pack.select(lock, "permissive")
        self.assertEqual([e["path"] for e in kept], ["b.riv"])

    def test_permissive_accepts_an_explicit_conclusion(self):
        # A hardcoded identifier list cannot recognise PngSuite's grant or a third party's
        # public-domain declaration. Without this, the most permissive corpora we hold were
        # silently absent from the permissive variant.
        lock = _lock()
        lock["sources"][0]["license"]["declared"] = "LicenseRef-PngSuite-Permissive"
        self.assertEqual(pack.select(lock, "permissive")[0], [])
        lock["sources"][0]["license"]["permissive"] = True
        self.assertEqual(len(pack.select(lock, "permissive")[0]), 2)

    def test_permissive_conclusion_must_be_sourced(self):
        with self.assertRaises(ValueError):
            spec.LicenseSpec(declared="LicenseRef-X", declared_scope="directory",
                             permissive=True)
        spec.LicenseSpec(declared="LicenseRef-X", declared_scope="directory",
                         permissive=True, concluded="read the text; unconditional grant")

    def test_unicode_licence_is_recognised_as_permissive(self):
        # The oracle corpus is the most permissively licensed material here; it was being
        # dropped from -permissive purely for lacking an entry in the identifier list.
        self.assertIn("Unicode-3.0", pack.PERMISSIVE_DECLARED)

    def test_permissive_drops_copyleft_declarations(self):
        for declared in ("GPL-3.0-or-later", "MPL-2.0"):
            lock = _lock()
            lock["sources"][0]["license"]["declared"] = declared
            self.assertEqual(pack.select(lock, "permissive")[0], [], declared)


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        vendor = self.root / "vendor" / "t"
        vendor.mkdir(parents=True)
        (vendor / "a.riv").write_bytes(b"RIVE\x07\x00A")
        (vendor / "b.riv").write_bytes(b"RIVE\x07\x00B")
        (self.root / "licenses").mkdir()
        (self.root / "licenses" / "ok@ccccccccccccc.txt").write_bytes(b"MIT text\n")
        self.addCleanup(self.tmp.cleanup)

    def _lockfile(self):
        import hashlib
        lock = _lock()
        for entry in lock["files"]:
            blob = (self.root / "vendor" / "t" / entry["path"]).read_bytes()
            entry["sha256"] = hashlib.sha256(blob).hexdigest()
            entry["size"] = len(blob)
        lock["sources"][0]["licenseSnapshot"] = "licenses/ok@ccccccccccccc.txt"
        return lock

    def test_archive_is_byte_reproducible(self):
        lock = self._lockfile()
        first = pack.build_pack(lock, self.root, self.root / "d1", "v1")
        second = pack.build_pack(lock, self.root, self.root / "d2", "v1")
        self.assertEqual(first[0]["sha256"], second[0]["sha256"])

    def test_archive_carries_provenance_documents(self):
        lock = self._lockfile()
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            names = set(tar.getnames())
            manifest = json.loads(tar.extractfile("manifest.json").read())
        self.assertLessEqual(
            {"manifest.json", "NOTICE.md", "README.md",
             "LICENSES/ok@ccccccccccccc.txt"}, names)
        self.assertEqual(manifest["variant"], "full")
        self.assertEqual(len(manifest["files"]), 2)

    def test_file_adjacent_licence_is_also_placed_beside_assets(self):
        # Spineboy's terms permit redistribution "as long as they are accompanied by this
        # license file"; the shared LICENSES/ copy alone does not satisfy that reading.
        lock = self._lockfile()
        lock["sources"][0]["license"]["declaredScope"] = "file-adjacent"
        lock["sources"][0]["license"]["declaredFrom"] = "ex/license.txt"
        lock["sources"][0]["adjacentPath"] = "license.txt"
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            self.assertIn("license.txt", tar.getnames())
            self.assertEqual(tar.extractfile("license.txt").read(), b"MIT text\n")

    def test_excluded_bytes_cannot_reach_an_archive(self):
        # The removal guarantee, enforced rather than trusted: an entry marked excluded
        # whose bytes are still reachable must fail the build.
        lock = self._lockfile()
        lock["files"][1]["exclude"] = {"reason": "takedown"}
        # Smuggle the excluded bytes back in under a second entry.
        lock["files"].append({
            "path": "b.riv", "sourceId": "ok",
            "sha256": lock["files"][1]["sha256"], "size": lock["files"][1]["size"],
        })
        with self.assertRaises(pack.ExclusionBreach):
            pack.build_pack(lock, self.root, self.root / "d", "v1")

    def test_canonical_spdx_text_accompanies_a_copyleft_declaration(self):
        # An upstream README saying "licensed under GPL 3.0" records the declaration but
        # does not discharge it — GPL-3.0 requires the text itself to travel along.
        spdx = self.root / "licenses" / "spdx"
        spdx.mkdir(parents=True)
        (spdx / "GPL-3.0-or-later.txt").write_bytes(b"GNU GENERAL PUBLIC LICENSE\n")
        lock = self._lockfile()
        lock["sources"][0]["license"]["declared"] = "GPL-3.0-or-later"
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            self.assertIn("LICENSES/GPL-3.0-or-later.txt", tar.getnames())

    def test_disjunctive_declaration_bundles_both_texts(self):
        spdx = self.root / "licenses" / "spdx"
        spdx.mkdir(parents=True)
        (spdx / "MIT.txt").write_bytes(b"MIT\n")
        (spdx / "Apache-2.0.txt").write_bytes(b"Apache\n")
        lock = self._lockfile()
        lock["sources"][0]["license"]["declared"] = "Apache-2.0 OR MIT"
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            names = set(tar.getnames())
        self.assertLessEqual({"LICENSES/MIT.txt", "LICENSES/Apache-2.0.txt"}, names)

    def test_notice_attributes_the_underlying_instrument_and_ships_its_text(self):
        # Attribution is the obligation the layered model creates. Naming an instrument
        # without shipping the document the reader is pointed at would be a weak form of it.
        (self.root / "licenses" / "ok-underlying-0@c.txt").write_bytes(b"Origin terms\n")
        lock = self._lockfile()
        lock["sources"][0]["license"]["underlying"] = [{
            "declared": "LicenseRef-Adobe-Stock",
            "declaredFrom": "Models/X/LICENSE.md",
            "note": "Origin instrument; publication rests on a separate arrangement.",
            "snapshot": "licenses/ok-underlying-0@c.txt",
        }]
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            notice = tar.extractfile("NOTICE.md").read().decode()
            self.assertIn("LICENSES/ok-underlying-0@c.txt", tar.getnames())
        self.assertIn("Underlying instrument", notice)
        self.assertIn("LicenseRef-Adobe-Stock", notice)
        self.assertIn("separate arrangement", notice)

    def test_readme_states_the_build_artifact_character(self):
        # The repository is a build step, not a distribution channel. GitHub releases are
        # publicly fetchable regardless of intent, so that framing has to be documented in
        # the artifact rather than only asserted in the policy doc.
        lock = self._lockfile()
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            readme = tar.extractfile("README.md").read().decode()
        self.assertIn("build artifact", readme)
        self.assertIn("not an asset library", readme)
        self.assertIn("terms travel with the files", readme)

    def test_variants_state_which_may_travel_onward(self):
        lock = self._lockfile()
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            full = tar.extractfile("README.md").read().decode()
        with tarfile.open(self.root / "d" / "t-permissive-v1.tar.gz") as tar:
            permissive = tar.extractfile("README.md").read().decode()
        self.assertIn("build input", full)
        self.assertIn("travel *onward*", permissive)

    def test_merge_group_extraction_note_appears(self):
        # Geometry and textures split across archives only resolve when extracted together.
        # Discovering that as a pile of missing textures would be a poor way to learn it.
        lock = self._lockfile()
        lock["pack"]["mergeGroup"] = "gltf-khronos"
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            readme = tar.extractfile("README.md").read().decode()
        self.assertIn("same directory", readme)
        self.assertIn("gltf-khronos", readme)

    def test_no_merge_note_when_pack_stands_alone(self):
        lock = self._lockfile()
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            readme = tar.extractfile("README.md").read().decode()
        self.assertNotIn("merge group", readme)

    def test_noncommercial_warning_appears_in_readme(self):
        lock = self._lockfile()
        lock["sources"][0]["license"]["commercialUse"] = False
        pack.build_pack(lock, self.root, self.root / "d", "v1")
        with tarfile.open(self.root / "d" / "t-full-v1.tar.gz") as tar:
            readme = tar.extractfile("README.md").read().decode()
        self.assertIn("prohibits commercial use", readme)


if __name__ == "__main__":
    unittest.main()
