"""Tests for the flight-oracles pipeline.

Focused on the properties the sourcing policy actually promises, because those are the
ones whose silent failure would be worst: a redistribution prohibition being honoured, an
excluded file never reaching an archive, file-adjacent licences travelling beside their
assets, and archives rebuilding byte-identically.

Run: python3 -m unittest discover -s tools/tests
"""

from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oracles import formats, pack, spec  # noqa: E402


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

    def test_unknown_returns_none_rather_than_raising(self):
        # Not knowing a format is a fact to record, never a reason to drop a fixture.
        self.assertIsNone(formats.detect(b"\x00\x01\x02\x03nonsense", "mystery.bin"))

    def test_truncated_input_does_not_raise(self):
        for blob in (b"", b"F", b"RIVE", b"FWS", b"\x89PNG\r\n\x1a\n"):
            formats.detect(blob, "t.bin")


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
