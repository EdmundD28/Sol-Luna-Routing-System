from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from benchmarks.p085_fixture.deployplan import (
    ManifestError,
    compile_plan,
    dependency_closure,
    dependency_order,
    normalize_name,
    parse_manifest,
    render_plan,
)
from benchmarks.p085_fixture.deployplan.diff import diff_services
from benchmarks.p085_fixture.deployplan.model import Operation, Plan, Service


def manifest(*services: dict) -> dict:
    return {"services": list(services)}


def svc(name: str, image: str = "img:v1", **extra: object) -> dict:
    return {"name": name, "image": image, **extra}


class ErrorContractTests(unittest.TestCase):
    def test_A01_error_has_stable_fields_and_text(self):
        err = ManifestError("BAD_NAME", "services[2].name", "invalid")
        self.assertEqual((err.code, err.path, err.message), ("BAD_NAME", "services[2].name", "invalid"))
        self.assertEqual(str(err), "BAD_NAME@services[2].name: invalid")


class NormalizeTests(unittest.TestCase):
    def test_A02_name_is_trimmed_and_lowered(self):
        self.assertEqual(normalize_name("  Web-API  "), "web-api")

    def test_A03_name_rejects_type_empty_and_bad_characters(self):
        for value in (None, 3, "", "9api", "web_api", "web api"):
            with self.subTest(value=value):
                with self.assertRaises(ManifestError) as caught:
                    normalize_name(value)
                self.assertEqual(caught.exception.code, "BAD_NAME")

    def test_A04_manifest_normalizes_defaults_and_collections(self):
        parsed = parse_manifest(manifest(svc(" API ", depends_on=[" DB ", "db"], env={"Z": 2, "A": True}, tags=[" Blue ", "blue"]), svc("db")))
        self.assertEqual(parsed[0], Service("api", "img:v1", ("db",), (("A", "true"), ("Z", "2")), ("blue",), 1))

    def test_A05_manifest_input_is_not_mutated(self):
        raw = manifest(svc("api", depends_on=["db"], env={"A": "1"}), svc("db"))
        snapshot = json.loads(json.dumps(raw))
        parse_manifest(raw)
        self.assertEqual(raw, snapshot)

    def test_A06_duplicate_normalized_name_is_rejected(self):
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest(svc("API"), svc(" api ")))
        self.assertEqual(caught.exception.code, "DUPLICATE_SERVICE")

    def test_A07_unknown_keys_are_rejected_at_exact_path(self):
        with self.assertRaises(ManifestError) as caught:
            parse_manifest({"services": [svc("api", mystery=1)], "extra": 2})
        self.assertEqual(caught.exception.code, "UNKNOWN_FIELD")
        self.assertEqual(caught.exception.path, "extra")
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest(svc("api", mystery=1)))
        self.assertEqual((caught.exception.code, caught.exception.path), ("UNKNOWN_FIELD", "services[0].mystery"))

    def test_A08_image_must_be_nonempty_string(self):
        for image in (None, "", "   "):
            with self.subTest(image=image):
                with self.assertRaises(ManifestError) as caught:
                    parse_manifest(manifest(svc("api", image=image)))
                self.assertEqual(caught.exception.code, "BAD_IMAGE")
        self.assertEqual(parse_manifest(manifest(svc("api", image="  image:v1  ")))[0].image, "image:v1")

    def test_A09_replicas_reject_bool_negative_and_non_int(self):
        for replicas in (True, -1, 1.5, "2"):
            with self.subTest(replicas=replicas):
                with self.assertRaises(ManifestError) as caught:
                    parse_manifest(manifest(svc("api", replicas=replicas)))
                self.assertEqual(caught.exception.code, "BAD_REPLICAS")
        self.assertEqual(parse_manifest(manifest(svc("api", replicas=0)))[0].replicas, 0)

    def test_A10_environment_values_have_canonical_scalars(self):
        parsed = parse_manifest(manifest(svc("api", env={"S": "x", "I": 2, "F": 1.5, "ONE": 1.0, "NEGZERO": -0.0, "EXP": 1e+20, "T": True, "N": None})))
        self.assertEqual(parsed[0].env, (("EXP", "1e+20"), ("F", "1.5"), ("I", "2"), ("N", "null"), ("NEGZERO", "-0.0"), ("ONE", "1.0"), ("S", "x"), ("T", "true")))

    def test_A11_environment_rejects_container_value(self):
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(manifest(svc("api", env={"A": [1]})))
        self.assertEqual(caught.exception.code, "BAD_ENV")

    def test_A12_service_models_are_frozen(self):
        item = parse_manifest(manifest(svc("api")))[0]
        with self.assertRaises(FrozenInstanceError):
            item.image = "other"


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.services = parse_manifest(manifest(svc("web", depends_on=["api"]), svc("db"), svc("api", depends_on=["db"]), svc("jobs", depends_on=["db"])))

    def test_A13_dependency_order_is_stable_and_lexical(self):
        self.assertEqual([s.name for s in dependency_order(self.services)], ["db", "api", "jobs", "web"])

    def test_A14_unknown_dependency_is_rejected(self):
        items = parse_manifest(manifest(svc("api", depends_on=["missing"])))
        with self.assertRaises(ManifestError) as caught:
            dependency_order(items)
        self.assertEqual((caught.exception.code, caught.exception.path), ("UNKNOWN_DEPENDENCY", "services.api.depends_on"))

    def test_A15_self_dependency_is_a_cycle(self):
        items = parse_manifest(manifest(svc("api", depends_on=["api"])))
        with self.assertRaises(ManifestError) as caught:
            dependency_order(items)
        self.assertEqual(caught.exception.code, "DEPENDENCY_CYCLE")
        self.assertIn("api", caught.exception.message)

    def test_A16_multi_node_cycle_lists_members_stably(self):
        items = parse_manifest(manifest(svc("z", depends_on=["y"]), svc("b", depends_on=["a"]), svc("y", depends_on=["z"]), svc("a", depends_on=["b"]), svc("tail", depends_on=["a"])))
        with self.assertRaises(ManifestError) as caught:
            dependency_order(items)
        self.assertEqual(caught.exception.message, "a,b")

    def test_A17_closure_includes_transitive_dependencies(self):
        self.assertEqual([s.name for s in dependency_closure(self.services, ["web"])], ["db", "api", "web"])

    def test_A18_closure_deduplicates_normalized_roots(self):
        self.assertEqual([s.name for s in dependency_closure(self.services, [" WEB ", "web"])], ["db", "api", "web"])

    def test_A19_closure_unknown_root_is_rejected(self):
        with self.assertRaises(ManifestError) as caught:
            dependency_closure(self.services, ["missing"])
        self.assertEqual(caught.exception.code, "UNKNOWN_ROOT")


class DiffTests(unittest.TestCase):
    def test_A20_equal_services_produce_no_operations(self):
        items = parse_manifest(manifest(svc("api")))
        self.assertEqual(diff_services(items, items), ())

    def test_A21_adds_follow_dependency_order(self):
        desired = parse_manifest(manifest(svc("web", depends_on=["api"]), svc("api")))
        ops = diff_services((), desired)
        self.assertEqual([(o.kind, o.name) for o in ops], [("add", "api"), ("add", "web")])

    def test_A22_removes_reverse_dependency_order(self):
        current = parse_manifest(manifest(svc("web", depends_on=["api"]), svc("api")))
        ops = diff_services(current, ())
        self.assertEqual([(o.kind, o.name) for o in ops], [("remove", "web"), ("remove", "api")])

    def test_A23_updates_follow_desired_dependency_order(self):
        current = parse_manifest(manifest(svc("web", depends_on=["api"]), svc("api")))
        desired = parse_manifest(manifest(svc("web", "web:v2", depends_on=["api"]), svc("api", "api:v2")))
        ops = diff_services(current, desired)
        self.assertEqual([(o.kind, o.name) for o in ops], [("update", "api"), ("update", "web")])

    def test_A24_operation_binds_before_and_after(self):
        old = parse_manifest(manifest(svc("api", "v1")))[0]
        new = parse_manifest(manifest(svc("api", "v2")))[0]
        self.assertEqual(diff_services((old,), (new,)), (Operation("update", "api", old, new),))

    def test_A25_invalid_current_graph_is_rejected(self):
        current = parse_manifest(manifest(svc("api", depends_on=["missing"])))
        with self.assertRaises(ManifestError) as caught:
            diff_services(current, ())
        self.assertEqual(caught.exception.code, "UNKNOWN_DEPENDENCY")
        desired = parse_manifest(manifest(svc("web", depends_on=["absent"])))
        with self.assertRaises(ManifestError) as caught:
            diff_services((), desired)
        self.assertEqual(caught.exception.code, "UNKNOWN_DEPENDENCY")


class PlannerTests(unittest.TestCase):
    def test_A26_compile_orders_services_and_operations(self):
        current = manifest(svc("old"))
        desired = manifest(svc("web", depends_on=["api"]), svc("api"))
        plan = compile_plan(current, desired)
        self.assertEqual([s.name for s in plan.services], ["api", "web"])
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("remove", "old"), ("add", "api"), ("add", "web")])

    def test_A27_roots_select_dependency_closed_desired_subset(self):
        desired = manifest(svc("web", depends_on=["api"]), svc("api", depends_on=["db"]), svc("db"), svc("jobs", depends_on=["db"]))
        plan = compile_plan(manifest(), desired, roots=("web",))
        self.assertEqual([s.name for s in plan.services], ["db", "api", "web"])
        self.assertEqual([o.name for o in plan.operations], ["db", "api", "web"])

    def test_A28_roots_do_not_remove_unselected_current_services(self):
        current = manifest(svc("jobs"), svc("api", "v1"))
        desired = manifest(svc("jobs", "v2"), svc("api", "v2"))
        plan = compile_plan(current, desired, roots=("api",))
        self.assertEqual([(o.kind, o.name) for o in plan.operations], [("update", "api")])

    def test_A29_render_is_canonical_and_has_trailing_newline(self):
        plan = compile_plan(manifest(), manifest(svc("api", env={"Z": 2, "A": 1})))
        rendered = render_plan(plan)
        self.assertTrue(rendered.endswith("\n"))
        body = json.loads(rendered)
        self.assertEqual(list(body), ["digest", "operations", "services"])
        self.assertEqual(list(body["services"][0]), ["depends_on", "env", "image", "name", "replicas", "tags"])
        self.assertEqual(body["services"][0]["env"], {"A": "1", "Z": "2"})
        self.assertEqual(list(body["operations"][0]), ["after", "before", "kind", "name"])
        self.assertIsNone(body["operations"][0]["before"])
        self.assertEqual(list(body["operations"][0]["after"]), ["depends_on", "env", "image", "name", "replicas", "tags"])

    def test_A30_digest_is_sha256_of_payload_without_digest(self):
        import hashlib

        plan = compile_plan(manifest(), manifest(svc("api")))
        body = json.loads(render_plan(plan))
        digest = body.pop("digest")
        payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(digest, "sha256:" + hashlib.sha256(payload).hexdigest())
        self.assertEqual(plan.digest, digest)

    def test_A31_semantically_equal_inputs_have_same_digest(self):
        left = compile_plan(manifest(), manifest(svc("API", tags=["B", "a"], env={"Z": 2, "A": 1})))
        right = compile_plan(manifest(), manifest(svc(" api ", tags=["a", "b"], env={"A": 1, "Z": 2})))
        self.assertEqual(left.digest, right.digest)

    def test_A32_unicode_is_not_ascii_escaped(self):
        plan = compile_plan(manifest(), manifest(svc("api", env={"LABEL": "月"})))
        self.assertIn("月", render_plan(plan))

    def test_A33_plan_and_operations_are_frozen(self):
        plan = compile_plan(manifest(), manifest(svc("api")))
        self.assertIsInstance(plan.services, tuple)
        self.assertIsInstance(plan.operations, tuple)
        with self.assertRaises(FrozenInstanceError):
            plan.digest = "other"
        with self.assertRaises(FrozenInstanceError):
            plan.operations[0].kind = "remove"


if __name__ == "__main__":
    unittest.main()
