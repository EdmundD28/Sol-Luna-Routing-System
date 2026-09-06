"""Independent public acceptance for the P110 profiled deployment plan."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError

from benchmarks.p085_fixture.deployplan import (
    ManifestError,
    Operation,
    ProfiledPlan,
    Service,
    apply_profile,
    compile_profiled_plan,
    compile_plan,
    dependency_closure,
    dependency_order,
    normalize_name,
    parse_manifest,
    render_plan,
    render_profiled_plan,
)


def manifest(*services: dict) -> dict:
    return {"services": list(services)}


def svc(name: str, image: str = "img:v1", **extra: object) -> dict:
    return {"name": name, "image": image, **extra}


def err_code(test: unittest.TestCase, fn, code: str, path: str | None = None) -> None:
    with test.assertRaises(ManifestError) as caught:
        fn()
    test.assertEqual(caught.exception.code, code)
    if path is not None:
        test.assertEqual(caught.exception.path, path)


class PreservedP085ContractTests(unittest.TestCase):
    def test_01_error_fields_and_text(self):
        error = ManifestError("BAD_NAME", "services[2].name", "invalid")
        self.assertEqual((error.code, error.path, error.message), ("BAD_NAME", "services[2].name", "invalid"))
        self.assertEqual(str(error), "BAD_NAME@services[2].name: invalid")

    def test_02_name_normalizes_and_rejects_invalid_values(self):
        self.assertEqual(normalize_name(" Web-API "), "web-api")
        for value in (None, 3, "", "9api", "web_api", "web api"):
            with self.subTest(value=value):
                err_code(self, lambda value=value: normalize_name(value), "BAD_NAME")

    def test_03_parse_defaults_and_canonical_collections(self):
        parsed = parse_manifest(manifest(svc(" API ", depends_on=[" DB ", "db"], env={"Z": 2, "A": True}, tags=[" Blue ", "blue"]), svc("db")))
        self.assertEqual(parsed[0], Service("api", "img:v1", ("db",), (("A", "true"), ("Z", "2")), ("blue",), 1))

    def test_04_parse_does_not_mutate_nested_input(self):
        raw = manifest(svc("api", depends_on=["db"], env={"A": "1"}), svc("db"))
        before = json.loads(json.dumps(raw))
        parse_manifest(raw)
        self.assertEqual(raw, before)

    def test_05_parse_rejects_duplicate_and_unknown_fields(self):
        err_code(self, lambda: parse_manifest(manifest(svc("API"), svc(" api "))), "DUPLICATE_SERVICE")
        err_code(self, lambda: parse_manifest({"services": [svc("api")], "extra": 1}), "UNKNOWN_FIELD", "extra")
        err_code(self, lambda: parse_manifest(manifest(svc("api", mystery=1))), "UNKNOWN_FIELD", "services[0].mystery")

    def test_06_parse_validates_image_replicas_environment(self):
        for image in (None, "", "   "):
            err_code(self, lambda image=image: parse_manifest(manifest(svc("api", image=image))), "BAD_IMAGE")
        for replicas in (True, -1, 1.5, "2"):
            err_code(self, lambda replicas=replicas: parse_manifest(manifest(svc("api", replicas=replicas))), "BAD_REPLICAS")
        err_code(self, lambda: parse_manifest(manifest(svc("api", env={"A": [1]}))), "BAD_ENV")
        self.assertEqual(parse_manifest(manifest(svc("api", replicas=0)))[0].replicas, 0)

    def test_07_dependency_order_closure_and_graph_errors(self):
        items = parse_manifest(manifest(svc("web", depends_on=["api"]), svc("db"), svc("api", depends_on=["db"]), svc("jobs", depends_on=["db"])))
        self.assertEqual([s.name for s in dependency_order(items)], ["db", "api", "jobs", "web"])
        self.assertEqual([s.name for s in dependency_closure(items, [" WEB ", "web"])], ["db", "api", "web"])
        err_code(self, lambda: dependency_closure(items, ["missing"]), "UNKNOWN_ROOT")
        cyclic = parse_manifest(manifest(svc("a", depends_on=["b"]), svc("b", depends_on=["a"])))
        err_code(self, lambda: dependency_order(cyclic), "DEPENDENCY_CYCLE")
        err_code(self, lambda: dependency_order(parse_manifest(manifest(svc("a", depends_on=["missing"])))), "UNKNOWN_DEPENDENCY")

    def test_08_compile_plan_preserves_operation_order_roots_and_digest(self):
        plan = compile_plan(manifest(svc("old")), manifest(svc("web", depends_on=["api"]), svc("api")))
        self.assertEqual([s.name for s in plan.services], ["api", "web"])
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("remove", "old"), ("add", "api"), ("add", "web")])
        rooted = compile_plan(manifest(svc("jobs"), svc("api", "v1")), manifest(svc("jobs", "v2"), svc("api", "v2")), roots=("api",))
        self.assertEqual([(o.kind, o.name) for o in rooted.operations], [("update", "api")])
        body = json.loads(render_plan(compile_plan(manifest(), manifest(svc("api")))))
        digest = body.pop("digest")
        payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(digest, "sha256:" + hashlib.sha256(payload).hexdigest())

    def test_09_p085_models_are_frozen(self):
        plan = compile_plan(manifest(), manifest(svc("api")))
        self.assertIsInstance(plan.services, tuple)
        with self.assertRaises(FrozenInstanceError):
            plan.digest = "other"
        with self.assertRaises(FrozenInstanceError):
            plan.operations[0].kind = "remove"


class ProfileOverlayTests(unittest.TestCase):
    def test_10_identity_profile_returns_dependency_order(self):
        base = manifest(svc("web", depends_on=["api"]), svc("api"))
        self.assertEqual(apply_profile(base, {"services": []}), (Service("api", "img:v1"), Service("web", "img:v1", ("api",))),)

    def test_11_existing_override_replaces_complete_fields(self):
        base = manifest(svc("api", "old", env={"A": "1", "B": "2"}, tags=["x"], replicas=2))
        result = apply_profile(base, {"services": [{"name": "API", "image": "new", "env": {"C": 3}, "replicas": 4}]})
        self.assertEqual(result[0], Service("api", "new", (), (("C", "3"),), ("x",), 4))

    def test_12_omitted_existing_fields_retain_values(self):
        base = manifest(svc("api", "old", depends_on=["db"], env={"A": "1"}, tags=["x"], replicas=2), svc("db"))
        result = apply_profile(base, {"services": [{"name": " api ", "image": "new"}]})
        self.assertEqual(result[0], Service("api", "new", ("db",), (("A", "1"),), ("x",), 2))

    def test_13_new_service_requires_image_and_uses_defaults(self):
        err_code(self, lambda: apply_profile(manifest(), {"services": [{"name": "api"}]}), "BAD_IMAGE", "services[0].image")
        result = apply_profile(manifest(), {"services": [{"name": "api", "image": "v1", "tags": ["x"]}]})
        self.assertEqual(result, (Service("api", "v1", (), (), ("x",), 1),))

    def test_14_remove_existing_service(self):
        result = apply_profile(manifest(svc("api"), svc("db")), {"services": [{"name": " API ", "remove": True}]})
        self.assertEqual(result, (Service("db", "img:v1"),))

    def test_15_overlay_order_and_mapping_order_are_semantically_irrelevant(self):
        left = apply_profile(manifest(svc("web", depends_on=["api"]), svc("api")), {"services": [{"name": "web", "image": "w2"}, {"name": "api", "image": "a2"}]})
        right = apply_profile(manifest(svc("api"), svc("web", depends_on=["api"])), {"services": [{"image": "a2", "name": " api "}, {"image": "w2", "name": "WEB"}]})
        self.assertEqual(left, right)

    def test_16_overlay_never_mutates_base_or_profile(self):
        base = manifest(svc("api", depends_on=["db"], env={"A": "1"}), svc("db"))
        profile = {"services": [{"name": "api", "env": {"B": "2"}}]}
        before_base, before_profile = json.loads(json.dumps(base)), json.loads(json.dumps(profile))
        apply_profile(base, profile)
        self.assertEqual((base, profile), (before_base, before_profile))

    def test_17_overlay_unknown_top_level_precedes_services_shape(self):
        err_code(self, lambda: apply_profile(manifest(), {"z": 1, "services": "bad"}), "UNKNOWN_FIELD", "z")
        err_code(self, lambda: apply_profile(manifest(), {"services": "bad"}), "BAD_PROFILE", "services")

    def test_18_overlay_shape_and_unknown_override_errors(self):
        err_code(self, lambda: apply_profile(manifest(), None), "BAD_PROFILE", "$")
        err_code(self, lambda: apply_profile(manifest(), {}), "BAD_PROFILE", "services")
        err_code(self, lambda: apply_profile(manifest(), {"services": [1]}), "BAD_OVERRIDE", "services[0]")
        err_code(self, lambda: apply_profile(manifest(), {"services": [{"name": "a", "z": 1}]}), "UNKNOWN_FIELD", "services[0].z")

    def test_19_overlay_duplicate_names_are_normalized(self):
        err_code(self, lambda: apply_profile(manifest(), {"services": [{"name": "API", "image": "a"}, {"name": " api ", "image": "b"}]}), "DUPLICATE_OVERRIDE", "services[1].name")

    def test_20_overlay_remove_rules_and_unknown_target(self):
        err_code(self, lambda: apply_profile(manifest(svc("api")), {"services": [{"name": "missing", "remove": True}]}), "UNKNOWN_OVERRIDE", "services[0].name")
        err_code(self, lambda: apply_profile(manifest(), {"services": [{"name": "api", "remove": "yes"}]}), "BAD_REMOVE", "services[0].remove")
        err_code(self, lambda: apply_profile(manifest(svc("api")), {"services": [{"name": "api", "remove": True, "image": "x"}]}), "BAD_REMOVE", "services[0].remove")

    def test_21_overlay_error_precedence_name_duplicate_remove_and_fields(self):
        err_code(self, lambda: apply_profile(manifest(), {"services": [{"image": "", "env": []}]}), "BAD_NAME", "services[0].name")
        err_code(self, lambda: apply_profile(manifest(svc("api")), {"services": [{"name": "api", "remove": False, "image": "", "depends_on": 2}]}), "BAD_IMAGE", "services[0].image")
        err_code(self, lambda: apply_profile(manifest(), {"services": [{"name": "api", "image": "v", "depends_on": 2, "env": []}]}), "BAD_DEPENDENCIES", "services[0].depends_on")

    def test_22_overlay_validates_all_service_fields_in_fixed_order(self):
        cases = [("depends_on", 2, "BAD_DEPENDENCIES"), ("env", [], "BAD_ENV"), ("tags", {}, "BAD_TAGS"), ("replicas", True, "BAD_REPLICAS")]
        for field, value, code in cases:
            with self.subTest(field=field):
                err_code(self, lambda field=field, value=value: apply_profile(manifest(svc("api")), {"services": [{"name": "api", field: value}]}), code, f"services[0].{field}")

    def test_23_overlay_validates_final_unknown_dependencies_and_cycles(self):
        err_code(self, lambda: apply_profile(manifest(svc("api")), {"services": [{"name": "api", "depends_on": ["missing"]}]}), "UNKNOWN_DEPENDENCY", "services.api.depends_on")
        base = manifest(svc("a"), svc("b"))
        err_code(self, lambda: apply_profile(base, {"services": [{"name": "a", "depends_on": ["b"]}, {"name": "b", "depends_on": ["a"]}]}), "DEPENDENCY_CYCLE")

    def test_24_new_override_order_is_semantically_irrelevant(self):
        base = manifest(svc("root"))
        left = apply_profile(base, {"services": [{"name": "z", "image": "z", "depends_on": ["root"]}, {"name": "a", "image": "a", "depends_on": ["root"]}]})
        right = apply_profile(base, {"services": [{"name": "a", "image": "a", "depends_on": ["root"]}, {"name": "z", "image": "z", "depends_on": ["root"]}]})
        self.assertEqual(left, right)


class ProfilePlanAndWaveTests(unittest.TestCase):
    def test_25_empty_profile_compiles_profiled_plan(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api")), {"services": []})
        self.assertIsInstance(plan, ProfiledPlan)
        self.assertEqual(plan.services, (Service("api", "img:v1"),))
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("add", "api")])
        self.assertEqual(plan.waves, ((plan.operations[0],),))

    def test_26_parallelism_requires_positive_non_boolean_integer(self):
        for value in (True, False, 0, -1, 1.5, "2"):
            with self.subTest(value=value):
                err_code(self, lambda value=value: compile_profiled_plan(manifest(), manifest(), {"services": []}, max_parallel=value), "BAD_PARALLELISM", "max_parallel")

    def test_27_removal_waves_remove_dependants_first(self):
        current = manifest(svc("web", depends_on=["api"]), svc("api"))
        plan = compile_profiled_plan(current, manifest(), {"services": []}, max_parallel=2)
        self.assertEqual([[o.name for o in wave] for wave in plan.waves], [["web"], ["api"]])

    def test_28_independent_removals_share_wave(self):
        current = manifest(svc("b"), svc("a"))
        plan = compile_profiled_plan(current, manifest(), {"services": []}, max_parallel=2)
        self.assertEqual([[o.name for o in wave] for wave in plan.waves], [["a", "b"]])

    def test_29_removal_waves_precede_all_forward_waves(self):
        current = manifest(svc("old"), svc("api", "v1"))
        desired = manifest(svc("api", "v2"), svc("new"))
        plan = compile_profiled_plan(current, desired, {"services": []}, max_parallel=2)
        self.assertEqual([[o.name for o in wave] for wave in plan.waves], [["old"], ["api", "new"]])
        kinds = [[o.kind for o in wave] for wave in plan.waves]
        self.assertEqual(kinds[0], ["remove"])
        self.assertTrue(all(kind != "remove" for wave in kinds[1:] for kind in wave))

    def test_30_forward_waves_respect_operated_dependency(self):
        current = manifest(svc("api", "v1"), svc("web", "v1", depends_on=["api"]))
        desired = manifest(svc("api", "v2"), svc("web", "v2", depends_on=["api"]))
        plan = compile_profiled_plan(current, desired, {"services": []}, max_parallel=2)
        self.assertEqual([[o.name for o in wave] for wave in plan.waves], [["api"], ["web"]])

    def test_31_independent_forward_operations_chunk_lexically(self):
        desired = manifest(svc("c"), svc("a"), svc("b"))
        plan = compile_profiled_plan(manifest(), desired, {"services": []}, max_parallel=2)
        self.assertEqual([[o.name for o in wave] for wave in plan.waves], [["a", "b"], ["c"]])

    def test_32_every_operation_is_in_exactly_one_wave_and_flattened(self):
        plan = compile_profiled_plan(manifest(svc("old")), manifest(svc("api"), svc("web", depends_on=["api"])), {"services": []}, max_parallel=1)
        self.assertEqual(tuple(op for wave in plan.waves for op in wave), plan.operations)
        self.assertEqual(sum(len(wave) for wave in plan.waves), len(plan.operations))

    def test_33_roots_close_after_overlay_and_preserve_unselected_current(self):
        current = manifest(svc("jobs"), svc("api", "v1"), svc("db"))
        desired = manifest(svc("jobs", "v2"), svc("api", "v1", depends_on=["db"]), svc("db"))
        plan = compile_profiled_plan(current, desired, {"services": []}, roots=("api",))
        self.assertEqual([s.name for s in plan.services], ["db", "api"])
        self.assertNotIn("jobs", [o.name for o in plan.operations])

    def test_34_roots_close_again_after_profile_changes_dependency(self):
        current = manifest(svc("api", "v1"))
        desired = manifest(svc("api", "v1"), svc("db"))
        profile = {"services": [{"name": "api", "depends_on": ["db"]}]}
        plan = compile_profiled_plan(current, desired, profile, roots=("api",))
        self.assertEqual([s.name for s in plan.services], ["db", "api"])
        self.assertEqual([(op.kind, op.name) for op in plan.operations], [("add", "db"), ("update", "api")])

    def test_35_overlay_graph_error_precedes_unknown_root(self):
        current = manifest(svc("api"))
        desired = manifest(svc("api"), svc("db"))
        profile = {"services": [{"name": "api", "depends_on": ["missing"]}]}
        err_code(self, lambda: compile_profiled_plan(current, desired, profile, roots=("missing-root",)), "UNKNOWN_DEPENDENCY")

    def test_36_unknown_root_is_checked_for_valid_overlay(self):
        err_code(self, lambda: compile_profiled_plan(manifest(), manifest(), {"services": []}, roots=("missing",)), "UNKNOWN_ROOT")

    def test_37_profiled_changes_propagate_restart_to_transitive_dependants(self):
        current = manifest(svc("api", "v1"), svc("mid", "v1", depends_on=["api"]), svc("web", "v1", depends_on=["mid"]))
        profile = {"services": [{"name": "api", "image": "v2"}]}
        plan = compile_profiled_plan(current, current, profile)
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("update", "api"), ("restart", "mid"), ("restart", "web")])
        self.assertEqual(plan.operations[1].before, plan.operations[1].after)

    def test_38_restart_is_not_added_for_already_changed_service(self):
        current = manifest(svc("api", "v1"), svc("web", "v1", depends_on=["api"]))
        desired = manifest(svc("api", "v2"), svc("web", "v2", depends_on=["api"]))
        plan = compile_profiled_plan(current, desired, {"services": []})
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("update", "api"), ("update", "web")])

    def test_39_multiple_changed_ancestors_yield_one_restart(self):
        current = manifest(svc("a", "v1"), svc("b", "v1"), svc("c", "v1", depends_on=["a", "b"]))
        profile = {"services": [{"name": "a", "image": "a2"}, {"name": "b", "image": "b2"}]}
        plan = compile_profiled_plan(current, current, profile)
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("update", "a"), ("update", "b"), ("restart", "c")])

    def test_40_restart_propagation_is_limited_to_selected_roots(self):
        current = manifest(svc("api", "v1"), svc("web", "v1", depends_on=["api"]), svc("jobs", "v1"))
        plan = compile_profiled_plan(current, current, {"services": [{"name": "api", "image": "v2"}]}, roots=("api",))
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("update", "api")])

    def test_41_operation_kinds_bind_expected_services(self):
        current = manifest(svc("old"), svc("api", "v1"))
        desired = manifest(svc("api", "v2"), svc("new"))
        plan = compile_profiled_plan(current, desired, {"services": []})
        kinds = {(op.kind, op.name): (op.before, op.after) for op in plan.operations}
        self.assertIsNotNone(kinds[("remove", "old")][0]); self.assertIsNone(kinds[("remove", "old")][1])
        self.assertIsNone(kinds[("add", "new")][0]); self.assertIsNotNone(kinds[("add", "new")][1])
        self.assertNotEqual(kinds[("update", "api")][0], kinds[("update", "api")][1])

    def test_42_plan_and_nested_models_are_frozen_tuples(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api")), {"services": []})
        self.assertIsInstance(plan.services, tuple); self.assertIsInstance(plan.operations, tuple); self.assertIsInstance(plan.waves, tuple)
        self.assertIsInstance(plan.waves[0], tuple)
        with self.assertRaises(FrozenInstanceError): plan.digest = "x"
        with self.assertRaises(FrozenInstanceError): plan.waves[0][0].name = "x"


class ProfileRenderingTests(unittest.TestCase):
    def test_43_render_has_canonical_top_level_and_complete_waves(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api")), {"services": []})
        rendered = render_profiled_plan(plan)
        self.assertTrue(rendered.endswith("\n"))
        body = json.loads(rendered)
        self.assertEqual(list(body), ["digest", "operations", "services", "waves"])
        self.assertEqual(list(body), sorted(body))
        self.assertEqual(body["waves"][0][0], body["operations"][0])
        self.assertEqual(list(body["services"][0]), sorted(body["services"][0]))
        self.assertEqual(list(body["operations"][0]), sorted(body["operations"][0]))
        self.assertEqual(list(body["waves"][0][0]), sorted(body["waves"][0][0]))
        self.assertNotIn(": ", rendered)
        self.assertNotIn(", ", rendered)
        self.assertEqual(rendered.count("\n"), 1)

    def test_44_render_recomputes_digest_from_plan_body(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api")), {"services": []})
        body = json.loads(render_profiled_plan(plan)); digest = body.pop("digest")
        payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(digest, "sha256:" + hashlib.sha256(payload).hexdigest())
        self.assertEqual(digest, plan.digest)

    def test_45_render_does_not_trust_stale_digest(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api")), {"services": []})
        stale = ProfiledPlan(plan.services, plan.operations, plan.waves, "sha256:stale")
        rendered = json.loads(render_profiled_plan(stale)); rendered.pop("digest")
        payload = json.dumps(rendered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(json.loads(render_profiled_plan(stale))["digest"], "sha256:" + hashlib.sha256(payload).hexdigest())

    def test_46_render_keeps_utf8_and_is_mapping_order_independent(self):
        left = compile_profiled_plan(manifest(), manifest(svc("api", env={"LABEL": "月"})), {"services": []})
        right = compile_profiled_plan(manifest(), {"services": [{"image": "img:v1", "name": "api", "env": {"LABEL": "月"}}]}, {"services": []})
        self.assertEqual(render_profiled_plan(left), render_profiled_plan(right))
        self.assertIn("月", render_profiled_plan(left))

    def test_47_rendered_operations_are_not_name_references(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api"), svc("web", depends_on=["api"])), {"services": []}, max_parallel=2)
        body = json.loads(render_profiled_plan(plan))
        self.assertIsInstance(body["waves"][0][0], dict)
        self.assertEqual(set(body["waves"][0][0]), {"after", "before", "kind", "name"})

    def test_48_rendered_service_and_operation_shapes_are_complete(self):
        plan = compile_profiled_plan(manifest(), manifest(svc("api", env={"A": 1}, tags=["x"], replicas=2)), {"services": []})
        body = json.loads(render_profiled_plan(plan))
        self.assertEqual(set(body["services"][0]), {"depends_on", "env", "image", "name", "replicas", "tags"})
        self.assertEqual(set(body["operations"][0]), {"after", "before", "kind", "name"})

    def test_49_public_exports_include_profiled_symbols(self):
        import benchmarks.p085_fixture.deployplan as package
        for name in ("apply_profile", "compile_profiled_plan", "render_profiled_plan", "ProfiledPlan", "compile_plan", "render_plan"):
            self.assertIn(name, package.__all__)
            self.assertTrue(hasattr(package, name))

    def test_50_parallelism_changes_waves_and_digest(self):
        desired = manifest(svc("a"), svc("b"), svc("c"))
        serial = compile_profiled_plan(manifest(), desired, {"services": []}, max_parallel=1)
        parallel = compile_profiled_plan(manifest(), desired, {"services": []}, max_parallel=2)
        self.assertNotEqual(serial.waves, parallel.waves)
        self.assertNotEqual(serial.digest, parallel.digest)


if __name__ == "__main__":
    unittest.main()
