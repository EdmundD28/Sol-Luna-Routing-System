from __future__ import annotations

import copy
import unittest

from common import plain
from opsworkbench.artifacts import build_inventory, select_artifact, validate_artifact, validate_artifact_request
from opsworkbench.errors import WorkbenchError


SHA_A = "a" * 64
SHA_B = "b" * 64


def artifact(identifier="app", version="1.0.0", **changes):
    value = {"artifact_id": identifier, "version": version, "platform": "win", "architecture": "x64", "features": [], "checksum": SHA_A, "size_bytes": 10, "metadata": {}}
    value.update(changes)
    return value


def request(**changes):
    value = {"artifact_id": "app", "platform": "win", "architecture": "x64", "features": [], "allow_prerelease": False}
    value.update(changes)
    return value


class ArtifactAcceptance(unittest.TestCase):
    def error(self, code, path, operation):
        with self.assertRaises(WorkbenchError) as caught:
            operation()
        self.assertEqual((caught.exception.code, caught.exception.path), (code, path))

    def test_A068_validation_normalizes_features_and_detaches_metadata(self):
        raw = artifact(features=["z", "a"], metadata={"月": [1]})
        parsed = validate_artifact(raw, ("artifacts", 0))
        raw["metadata"]["月"].append(2)
        self.assertEqual(parsed.features, ("a", "z"))
        self.assertEqual(plain(parsed.metadata), {"月": [1]})
        with self.assertRaises(TypeError):
            parsed.metadata["x"] = 1
        with self.assertRaises(TypeError):
            parsed.metadata["月"][0] = 2

    def test_A069_validation_rejects_shape_bool_size_checksum_and_version(self):
        self.error("UNKNOWN_FIELD", ("artifacts", 2, "extra"), lambda: validate_artifact({**artifact(), "extra": 1}, ("artifacts", 2)))
        for field, value, code in (("size_bytes", True, "INVALID_FIELD"), ("checksum", "A" * 64, "INVALID_FIELD"), ("version", "01.0.0", "INVALID_VERSION"), ("features", ["x", "x"], "INVALID_FIELD")):
            with self.subTest(field=field):
                self.error(code, ("artifacts", 0, field), lambda field=field, value=value: validate_artifact(artifact(**{field: value}), ("artifacts", 0)))

    def test_A070_selection_uses_semver_then_size_and_excludes_prerelease(self):
        records = [artifact(version="2.0.0-alpha", checksum=SHA_B, size_bytes=99), artifact(version="1.9.0", features=["cpu"], size_bytes=20), artifact(version="1.9.0", features=["gpu"], checksum=SHA_B, size_bytes=30)]
        self.assertEqual(select_artifact(records, request()).checksum, SHA_B)
        self.assertEqual(select_artifact(records, request(allow_prerelease=True)).version, "2.0.0-alpha")

    def test_A071_selection_requires_artifact_feature_superset(self):
        records = [artifact(version="2.0.0", features=["base"]), artifact(version="1.0.0", features=["base", "gpu"], checksum=SHA_B)]
        selected = select_artifact(records, request(features=["gpu"]))
        self.assertEqual((selected.version, selected.features), ("1.0.0", ("base", "gpu")))

    def test_A072_selected_missing_checksum_is_structured(self):
        self.error("MISSING_CHECKSUM", ("artifacts", 0, "checksum"), lambda: select_artifact([artifact(checksum=None)], request()))

    def test_A073_duplicate_identity_is_idempotent_or_conflicting(self):
        same = artifact()
        self.assertEqual(len(build_inventory([same, copy.deepcopy(same)]).records), 1)
        conflict = artifact(metadata={"different": True})
        self.error("DUPLICATE_ARTIFACT", ("artifacts", 1), lambda: build_inventory([same, conflict]))

    def test_A074_inventory_is_semver_sorted_and_platform_indexed(self):
        records = [artifact("雪", "1.0.0", platform="linux"), artifact("app", "1.2.0"), artifact("app", "2.0.0", checksum=None)]
        inventory = build_inventory(records)
        self.assertEqual([(r.artifact_id, r.version) for r in inventory.records], [("app", "2.0.0"), ("app", "1.2.0"), ("雪", "1.0.0")])
        self.assertEqual(plain(inventory.by_platform), {"linux": ["雪"], "win": ["app"]})
        with self.assertRaises(TypeError):
            inventory.by_platform["win"] = ()
        with self.assertRaises(Exception):
            inventory.records += ()

    def test_A075_empty_inventory_and_no_match_are_deterministic(self):
        self.assertEqual(build_inventory([]).records, ())
        self.error("NO_COMPATIBLE_ARTIFACT", (), lambda: select_artifact([artifact(platform="linux")], request()))

    def test_A076_request_validation_rejects_bool_and_unknown_fields(self):
        self.error("UNKNOWN_FIELD", ("request", "x"), lambda: validate_artifact_request({**request(), "x": 1}))
        self.error("INVALID_FIELD", ("request", "allow_prerelease"), lambda: validate_artifact_request(request(allow_prerelease=1)))

    def test_A077_operations_do_not_mutate_inputs(self):
        records = [artifact(metadata={"nested": [10**80]})]
        before = copy.deepcopy(records)
        build_inventory(records)
        select_artifact(records, request())
        self.assertEqual(records, before)


if __name__ == "__main__":
    unittest.main()
