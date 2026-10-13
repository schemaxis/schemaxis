"""Benchmark isolation, case reuse and independent artifact falsification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import benchmark_workflows as b
from benchmark_grading import mesh_check


class WorkflowBenchmarkTests(unittest.TestCase):
    def spec(self):return json.loads((ROOT/'examples/benchmarks/cases.json').read_text())

    def test_manifest_bounds_and_identifiers(self):
        original=self.spec();b.validate(original)
        for key,value in [('id','../escape'),('inductance',float('nan')),('points',True),('amplitude',0)]:
            bad=copy.deepcopy(original);bad['rounds']['initial'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):b.validate(bad)
        bad=copy.deepcopy(original);bad['rounds']['initial'].append(bad['rounds']['initial'][0])
        with self.assertRaises(ValueError):b.validate(bad)

    def test_fresh_packages_equal_inputs_and_separate_arm_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=b.prepare(self.spec(),root/'package')
            hashes=[]
            for arm in ('ordinary','schemaxis'):
                target=root/arm;b.stage(package,'initial',arm,target)
                task=json.loads((target/'task.json').read_text());hashes.append(b.task_digest(task))
                self.assertNotIn('revision', [p.name for p in target.iterdir()])
                self.assertEqual((target/'templates').exists(),arm=='schemaxis')
                self.assertEqual(json.loads((target/'trial-record.json').read_text())['status'],'not-run')
            self.assertEqual(*hashes)
            task=json.loads((root/'ordinary/task.json').read_text())
            (Path(task['inputs'])/'table-a/input.csv').write_text('changed')
            self.assertNotEqual(b.task_digest(task),hashes[0])

    def test_materialised_inputs_and_existing_planning_boundary(self):
        from schemaxis import workflow
        with tempfile.TemporaryDirectory() as temp:
            root=b.prepare(self.spec(),Path(temp)/'pack')
            for round_name in ('initial','revision'):
                for case in self.spec()['rounds'][round_name]:
                    before=copy.deepcopy(case);doc=b.materialise(case,root/round_name/'inputs')
                    with self.subTest(round=round_name,case=case['id']):
                        if case['family']=='mesh':
                            # Future STEP publications retain their references;
                            # input-specific validation awaits verified receipts.
                            prepared=workflow.inspect_plan(doc)
                            deferred=[op for op in prepared['operations']
                                      if op['provisionalPlan'].get('status')=='deferred']
                            self.assertTrue(deferred)
                            self.assertTrue(all(op['provisionalPlan']['references'] for op in deferred))
                            self.assertNotIn('/unresolved-artifact',json.dumps(prepared))
                        else:workflow.inspect_plan(doc)
                    self.assertEqual(case,before)
            a=self.spec()['rounds']['initial'][0];c=copy.deepcopy(a);c['id']='repurposed';c['inductance']=3
            doc=b.materialise(c,root/'initial/inputs')
            self.assertEqual(doc['operations'][0]['document']['circuit']['inductors'][0]['inductance'],3)

    def test_table_grader_rejects_claims_missing_rows_and_wrong_workbook(self):
        case=next(c for c in self.spec()['rounds']['initial'] if c['family']=='table')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);submission=root/'submission';target=submission/case['id'];target.mkdir(parents=True)
            b.csv_write(target/'results.csv',case['columns'],case['rows'])
            # Minimal ODS content: an independent fixture, not adaptor output.
            rows=[case['columns']]+case['rows'];xml='<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><table:table>'
            for row in rows:
                xml+='<table:table-row>'
                for v in row:
                    xml+=(f'<table:table-cell office:value-type="float" office:value="{v}"/>' if isinstance(v,(int,float)) else f'<table:table-cell office:value-type="string"><text:p>{v}</text:p></table:table-cell>')
                xml+='</table:table-row>'
            xml+='</table:table></office:document-content>'
            def workbook(text):
                with zipfile.ZipFile(target/'results.ods','w') as z:z.writestr('content.xml',text)
            workbook(xml)
            self.assertTrue(b.grade_case(case,target,{},root/'grade')['workbookReadback'])
            workbook(xml.replace('office:value="4"','office:value="400"'))
            with self.assertRaises(ValueError):b.grade_case(case,target,{},root/'bad-grade')
            workbook(xml);b.csv_write(target/'results.csv',case['columns'],case['rows'][:-1])
            with self.assertRaises(ValueError):b.grade_case(case,target,{},root/'bad-grade')
            (target/'result.json').write_text('{"verified": true}')
            task={'cases':[case],'inputs':str(root/'inputs')}
            report=b.grade(task,submission,{},root/'batch-grade');self.assertFalse(report['passed'])

    def test_analytic_fixture_provenance_and_independent_time_fields(self):
        case=next(c for c in self.spec()['rounds']['initial'] if c['family']=='cfd')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'case';b.make_foam(case,root)
            self.assertIn('not a solved flow',json.loads((root/'PROVENANCE.json').read_text())['origin'])
            self.assertNotEqual((root/'1/U').read_bytes(),(root/'2/U').read_bytes())
            self.assertEqual(len((root/'constant/polyMesh/neighbour').read_text().splitlines()),17)

    def test_independent_mesh_grader_rejects_tags_and_missing_faces(self):
        with tempfile.TemporaryDirectory() as temp:
            points=[(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]
            tets=[(0,1,2,6),(0,2,3,6),(0,3,7,6),(0,7,4,6),(0,4,5,6),(0,5,1,6)]
            counts={}
            for t in tets:
                for ids in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
                    f=tuple(sorted(t[i] for i in ids));counts[f]=counts.get(f,0)+1
            faces=[f for f,n in counts.items() if n==1]
            elements=[]
            for f in faces:
                tag=3 if all(points[i][0]==0 for i in f) else 4 if all(points[i][0]==1 for i in f) else 2
                elements.append(f'{len(elements)+1} 2 2 {tag} 1 '+' '.join(str(i+1) for i in f))
            for t in tets:elements.append(f'{len(elements)+1} 4 2 1 1 '+' '.join(str(i+1) for i in t))
            text='$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$PhysicalNames\n4\n3 1 "part"\n2 2 "outside"\n2 3 "fixed"\n2 4 "loaded"\n$EndPhysicalNames\n$Nodes\n8\n'
            text+='\n'.join(str(i+1)+' '+' '.join(map(str,p)) for i,p in enumerate(points))+'\n$EndNodes\n$Elements\n18\n'+'\n'.join(elements)+'\n$EndElements\n'
            path=Path(temp)/'mesh.msh';path.write_text(text);case={'length':1,'width':1,'height':1}
            self.assertAlmostEqual(mesh_check(path,case)['volume'],1)
            for bad in (text.replace('2 2 3 1','2 2 2 1',1),text.replace(elements[0]+'\n','').replace('$Elements\n18','$Elements\n17')):
                path.write_text(bad)
                with self.assertRaises(ValueError):mesh_check(path,case)


if __name__=='__main__':unittest.main()
