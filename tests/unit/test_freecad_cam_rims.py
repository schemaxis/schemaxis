"""Native-independent adversarial endpoint graphs and aggregate admission."""
import math
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad.cam_mixed_budget import BooleanBudget,LIMITS
from schemaxis.adaptors.freecad.cam_rims_native import prospective,representative


class Vertex:
    def __init__(self,key):self.key=key
    def isSame(self,other):return self.key==other.key


class Edge:
    def __init__(self,key,a,b,length=math.pi):
        self.key=key;self.Vertexes=[Vertex(a),Vertex(b)];self.Length=length
    def isSame(self,other):return self.key==other.key
    def isClosed(self):return False
    def countElement(self,kind):return 2


class EmptyOverlap:
    def countElement(self,kind):return 0


class CompleteRims(unittest.TestCase):
    def run_group(self,group,intersection=lambda a,b:EmptyOverlap()):
        budget=BooleanBudget();prospective([group],budget,3)
        return representative(group,1,budget,intersection,'target')

    def test_cycle_uses_native_identity_not_coincident_endpoint_coordinates(self):
        group=[(12,Edge('a','north','south')),(4,Edge('b','south','north'))]
        self.assertEqual(self.run_group(group),4)
        # Different native identities must not be merged by their coordinates.
        group[1]=(4,Edge('b','south-copy','north-copy'))
        with self.assertRaises(SchemaxisError):self.run_group(group)

    def test_missing_duplicate_and_disconnected_coverage_refuse(self):
        first=Edge('a','a','b')
        groups=[[(1,first)],[(1,first),(2,first)],
                [(1,Edge('a','a','b',math.pi/2)),(2,Edge('b','b','a',math.pi/2)),
                 (3,Edge('c','c','d',math.pi/2)),(4,Edge('d','d','c',math.pi/2))]]
        for group in groups:
            with self.subTest(group=group),self.assertRaises(SchemaxisError):self.run_group(group)

    def test_positive_dimensional_overlap_refuses_despite_coherent_endpoints(self):
        class Overlap:
            def countElement(self,kind):return 1
        group=[(1,Edge('a','a','b')),(2,Edge('b','b','a'))]
        with self.assertRaises(SchemaxisError):self.run_group(group,lambda a,b:Overlap())

    def test_all_groups_reserve_overlap_budget_before_any_kernel(self):
        group=[(i,None) for i in range(64)]
        budget=BooleanBudget()
        prospective([group],budget,32) #2016+32 exactly2048
        with self.assertRaises(SchemaxisError):prospective([group,[(1,None),(2,None)]],budget,32)
        self.assertEqual(budget.operations,0)
        budget.identity_checks=LIMITS['facePairs']-1
        budget.check()
        with self.assertRaises(SchemaxisError):budget.check()
        self.assertEqual(budget.identity_checks,LIMITS['facePairs'])
