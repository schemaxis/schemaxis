#!/usr/bin/env python3
"""Independent native electrical identities, finite requirements and tamper gates."""
import argparse
import copy
import json
import math
from pathlib import Path

from schemaxis import workflow
from schemaxis.adaptors.ngspice import adaptor
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise
from schemaxis.tabular import read_csv

ROOT=Path(__file__).resolve().parents[1]


def failure(callback,code):
    try:callback()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.code
    raise AssertionError('expected '+code)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True);parser.add_argument('--output-directory',type=Path,required=True)
    args=parser.parse_args();root=args.output_directory.absolute();root.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'scope':'Finite ideal linear AC characterisation; native input current; derived branch currents/powers/impedance; no continuous-envelope or general SPICE claim.','accepted':{},'negative':{}}
    def example(name):return json.loads((ROOT/f'examples/schemaxis/ngspice-{name}.json').read_text())
    def run(name,doc):
        output=root/name;adaptor.run(doc,output,executable=args.executable,timeout=60)
        assert adaptor.verify(output)['verified'];table=read_csv(output/'results.csv')
        records=[dict(zip(table['columns'],row)) for row in table['rows']]
        report['accepted'][name]={'samples':len(records),'first':records[0],'last':records[-1]}
        return output,records
    for name in ('filter-characterisation','resonator-power','octave-filter'):
        doc=example(name);output,records=run(name,doc)
        for row in records:
            f=row['frequency_Hz'];w=2*math.pi*f;factor=.5 if doc['amplitudeConvention']=='peak' else 1
            # Series RC/RLC impedance formula, independent of host nodal stamps.
            z=1000+1/(1j*w*1e-6)+(1j*w if name=='resonator-power' else 0)
            i=doc['amplitude']/z;observed=complex(row['$input_current_real_A'],row['$input_current_imag_A'])
            assert abs(observed-i)<=1e-10*abs(i)
            assert abs(complex(row['$input_impedance_real_Ohm'],row['$input_impedance_imag_Ohm'])-z)<=1e-9*abs(z)
            expected=factor*doc['amplitude']*i.conjugate()
            assert abs(complex(row['$input_activePower_W'],row['$input_reactivePower_var'])-expected)<1e-12
            powers=sum((complex(row[branch+'_activePower_W'],row[branch+'_reactivePower_var']) for branch in doc['circuit']['branchProbes']),0j)
            assert abs(powers-expected)<1e-12
        if name=='octave-filter':assert len(records)==13 and math.isclose(records[-1]['frequency_Hz'],800)
    # Actual partial decade, decade redistribution and octave bounds vary grid.
    for spacing,start,stop,density,count in [('decade',10,23,10,4),('decade',10,3700,5,13),('octave',100,350,3,6)]:
        doc=example('filter-characterisation');doc.pop('requirements');doc.update(spacing=spacing,start=start,stop=stop,points=density)
        _,records=run(f'{spacing}-{start}-{stop}',doc);assert len(records)==count
    for convention,amplitude in [('rms',-2),('peak',2)]:
        doc=example('filter-characterisation');doc.pop('requirements');doc.update(amplitudeConvention=convention,amplitude=amplitude)
        _,records=run(f'{convention}-signed',doc)
        assert math.isclose(records[0]['$input_activePower_W'],.00025*amplitude**2*(2 if convention=='rms' else 1),rel_tol=1e-10)
    doc=example('filter-characterisation');doc['circuit']['capacitors'][0]['capacitance']=2e-6
    report['negative']['changedComponentUnmet']=failure(lambda:adaptor.run(doc,root/'unmet',executable=args.executable),'PERFORMANCE_NOT_MET')
    # Tiny amplitude/high impedance is a valid supported linear observation.
    # Relative checks must reject 2x and zero current after refreshing digests.
    doc=example('filter-characterisation');doc.pop('requirements');doc.update(amplitude=1e-15)
    doc['circuit']['resistors'][0]['resistance']=1e9
    doc['circuit']['capacitors'][0]['capacitance']=1e-12
    output,records=run('tiny-high-impedance',doc)
    native=output/'native.dat';original=native.read_bytes();receipt=(output/'verification.json').read_bytes()
    for scale in (2,0):
        lines=original.decode().splitlines();rows=[line.split() for line in lines[1:]]
        for row in rows:row[-2:]=[str(float(value)*scale) for value in row[-2:]]
        native.write_text(lines[0]+'\n'+'\n'.join(' '.join(row) for row in rows)+'\n')
        v=json.loads(receipt);v['evidence']['native.dat']=file_digest(native);atomic_json(output/'verification.json',v);finalise(output)
        report['negative']['tinySourceCurrentFactor'+str(scale)]=failure(lambda:adaptor.verify(output),'VERIFICATION_FAILED')
        native.write_bytes(original);(output/'verification.json').write_bytes(receipt);finalise(output)
    assert adaptor.verify(output)['verified']
    # A valid phase requirement on tiny voltages is still normalised accurately.
    doc=example('filter-characterisation');doc.update(amplitude=1e-15)
    doc['requirements']=doc['requirements'][:2]
    output,_=run('tiny-phase',doc);native=output/'native.dat';original=native.read_bytes()
    lines=original.decode().splitlines();rows=[line.split() for line in lines[1:]]
    # Node order is in,out; corrupt unselected source? Corrupt output only.
    for row in rows:row[3]=str(float(row[3])*2)
    native.write_text(lines[0]+'\n'+'\n'.join(' '.join(row) for row in rows)+'\n')
    receipt=json.loads((output/'verification.json').read_text());receipt['evidence']['native.dat']=file_digest(native)
    atomic_json(output/'verification.json',receipt);finalise(output)
    report['negative']['tinyTransferVoltage']=failure(lambda:adaptor.verify(output),'VERIFICATION_FAILED')
    native.write_bytes(original);receipt['evidence']['native.dat']=file_digest(native);atomic_json(output/'verification.json',receipt);finalise(output)
    assert adaptor.verify(output)['verified']
    doc={'version':'schemaxis.workflow/1','operations':[{'id':'electrical','document':example('filter-characterisation')}]}
    output=root/'workflow';workflow.execute(doc,output,locations={'ngspice':args.executable},timeout=60)
    assert workflow.verify(output)['verified']
    result=workflow.execute(doc,output,locations={'ngspice':args.executable},timeout=60,resume=True)
    assert all(job['reused'] for job in result['jobs']);report['workflowReuse']=True
    report['verified']=True;atomic_json(root/'qualification.json',report);print(json.dumps({'verified':True,'accepted':len(report['accepted']),'negative':report['negative'],'workflowReuse':True}))


if __name__=='__main__':main()
