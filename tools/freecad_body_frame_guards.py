"""Frame-specific refreshed attacks on qualifier-generated pure Body packets."""
import copy
import json
import re
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
from zipfile import ZipFile,ZIP_DEFLATED
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise


def source_opens(paths):
    """Count admitted source copies too, not only the publication's old path.

    Public verification stages the already admitted packet into a fresh private
    sources directory. This predicate matches the generic history qualifier's
    independently controlled source-open observation.
    """
    return [name for name in paths if Path(name).parent.name=='sources'
            and re.fullmatch(r'source[0-9]+\.FCStd',Path(name).name)]


def qualify(target,alternate,out):
    target=Path(target);out=Path(out);out.mkdir()
    source=target/'sources/source0.FCStd';native=target/'model.FCStd'
    originals={p:p.read_bytes() for p in target.iterdir() if p.is_file()};originals[source]=source.read_bytes()
    saved_plan=json.loads(originals[target/'plan.json']);records=json.loads(originals[target/'sources.json'])
    log=out/'opens.jsonl';report={'verified':False,'attacks':{},'opens':{}}
    def restore():
        for p,data in originals.items():p.write_bytes(data)
    def placement(path,name):
        with ZipFile(path) as z:members={n:z.read(n) for n in z.namelist()}
        xml=E.fromstring(members['Document.xml']);prop=xml.find("./ObjectData/Object[@name='"+name+"']/Properties/Property[@name='Placement']/PropertyPlacement")
        assert prop is not None
        prop.set('Px',format(float(prop.get('Px'))+.125,'.17g'))
        raw=members['Document.xml'];members['Document.xml']=raw[:raw.index(b'<Document ')]+E.tostring(xml,encoding='utf-8')
        with ZipFile(path,'w',ZIP_DEFLATED) as z:
            for n,data in members.items():z.writestr(n,data)
    original_call=SubprocessRunner.__call__
    def audit(self,code):
        prefix=('import FreeCAD as _a,json as _j,os as _o\n_original_open=_a.openDocument\n'
                'def _audited_open(*args,**kwargs):\n'
                ' name=str(args[0] if args else kwargs.get("FileName",""))\n'
                ' with open('+repr(str(log))+',"a") as s:s.write(_j.dumps({"path":name,"pid":_o.getpid()})+"\\n")\n'
                ' return _original_open(*args,**kwargs)\n_a.openDocument=_audited_open\n')
        return original_call(self,prefix+code)
    try:
        with patch.object(SubprocessRunner,'__call__',audit):
            assert registry.verify(target)['verified']
            positive=[json.loads(s)['path'] for s in log.read_text().splitlines()]
            observed=source_opens(positive)
            assert observed;report['unchangedSourceOpenControl']=True;report['unchangedSourceOpens']=observed
            for label in ('sourceBodyPlacement','sourceLocalFrame','equalMassRelocatedBore','copiedBodyPlacement'):
                restore();plan=copy.deepcopy(saved_plan)
                if label=='sourceBodyPlacement':placement(source,plan['parts'][0]['source']['body'])
                elif label=='sourceLocalFrame':plan['parts'][0]['source']['sourceFrame']='world'
                elif label=='equalMassRelocatedBore':source.write_bytes(Path(alternate).read_bytes())
                else:
                    renames=json.loads(originals[target/'built.json'])['renames']
                    placement(native,renames['parametered'][plan['parts'][0]['source']['body']])
                if label=='copiedBodyPlacement':
                    receipt=json.loads(originals[target/'verification.json'])
                    receipt['artifact']['sha256']=file_digest(native);receipt['artifacts']=[receipt['artifact']]
                    atomic_json(target/'verification.json',receipt)
                else:
                    facts=plan['parts'][0]['source'];facts['sha256']=file_digest(source);facts['bytes']=source.stat().st_size
                    with ZipFile(source) as z:facts['expandedBytes']=sum(i.file_size for i in z.infolist())
                    atomic_json(target/'plan.json',plan);changed=copy.deepcopy(records)
                    changed['parametered']['sha256']=facts['sha256'];atomic_json(target/'sources.json',changed)
                finalise(target);log.unlink(missing_ok=True)
                try:registry.verify(target)
                except SchemaxisError as error:
                    assert error.fault.code in ('VERIFICATION_FAILED','UNSUPPORTED_SOURCE'),error.fault
                    assert 'metadata' not in error.fault.message.lower(),error.fault
                    report['attacks'][label]=error.fault.to_dict()
                else:raise AssertionError(label+' accepted')
                opened=[json.loads(s)['path'] for s in log.read_text().splitlines()] if log.exists() else []
                assert str(native) not in opened
                if label!='copiedBodyPlacement':assert not source_opens(opened),(label,opened)
                report['opens'][label]=opened
                (out/(label+'.FCStd')).write_bytes((native if label=='copiedBodyPlacement' else source).read_bytes())
                atomic_json(out/(label+'-plan.json'),plan);atomic_json(out/'report.json',report)
            restore();assert registry.verify(target)['verified'];report['verified']=True
    finally:restore();atomic_json(out/'report.json',report)
    return report
