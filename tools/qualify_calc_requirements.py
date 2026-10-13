#!/usr/bin/env python3
"""Independent native Calc cell-bound/reconciliation and workflow acceptance."""
import argparse
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from schemaxis.adaptors.calc import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow import execute, verify

ROOT=Path(__file__).resolve().parents[1]


def independent_totals(directory):
    # This oracle reads literal cached totals directly, without the adaptor's
    # workbook parser, expected(), assessment, receipt or formula generator.
    with ZipFile(directory/'analysis.xlsx') as archive:
        root=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
    namespace={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    actual={cell.get('r'):float(cell.findtext('s:v',namespaces=namespace))
            for cell in root.findall('.//s:c',namespace) if cell.get('r') in ('C2','C3')}
    if actual!={'C2':150,'C3':150}:raise AssertionError('independent XLSX totals differ')
    with ZipFile(directory/'analysis.ods') as archive:
        root=ET.fromstring(archive.read('content.xml'))
    ns={'t':'urn:oasis:names:tc:opendocument:xmlns:table:1.0','o':'urn:oasis:names:tc:opendocument:xmlns:office:1.0'}
    summary=next(sheet for sheet in root.findall('.//t:table',ns) if sheet.get('{'+ns['t']+'}name')=='Summary')
    rows=summary.findall('t:table-row',ns)
    for row in rows[1:3]:
        if float(row.findall('t:table-cell',ns)[2].get('{'+ns['o']+'}value'))!=150:
            raise AssertionError('independent reopened ODS total differs')


def rejected(function,code=None):
    try:function()
    except SchemaxisError as error:
        if code is not None and error.fault.code!=code:raise
        return error.fault.to_dict()
    raise AssertionError('expected structured rejection')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--output-directory',required=True,type=Path)
    args=parser.parse_args();directory=args.output_directory.absolute();directory.mkdir(parents=True,exist_ok=False)
    executable=str(args.executable.absolute())
    document=json.loads((ROOT/'examples/schemaxis/calc-balance.json').read_text())
    results=[]
    for name,requirements in [('balanced',document['requirements']),('exact-cell-boundary',[
        {'name':'first-income','type':'cellBounds','cell':{'sheet':'Data','cell':'A2'},'minimum':100,'maximum':100}]),
        ('explicit-coefficients',[{'name':'weighted','type':'reconcile','terms':[
            {'sheet':'Data','cell':'A2','coefficient':2},{'sheet':'Data','cell':'B2','coefficient':-1}],
            'target':130,'absoluteTolerance':0}])]:
        case=copy.deepcopy(document);case['requirements']=requirements;target=directory/name
        adaptor.run(case,target,executable=executable,timeout=60);adaptor.verify(target);independent_totals(target)
        assessment=json.loads((target/'requirements.json').read_text())
        if not assessment['passed'] or any(check['status']!='passed' for result in assessment['formats'].values() for check in result['checks']):
            raise AssertionError('native assessment differs')
        results.append({'case':name,'verified':True,'independentTotals':[150,150], 'runtime':json.loads((target/'runtime.json').read_text())['runtime']})
    target=directory/'balanced';tamper=[]
    path=target/'requirements.json';original=path.read_bytes()
    for payload in (b'null',b'{',b' '* (1024*1024+1)):
        path.write_bytes(payload);tamper.append(rejected(lambda:adaptor.verify(target)))
    path.write_bytes(original)
    mutated=json.loads(original);mutated['formats']['xlsx']['checks'][1]['value']=123
    path.write_text(json.dumps(mutated));tamper.append(rejected(lambda:adaptor.verify(target)));path.write_bytes(original)
    # Keep old cached numbers, change a fixed native formula; both verification
    # relationships must survive independently of the new requirement checks.
    path=target/'analysis.xlsx';original=path.read_bytes()
    with ZipFile(path) as archive:members={name:archive.read(name) for name in archive.namelist()}
    members['xl/worksheets/sheet2.xml']=members['xl/worksheets/sheet2.xml'].replace(b'SUM(',b'MAX(',1)
    with ZipFile(path,'w',ZIP_DEFLATED) as archive:
        for name,payload in members.items():archive.writestr(name,payload)
    tamper.append(rejected(lambda:adaptor.verify(target)));path.write_bytes(original);adaptor.verify(target)
    failures=[]
    for name,mutate,code in [('imbalance',lambda d:d['nodes'][0]['options']['rows'][1].__setitem__(1,85),'REQUIREMENTS_UNMET'),
                            ('missing',lambda d:d['requirements'][0]['cell'].update(cell='C65'),'REQUIREMENT_SELECTION_FAILED'),
                            ('nonnumeric',lambda d:d['requirements'][0]['cell'].update(cell='A1'),'REQUIREMENT_SELECTION_FAILED')]:
        case=copy.deepcopy(document);mutate(case);target=directory/name
        fault=rejected(lambda:adaptor.run(case,target,executable=executable,timeout=60),code)
        if not all((target/name).is_file() for name in ('analysis.xlsx','analysis.ods','requirements.json')):
            raise AssertionError('failed native assessment not retained')
        if (target/'verification.json').exists() or json.loads((target/'result.json').read_text())['verified']:
            raise AssertionError('unmet or invalid selection promoted to verified publication')
        failures.append({'case':name,'fault':fault,'nativeWorkbooksRetained':True})
    workflow={'version':'schemaxis.workflow/1','operations':[{'id':'producer','document':document},
        {'id':'consumer','document':{'version':'schemaxis.calc/1','nodes':[{'id':'imported','filter':'readCSV',
         'options':{'file':{'$artifact':'producer','index':2}}}],'requirements':document['requirements']}}]}
    target=directory/'workflow';execute(workflow,target,locations={'calc':executable},timeout=60);verify(target)
    resumed=execute(workflow,target,locations={'calc':executable},timeout=60,resume=True)
    if sum(bool(job.get('reused')) for job in resumed['jobs'])!=2:raise AssertionError('verified native assessment was not reused')
    failed=copy.deepcopy(workflow);failed['operations'][0]['document']['nodes'][0]['options']['rows'][1][1]=85
    target=directory/'failed-workflow';rejected(lambda:execute(failed,target,locations={'calc':executable},timeout=60),'REQUIREMENTS_UNMET')
    rejected(lambda:execute(failed,target,locations={'calc':executable},timeout=60,resume=True),'REQUIREMENTS_UNMET')
    status=json.loads((target/'result.json').read_text())
    if any(job['operation']=='consumer' for job in status['jobs']) or any(job.get('reused') for job in status['jobs']):
        raise AssertionError('unmet producer launched consumer or was reused')
    report={'verified':True,'provider':'calc','scope':'Three fixed-table native checks, both-format literal total readback, formula/assessment tamper rejection, unmet/missing/text conditions and blocked/reused CSV workflow. No general workbook, unit conversion or GUI claims.',
            'cases':results,'failures':failures,'tamper':tamper,'workflow':{'verified':True,'reusedJobs':2,'unmetBlocksConsumerAndReuse':True}}
    atomic_json(directory/'acceptance.json',report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
