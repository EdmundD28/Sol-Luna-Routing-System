from __future__ import annotations

import copy
import unittest

from benchmarks.p108_fixture.bomengine import BomError, BomResult, Component, NormalizedChange, evaluate_bom

def c(cid, version=1, quantity=1, depends_on=(), excludes=()):
    return {"id":cid,"version":version,"quantity":quantity,"depends_on":list(depends_on),"excludes":list(excludes)}

class BomCase(unittest.TestCase):
    def error(self, code, path, components, changes=()):
        with self.assertRaises(BomError) as caught: evaluate_bom(components, changes)
        self.assertEqual((caught.exception.code,caught.exception.path),(code,path))

class BasicTests(BomCase):
    def test_empty(self):
        self.assertEqual(evaluate_bom([],[]),BomResult((),(),(),(),()))

    def test_unchanged_graph_is_sorted_and_waved(self):
        result=evaluate_bom([c("C",depends_on=("B",)),c("A"),c("B",depends_on=("A",))],[])
        self.assertEqual(tuple(x.id for x in result.components),("A","B","C"))
        self.assertEqual(result.waves,(("A",),("B",),("C",)))
        self.assertEqual(result.impacted,())

    def test_quantity_and_version_changes_propagate_reverse_impact(self):
        raw=[c("A"),c("B",depends_on=("A",)),c("C",depends_on=("B",)),c("D")]
        result=evaluate_bom(raw,[{"kind":"set_quantity","source":"A","quantity":3},{"kind":"set_version","source":"D","version":2}])
        by={x.id:x for x in result.components}
        self.assertEqual((by["A"].quantity,by["D"].version),(3,2))
        self.assertEqual(result.impacted,("A","B","C","D"))
        self.assertEqual(result.changes,(NormalizedChange("set_quantity","A",None,3),NormalizedChange("set_version","D",None,2)))

    def test_inputs_and_outputs_are_detached_and_frozen(self):
        components=[c("A")]; changes=[{"kind":"set_version","source":"A","version":2}]
        before=(copy.deepcopy(components),copy.deepcopy(changes)); result=evaluate_bom(components,changes)
        self.assertEqual((components,changes),before)
        components[0]["version"]=9; self.assertEqual(result.components[0].version,2)
        with self.assertRaises(Exception): result.impacted += ()

class ChangeTests(BomCase):
    def test_replace_rewrites_dependencies_and_preserves_fields(self):
        result=evaluate_bom([c("A",2,4),c("B",depends_on=("A",))],[{"kind":"replace","source":"A","target":"X"}])
        by={x.id:x for x in result.components}
        self.assertEqual((by["X"].version,by["X"].quantity),(2,4)); self.assertEqual(by["B"].depends_on,("X",))
        self.assertEqual(result.impacted,("B","X")); self.assertEqual(result.removed,())

    def test_replace_version_override(self):
        result=evaluate_bom([c("A",2)],[{"kind":"replace","source":"A","target":"X","version":7}])
        self.assertEqual(result.components[0].version,7); self.assertEqual(result.changes[0].value,7)

    def test_swap_and_one_step_chain(self):
        swap=evaluate_bom([c("A",1),c("B",2)],[{"kind":"replace","source":"A","target":"B"},{"kind":"replace","source":"B","target":"A"}])
        self.assertEqual([(x.id,x.version) for x in swap.components],[('A',2),('B',1)])
        chain=evaluate_bom([c("A",1),c("B",2)],[{"kind":"replace","source":"A","target":"B"},{"kind":"replace","source":"B","target":"C"}])
        self.assertEqual([(x.id,x.version) for x in chain.components],[('B',1),('C',2)])

    def test_remove_unreferenced(self):
        result=evaluate_bom([c("A"),c("B")],[{"kind":"remove","source":"A"}])
        self.assertEqual(tuple(x.id for x in result.components),("B",)); self.assertEqual(result.removed,("A",)); self.assertEqual(result.impacted,())

    def test_remove_dependency_is_fatal(self):
        self.error("MISSING_DEPENDENCY",("final","B","depends_on",0),[c("A"),c("B",depends_on=("A",))],[{"kind":"remove","source":"A"}])

    def test_remove_excluded_component_drops_exclusion(self):
        result=evaluate_bom([c("A",excludes=("B",)),c("B")],[{"kind":"remove","source":"B"}])
        self.assertEqual(result.components[0].excludes,())

    def test_independent_change_order_is_equal(self):
        components=[c("A"),c("B")]
        one=[{"kind":"set_version","source":"B","version":2},{"kind":"set_quantity","source":"A","quantity":3}]
        self.assertEqual(evaluate_bom(components,one),evaluate_bom(list(reversed(components)),list(reversed(one))))

class ValidationTests(BomCase):
    def test_invalid_component_shapes(self):
        cases=[([1],"INVALID_TYPE",("components",0)),([{"id":"A"}],"MISSING_FIELD",("components",0,"version")),([c("bad")],"INVALID_ID",("components",0,"id")),([c("A",version=True)],"INVALID_INTEGER",("components",0,"version"))]
        for raw,code,path in cases:
            with self.subTest(code=code): self.error(code,path,raw)

    def test_duplicate_id(self):
        self.error("DUPLICATE_ID",("components",1,"id"),[c("A"),c("A")])

    def test_duplicate_dependency_and_exclusion_items(self):
        self.error("DUPLICATE_REFERENCE",("components",1,"depends_on",1),[c("A"),c("B",depends_on=("A","A"))])
        self.error("DUPLICATE_REFERENCE",("components",0,"excludes",1),[c("A",excludes=("B","B")),c("B")])

    def test_unknown_and_self_references(self):
        self.error("UNKNOWN_REFERENCE",("components",0,"depends_on",0),[c("A",depends_on=("Z",))])
        self.error("SELF_DEPENDENCY",("components",0,"depends_on",0),[c("A",depends_on=("A",))])
        self.error("SELF_EXCLUSION",("components",0,"excludes",0),[c("A",excludes=("A",))])

    def test_invalid_change_shapes(self):
        components=[c("A")]
        cases=[([1],"INVALID_TYPE",("changes",0)),([{"kind":"wat","source":"A"}],"INVALID_CHANGE",("changes",0,"kind")),([{"kind":"set_quantity","source":"A","quantity":0}],"INVALID_INTEGER",("changes",0,"quantity")),([{"kind":"replace","source":"A","target":"X","version":None}],"INVALID_INTEGER",("changes",0,"version"))]
        for raw,code,path in cases:
            with self.subTest(code=code): self.error(code,path,components,raw)

    def test_unknown_and_duplicate_change_source(self):
        self.error("UNKNOWN_SOURCE",("changes",0,"source"),[c("A")],[{"kind":"remove","source":"Z"}])
        self.error("DUPLICATE_CHANGE",("changes",1,"source"),[c("A")],[{"kind":"set_version","source":"A","version":2},{"kind":"remove","source":"A"}])

    def test_target_conflict_matrix(self):
        components=[c("A"),c("B"),c("C")]
        cases=[
          ([{"kind":"replace","source":"A","target":"C"}],0),
          ([{"kind":"replace","source":"A","target":"B"},{"kind":"remove","source":"B"}],0),
          ([{"kind":"replace","source":"A","target":"X"},{"kind":"replace","source":"B","target":"X"}],1)]
        for raw,index in cases:
            with self.subTest(raw=raw): self.error("TARGET_CONFLICT",("changes",index,"target"),components,raw)

    def test_exclusion_precedes_cycle(self):
        raw=[c("A",depends_on=("B",),excludes=("B",)),c("B",depends_on=("A",))]
        self.error("EXCLUSION_CONFLICT",("final","A","excludes",0),raw)

    def test_cycle(self):
        self.error("CYCLE",("final","depends_on"),[c("A",depends_on=("B",)),c("B",depends_on=("A",))])

class GraphTests(BomCase):
    def test_exclusion_is_symmetric_and_fatal(self):
        self.error("EXCLUSION_CONFLICT",("final","A","excludes",0),[c("A",excludes=("B",)),c("B")])

    def test_diamond_waves_and_impact(self):
        raw=[c("A"),c("B",depends_on=("A",)),c("C",depends_on=("A",)),c("D",depends_on=("B","C"))]
        result=evaluate_bom(raw,[{"kind":"set_version","source":"A","version":2}])
        self.assertEqual(result.waves,(("A",),("B","C"),("D",))); self.assertEqual(result.impacted,("A","B","C","D"))

    def test_dependency_and_component_order_do_not_matter(self):
        one=[c("A"),c("B"),c("C",depends_on=("B","A"))]
        two=[c("C",depends_on=("A","B")),c("B"),c("A")]
        self.assertEqual(evaluate_bom(one,[]),evaluate_bom(two,[]))

if __name__ == "__main__": unittest.main()
