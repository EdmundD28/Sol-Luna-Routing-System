"""Independent public acceptance for the P109 policy evaluator."""
import copy
import unittest

from policyengine import Decision, PolicyError, evaluate_access


def rule(rule_id="R_ALLOW", effect="allow", priority=10, **overrides):
    value = {
        "id": rule_id, "effect": effect, "priority": priority,
        "subject": {"ids": [], "roles": [], "groups": []},
        "resource": {"ids": [], "kinds": [], "tags": {}},
        "actions": ["document:read"], "when": None,
    }
    value.update(overrides)
    return value


def request(action="document:read", **overrides):
    value = {
        "subject": {"id": "USER_1", "roles": ["admin"], "groups": ["engineering"], "attrs": {"department": "eng"}},
        "resource": {"id": "DOC_1", "kind": "document", "tags": {"classification": "internal"}, "attrs": {"owner": "USER_1"}},
        "action": action, "context": {"ip": "10.0.0.1"},
    }
    value.update(overrides)
    return value


class PublicAcceptance(unittest.TestCase):
    def test_default_deny_and_exact_allow(self):
        self.assertEqual(evaluate_access([], request()).effect, "deny")
        self.assertEqual(evaluate_access([rule()], request()).winner, "R_ALLOW")

    def test_each_subject_dimension_and_wildcards(self):
        for field, selected, req in (("ids", ["USER_1"], request()), ("roles", ["admin"], request()), ("groups", ["engineering"], request())):
            with self.subTest(field=field):
                self.assertEqual(evaluate_access([rule(subject={"ids": selected if field == "ids" else [], "roles": selected if field == "roles" else [], "groups": selected if field == "groups" else []})], req).effect, "allow")
        self.assertEqual(evaluate_access([rule(subject={"ids": ["USER_2"], "roles": [], "groups": []})], request()).effect, "deny")

    def test_each_resource_dimension_tags_and_wildcards(self):
        self.assertEqual(evaluate_access([rule(resource={"ids": ["DOC_1"], "kinds": [], "tags": {}})], request()).effect, "allow")
        self.assertEqual(evaluate_access([rule(resource={"ids": [], "kinds": ["document"], "tags": {}})], request()).effect, "allow")
        self.assertEqual(evaluate_access([rule(resource={"ids": [], "kinds": [], "tags": {"classification": ["internal"]}})], request()).effect, "allow")
        self.assertEqual(evaluate_access([rule(resource={"ids": [], "kinds": ["image"], "tags": {}})], request()).effect, "deny")

    def test_exact_prefix_and_star_actions(self):
        for pattern, action in (("document:read", "document:read"), ("document:read:*", "document:read:own"), ("*", "anything:write")):
            with self.subTest(pattern=pattern):
                self.assertEqual(evaluate_access([rule(actions=[pattern])], request(action)).effect, "allow")
        self.assertEqual(evaluate_access([rule(actions=["document:read:*"])], request("document:reader")).effect, "deny")

    def test_all_leaf_operators(self):
        cases = [("eq", "eng", True), ("ne", "sales", True), ("in", ["eng", "sales"], True), ("not_in", ["sales"], True), ("contains", "en", True), ("lt", 6, True), ("le", 5, True), ("gt", 1, True), ("ge", 5, True), ("exists", None, True)]
        for op, value, expected in cases:
            condition = {"path": ["subject", "attrs", "department"] if op not in ("lt", "le", "gt", "ge") else ["context", "count"], "op": op}
            if op != "exists": condition["value"] = value
            req = request(context={"ip": "10.0.0.1", "count": 5})
            decision = evaluate_access([rule(when=condition)], req)
            self.assertEqual(decision.effect == "allow", expected, op)

    def test_missing_path_is_false_except_exists(self):
        for op in ("eq", "ne", "in", "not_in", "contains", "lt", "le", "gt", "ge"):
            value = [1] if op in ("in", "not_in") else "x"
            condition = {"path": ["context", "missing"], "op": op, "value": value}
            self.assertEqual(evaluate_access([rule(when=condition)], request()).effect, "deny")
        condition = {"path": ["context", "missing"], "op": "exists"}
        self.assertEqual(evaluate_access([rule(when=condition)], request()).effect, "deny")

    def test_recursive_conditions_and_short_circuit_equivalence(self):
        c = {"all": [{"path": ["context", "ip"], "op": "exists"}, {"not": {"path": ["context", "missing"], "op": "exists"}}]}
        left = {"any": [c, {"path": ["context", "ip"], "op": "eq", "value": "never"}]}
        right = {"any": [{"path": ["context", "ip"], "op": "eq", "value": "never"}, c]}
        self.assertEqual(evaluate_access([rule(when=c)], request()).effect, "allow")
        self.assertEqual(evaluate_access([rule(when=left)], request()),
                         evaluate_access([rule(when=right)], request()))

    def test_priority_precedes_specificity(self):
        self.assertEqual(evaluate_access([rule("A", priority=2), rule("Z", effect="deny", priority=3, subject={"ids": ["USER_1"], "roles": [], "groups": []})], request()).winner, "Z")

    def test_every_specificity_component(self):
        cases = (
            (rule("A"), rule("Z", subject={"ids": ["USER_1"], "roles": [], "groups": []}), request()),
            (rule("A"), rule("Z", resource={"ids": ["DOC_1"], "kinds": [], "tags": {}}), request()),
            (rule("A", actions=["*"]), rule("Z", actions=["document:read"]), request()),
            (rule("A", actions=["document:*"]), rule("Z", actions=["document:read:*"]), request("document:read:own")),
            (rule("A"), rule("Z", resource={"ids": [], "kinds": ["document"], "tags": {}}), request()),
            (rule("A"), rule("Z", resource={"ids": [], "kinds": [], "tags": {"classification": ["internal"]}}), request()),
            (rule("A"), rule("Z", subject={"ids": [], "roles": ["admin"], "groups": []}), request()),
            (rule("A"), rule("Z", subject={"ids": [], "roles": [], "groups": ["engineering"]}), request()),
            (rule("A"), rule("Z", when={"path": ["context", "ip"], "op": "exists"}), request()),
        )
        for index, (broad, specific, req) in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(evaluate_access([broad, specific], req).winner, "Z")

    def test_counted_specificity_components_are_not_booleans(self):
        tagged_request = request(resource={
            "id": "DOC_1", "kind": "document",
            "tags": {"classification": "internal", "env": "prod"},
            "attrs": {"owner": "USER_1"},
        })
        one_tag = rule("A", resource={"ids": [], "kinds": [],
                                      "tags": {"classification": ["internal"]}})
        two_tags = rule("Z", resource={"ids": [], "kinds": [],
                                       "tags": {"classification": ["internal"], "env": ["prod"]}})
        self.assertEqual(evaluate_access([one_tag, two_tags], tagged_request).winner, "Z")

        leaf = {"path": ["context", "ip"], "op": "exists"}
        one_node = rule("A", when=leaf)
        three_nodes = rule("Z", when={"all": [
            leaf,
            {"path": ["subject", "attrs", "department"], "op": "eq", "value": "eng"},
        ]})
        self.assertEqual(evaluate_access([one_node, three_nodes], request()).winner, "Z")

    def test_deny_override_lexical_winner_and_decisive_retention(self):
        rules = [rule("Z", effect="allow"), rule("A", effect="deny")]
        decision = evaluate_access(rules, request())
        self.assertEqual((decision.effect, decision.winner, decision.reason), ("deny", "A", "explicit_deny"))
        self.assertEqual(decision.decisive, ("A", "Z"))

    def test_frozen_detached_records_and_input_immutability(self):
        raw_rules, raw_request = [rule()], request()
        before = (copy.deepcopy(raw_rules), copy.deepcopy(raw_request))
        result = evaluate_access(raw_rules, raw_request)
        self.assertIsInstance(result, Decision)
        self.assertEqual((raw_rules, raw_request), before)
        with self.assertRaises((AttributeError, TypeError)): result.effect = "deny"

    def test_reordering_invariance_and_membership_order(self):
        a = rule("A", when={"path": ["context", "ip"], "op": "in", "value": ["10.0.0.1", "10.0.0.2"]})
        b = copy.deepcopy(a); b["when"]["value"] = ["10.0.0.2", "10.0.0.1"]
        self.assertEqual(evaluate_access([a], request()), evaluate_access([b], request()))

    def test_when_none_differs_from_eq_none(self):
        self.assertEqual(evaluate_access([rule()], request()).effect, "allow")
        self.assertEqual(evaluate_access([rule(when={"path": ["context", "absent"], "op": "eq", "value": None})], request()).effect, "deny")

    def test_error_codes_and_representative_paths(self):
        bad_name = rule(subject={"ids": [], "roles": ["Admin"], "groups": []})
        bad_scalar = rule(resource={"ids": [], "kinds": [], "tags": {"classification": [1.5]}})
        bad_membership = rule(when={"path": ["context", "x"], "op": "in", "value": [True, 1, True]})
        condition = {"path": ["context", "x"], "op": "exists"}
        for _ in range(8): condition = {"not": condition}
        cases = [
            ({}, "INVALID_TYPE", ("rules",)), ([{}], "MISSING_FIELD", ("rules", 0, "id")), ([rule(extra=1)], "UNKNOWN_FIELD", ("rules", 0, "extra")),
            ([rule("bad")], "INVALID_ID", ("rules", 0, "id")), ([rule(effect="bogus")], "INVALID_EFFECT", ("rules", 0, "effect")), ([bad_name], "INVALID_NAME", ("rules", 0, "subject", "roles", 0)),
            ([rule(priority=True)], "INVALID_INTEGER", ("rules", 0, "priority")), ([bad_scalar], "INVALID_SCALAR", ("rules", 0, "resource", "tags", "classification", 0)), ([rule("A"), rule("A")], "DUPLICATE_ID", ("rules", 1, "id")),
            ([bad_membership], "DUPLICATE_VALUE", ("rules", 0, "when", "value", 2)), ([rule(actions=[])], "INVALID_ACTION", ("rules", 0, "actions")), ([rule(when={})], "INVALID_CONDITION", ("rules", 0, "when")),
            ([rule(when={"path": ["bad", "x"], "op": "exists"})], "INVALID_PATH", ("rules", 0, "when", "path")), ([rule(when={"path": ["context", "x"], "op": "nope", "value": 1})], "INVALID_OPERATOR", ("rules", 0, "when", "op")),
            ([rule(when=condition)], "CONDITION_DEPTH", ("rules", 0, "when", "not", "not", "not", "not", "not", "not", "not", "not")),
            ([rule(when={"all": [{"path": ["context", "x"], "op": "exists"}] * 64})], "CONDITION_SIZE", ("rules", 0, "when", "all", 63)),
        ]
        for raw, code, path in cases:
            with self.subTest(code=code):
                with self.assertRaises(PolicyError) as caught: evaluate_access(raw, request())
                self.assertEqual((caught.exception.code, caught.exception.path), (code, path))

    def test_nested_unknown_and_missing_fields(self):
        bad = rule(); del bad["subject"]["ids"]
        with self.assertRaises(PolicyError) as caught: evaluate_access([bad], request())
        self.assertEqual(caught.exception.path, ("rules", 0, "subject", "ids"))

    def test_request_nested_missing_unknown_and_duplicate_membership(self):
        req = request(); del req["subject"]["attrs"]
        with self.assertRaises(PolicyError) as caught: evaluate_access([], req)
        self.assertEqual(caught.exception.path, ("request", "subject", "attrs"))
        req = request(); req["resource"]["extra"] = 1
        with self.assertRaises(PolicyError) as caught: evaluate_access([], req)
        self.assertEqual(caught.exception.path, ("request", "resource", "extra"))
        bad = rule(when={"path": ["context", "x"], "op": "in", "value": [True, 1, True]})
        with self.assertRaises(PolicyError) as caught: evaluate_access([bad], request())
        self.assertEqual(caught.exception.path, ("rules", 0, "when", "value", 2))

    def test_deep_attributes_missing_intermediate_and_invalid_key(self):
        req = request(
            subject={"id": "USER_1", "roles": ["admin"], "groups": ["engineering"],
                     "attrs": {"profile": {"department": "eng"}}},
            context={"network": {"region": "au"}},
        )
        condition = {"all": [
            {"path": ["context", "network", "region"], "op": "eq", "value": "au"},
            {"path": ["subject", "attrs", "profile", "department"], "op": "eq", "value": "eng"},
        ]}
        self.assertEqual(evaluate_access([rule(when=condition)], req).effect, "allow")
        missing = {"path": ["context", "network", "country", "code"], "op": "ne", "value": "nz"}
        self.assertEqual(evaluate_access([rule(when=missing)], req).effect, "deny")
        bad = copy.deepcopy(req)
        bad["context"]["Bad"] = 1
        with self.assertRaises(PolicyError) as caught:
            evaluate_access([], bad)
        self.assertEqual((caught.exception.code, caught.exception.path),
                         ("INVALID_NAME", ("request", "context", "Bad")))

    def test_depth_nine_and_node_sixty_five(self):
        condition = {"path": ["context", "x"], "op": "exists"}
        for _ in range(8): condition = {"not": condition}
        with self.assertRaises(PolicyError) as caught: evaluate_access([rule(when=condition)], request())
        self.assertEqual(caught.exception.code, "CONDITION_DEPTH")
        many = {"all": [{"path": ["context", "x"], "op": "exists"}] * 64}
        with self.assertRaises(PolicyError) as caught: evaluate_access([rule(when=many)], request())
        self.assertEqual(caught.exception.code, "CONDITION_SIZE")


if __name__ == "__main__": unittest.main()
