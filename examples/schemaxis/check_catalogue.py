"""Independent analytic checks for the catalogue's bounded acceptance examples."""
import argparse
import csv
import json
from pathlib import Path


def check(mesh, table, extension):
    load=lambda path:json.loads((Path(path)/'verification.json').read_text())
    m,t,e=load(mesh),load(table),load(extension)
    assert all(r['verified'] and r['status']=='succeeded' for r in (m,t,e))
    obs=m['states'][0]['observations']
    assert obs['sphere']['points']==(24-2)*24+2
    assert obs['sphere']['cells']==2*24*(24-2)
    assert abs(obs['cut']['bounds'][0])<1e-6
    assert 1.9 < obs['cut']['bounds'][1] <= 2
    assert obs['cut']['cells'] == obs['shrink']['cells']
    assert obs['shrink']['points'] > obs['cut']['points']
    obs=t['states'][0]['observations']
    assert obs['table']['rows']==4
    assert obs['points']['points']==4
    assert obs['points']['bounds']==[0.,1.,0.,1.,0.,1.]
    artifact=next(a for a in t['artifacts'] if a['identity']['kind']=='measurement')
    with open(artifact['file']) as stream:
        rows=list(csv.DictReader(stream))
    for row,coordinates in zip(rows,[(0,0,0),(1,0,0),(0,1,0),(0,0,1)]):
        assert [float(row[k+'[0]']) for k in ('x','y','z')] == list(coordinates)
    assert len(rows)==4
    obs=e['states'][0]['observations']
    assert obs['source']['cells']==obs['result']['cells']
    assert obs['result']['points']==3*obs['result']['cells']
    assert obs['result']['bounds'][5] < obs['source']['bounds'][5]
    return {'verified':True,'checks':['sphere tessellation counts','positive half-space clip',
            'shrink preserves cells and separates vertices','four table coordinates and bounds',
            'numeric row CSV matches input','custom filter changes geometry and preserves cells']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('mesh','table','extension'): parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(check(args.mesh,args.table,args.extension),indent=2))
