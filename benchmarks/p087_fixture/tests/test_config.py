from __future__ import annotations

import json
import math
import unittest

from common import plain
from opsworkbench.canonical import canonical_json, clone_json
from opsworkbench.config import ConfigLayer, MergedConfig, merge_layers, validate_layer
from opsworkbench.errors import WorkbenchError


def layer(identifier: str, data: dict) -> dict:
    return {"id": identifier, "data": data}


class ConfigAcceptance(unittest.TestCase):
    def error(self, code, path, operation):
        with self.assertRaises(WorkbenchError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)

    def test_A001_canonical_json_is_compact_sorted_unicode(self):
        self.assertEqual(canonical_json({"月": 2, "a": [1, {"z": 0}]}), '{"a":[1,{"z":0}],"月":2}')

    def test_A002_canonical_json_accepts_scalar_array_and_large_integer(self):
        huge = 10**100
        self.assertEqual(canonical_json([None, True, "雪", huge]), f'[null,true,"雪",{huge}]')

    def test_A003_canonical_json_normalizes_negative_zero(self):
        self.assertNotIn("-0", canonical_json({"x": -0.0, "nested": [-0.0]}))

    def test_A004_canonical_json_rejects_nonfinite_and_unsupported(self):
        for value in (math.nan, math.inf, {"x"}):
            with self.subTest(value=value):
                self.error("INVALID_JSON", (), lambda value=value: canonical_json(value))

    def test_A005_clone_json_detaches_every_nested_container(self):
        raw = {"a": [{"b": 1}]}
        cloned = clone_json(raw)
        raw["a"][0]["b"] = 2
        self.assertEqual(cloned, {"a": [{"b": 1}]})

    def test_A006_validate_layer_returns_frozen_detached_model(self):
        raw = layer("base", {"db": {"host": "localhost"}})
        parsed = validate_layer(raw)
        raw["data"]["db"]["host"] = "changed"
        self.assertIsInstance(parsed, ConfigLayer)
        self.assertEqual(parsed.layer_id, "base")
        self.assertEqual(parsed.data["db"]["host"], "localhost")
        with self.assertRaises(TypeError):
            parsed.data["db"]["host"] = "x"

    def test_A007_validate_layer_rejects_shape_id_and_data_types(self):
        self.error("UNKNOWN_FIELD", ("layers", 0, "extra"), lambda: validate_layer({"id": "x", "data": {}, "extra": 1}, 0))
        for raw in (layer("", {}), layer(3, {}), layer("x", [])):
            with self.subTest(raw=raw):
                with self.assertRaises(WorkbenchError):
                    validate_layer(raw, 0)

    def test_A008_validate_layer_rejects_reserved_keys_recursively(self):
        self.error("RESERVED_KEY", ("layers", 2, "data", "nested", "$bad"), lambda: validate_layer(layer("x", {"nested": {"$bad": 1}}), 2))

    def test_A009_merge_empty_layers_has_empty_data_and_sources(self):
        merged = merge_layers([])
        self.assertIsInstance(merged, MergedConfig)
        self.assertEqual(dict(merged.data), {})
        self.assertEqual(merged.sources, ())

    def test_A010_nested_mapping_merge_preserves_unoverridden_leaves(self):
        merged = merge_layers([layer("base", {"db": {"host": "a", "port": 1}}), layer("prod", {"db": {"host": "b"}})])
        self.assertEqual(plain(merged.data), {"db": {"host": "b", "port": 1}})

    def test_A011_scalar_and_list_values_replace_instead_of_merge(self):
        merged = merge_layers([layer("one", {"x": {"a": 1}, "items": [1, 2]}), layer("two", {"x": 4, "items": [3]})])
        self.assertEqual(plain(merged.data), {"items": [3], "x": 4})

    def test_A012_exact_delete_sentinel_removes_present_and_absent_paths(self):
        delete = {"$delete": True}
        merged = merge_layers([layer("one", {"a": 1, "nested": {"x": 2}}), layer("two", {"a": delete, "nested": {"missing": delete}})])
        self.assertEqual(plain(merged.data), {"nested": {"x": 2}})

    def test_A013_delete_lookalikes_are_rejected_not_treated_as_data(self):
        for value in ({"$delete": False}, {"$delete": True, "x": 1}):
            with self.subTest(value=value):
                with self.assertRaises(WorkbenchError):
                    merge_layers([layer("x", {"a": value})])

    def test_A014_sources_name_final_layer_for_every_leaf(self):
        merged = merge_layers([layer("base", {"z": 1, "nested": {"x": 2}}), layer("top", {"a": 4, "nested": {"x": 3}})])
        self.assertEqual([(source.layer_id, source.path) for source in merged.sources], [("top", ("a",)), ("top", ("nested", "x")), ("base", ("z",))])

    def test_A015_parent_replacement_removes_obsolete_descendant_sources(self):
        merged = merge_layers([layer("base", {"nested": {"x": 1, "y": 2}}), layer("top", {"nested": [3]})])
        self.assertEqual([(s.layer_id, s.path) for s in merged.sources], [("top", ("nested",))])

    def test_A016_duplicate_layer_ids_are_rejected_at_second_id(self):
        self.error("DUPLICATE_LAYER", ("layers", 1, "id"), lambda: merge_layers([layer("same", {}), layer("same", {})]))

    def test_A017_merge_does_not_mutate_or_alias_inputs(self):
        raw = [layer("base", {"a": [1], "b": {"c": 2}})]
        snapshot = json.loads(json.dumps(raw))
        merged = merge_layers(raw)
        self.assertEqual(raw, snapshot)
        raw[0]["data"]["a"].append(9)
        self.assertEqual(plain(merged.data), {"a": [1], "b": {"c": 2}})

    def test_A018_semantically_equal_layers_are_deterministic(self):
        left = merge_layers([layer("x", {"z": 1, "月": 2})])
        right = merge_layers([layer("x", {"月": 2, "z": 1})])
        self.assertEqual(canonical_json(left.data), canonical_json(right.data))
        self.assertEqual(left.sources, right.sources)

    def test_A019_error_object_is_structured_frozen_and_stable(self):
        details = {"why": ["test"]}
        error = WorkbenchError("BAD", ("x", 1), "broken", details)
        details["why"].append("changed")
        self.assertEqual((error.code, error.path, error.message), ("BAD", ("x", 1), "broken"))
        self.assertEqual(plain(error.details), {"why": ["test"]})
        with self.assertRaises(Exception):
            error.code = "OTHER"
        with self.assertRaises(TypeError):
            error.details["why"] = ()


if __name__ == "__main__":
    unittest.main()
