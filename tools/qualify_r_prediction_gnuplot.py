#!/usr/bin/env python3
"""R prediction table to Gnuplot error-bar handoff: exact artifact edge, independent geometry, propagation and pre-native refusals."""
import argparse
import copy
import json
import math
from pathlib import Path

from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors.r import adaptor as r_adaptor
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[1]
SIGMA=math.sqrt(.05)
# Gnuplot adaptor layout, documented in docs/gnuplot.md: x 15-95 percent across, y 20-90 percent upward.
def pixel(value,low,high,start,stop,size,flip):
    fraction=(value-low)/(high-low);share=start+(stop-start)*fraction
    return size*(1-share) if flip else size*share


def critical(level):
    return level*math.sqrt(2/(1-level*level))


def refusal(callback,code,render_root):
    try:callback()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        assert not list(render_root.glob('plot/**/render-submission.json')),'consumer native ran before refusal'
        return error.fault.to_dict()
    raise AssertionError('expected '+code)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--r',required=True);parser.add_argument('--gnuplot',required=True)
    parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--timeout',type=float,default=300)
    args=parser.parse_args();root=args.output_directory.absolute();root.mkdir(parents=True,exist_ok=False)
    locations={'r':args.r,'gnuplot':args.gnuplot};base=json.loads((ROOT/'examples/schemaxis/r-prediction-to-gnuplot.json').read_text())
    report={'version':'schemaxis.r.prediction.gnuplot/1','verified':False,'sourceDigests':{name:source_digest(name) for name in ('r','gnuplot')},
        'recipeSHA256':file_digest(__file__),'workflowSHA256':file_digest(ROOT/'examples/schemaxis/r-prediction-to-gnuplot.json'),
        'scope':'One explicit halfWidth column of the R prediction table as the single Gnuplot error series; exact $artifact edge, captured bytes, independent SVG/PNG interval geometry, changed newdata/level propagation, resume reuse and pre-native refusals. '
            'The x axis is the first declared predictor of the new rows; no observed responses are plotted and no new-row truth is implied.','accepted':{},'negative':{}}
    def execute(document,name,**options):
        return workflow.execute(document,root/name,locations=locations,timeout=args.timeout,**options)
    def attempt(directory,operation):
        return sorted((directory/operation/'batch-0').glob('attempt-*'))[-1]
    def geometry(summary,rows,low,high,level_label=None):
        points=summary['geometry'][0]['points'];errors=summary['geometry'][0]['errorPixels']
        assert len(points)==len(errors)==len(rows)
        for point,pair,row in zip(points,errors,rows):
            x=pixel(row['inputs'][0]['value'],*low,.15,.95,800,False);y=pixel(row['prediction'],*high,.2,.9,600,True)
            assert math.isclose(point[0],x,abs_tol=.06) and math.isclose(point[1],y,abs_tol=.06),(point,x,y)
            lower=pixel(row['lower'],*high,.2,.9,600,True);upper=pixel(row['upper'],*high,.2,.9,600,True)
            assert math.isclose(pair[0],lower,abs_tol=.06) and math.isclose(pair[1],upper,abs_tol=.06),(pair,lower,upper)
            assert math.isclose(row['halfWidth'],row['upper']-row['prediction'],rel_tol=1e-9)
    try:
        directory=root/'individual';result=execute(base,'individual');assert workflow.verify(directory)['verified']
        r_directory=Path(next(job for job in result['jobs'] if job['operation']=='regression')['directory']);plot=attempt(directory,'plot')
        table=r_directory/'prediction.csv'
        assert (plot/'captured.csv').read_bytes()==table.read_bytes(),'captured bytes differ from the published R prediction table'
        captures=json.loads((plot/'captures.json').read_text());assert file_digest(table) in json.dumps(captures),captures
        summary=json.loads((r_directory/'regression-summary.json').read_text())['prediction'];shown=json.loads((plot/'plot-summary.json').read_text())
        assert shown['units']==['degC','V'] and shown['rows']==3 and shown['series']==1
        geometry(shown,summary['rows'],(-.5,3.5),(8,18))
        t=critical(.95)
        for row,x in zip(summary['rows'],(0,1,3)):assert math.isclose(row['halfWidth'],t*SIGMA*math.sqrt(1+.25+x*x/10),rel_tol=1e-9)
        svg=(plot/'plot.svg').read_text();assert 'Individual 95 percent prediction interval (V)' in svg and 'degC' in svg
        assert (plot/'plot.png').read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
        report['accepted']['individual']={'artifactEdge':{'$artifact':'regression','index':3},'capturedBytes':file_digest(plot/'captured.csv'),'errorPixels':shown['geometry'][0]['errorPixels'],
            'verification':'adaptor-owned independent SVG geometry and CRC-checked PNG reconstruction, plus this recipe affine recomputation from the R summary'}
        resumed=execute(base,'individual',resume=True);assert all(job['reused'] for job in resumed['jobs']);report['accepted']['resumeReuse']=True
        # Changed new rows, level and interval type propagate through the same edge.
        changed=copy.deepcopy(base);request=changed['operations'][0]['document']['prediction']
        request.update(interval='confidence',level=.9,newdata=[[-.25],[.5],[2.5]]);plot_document=changed['operations'][1]['document']
        plot_document['series'][0]['label']='Mean 90 percent confidence interval (V)';plot_document['title']='Calibration line with 90 percent mean confidence intervals'
        result=execute(changed,'confidence-level-0.9');assert workflow.verify(root/'confidence-level-0.9')['verified']
        r_directory=Path(next(job for job in result['jobs'] if job['operation']=='regression')['directory']);plot=attempt(root/'confidence-level-0.9','plot')
        summary=json.loads((r_directory/'regression-summary.json').read_text())['prediction'];shown=json.loads((plot/'plot-summary.json').read_text())
        assert summary['interval']=='confidence' and summary['level']==.9 and [row['inputs'][0]['value'] for row in summary['rows']]==[-.25,.5,2.5]
        for row,x in zip(summary["rows"],(-.25,.5,2.5)):assert math.isclose(row['halfWidth'],critical(.9)*SIGMA*math.sqrt(.25+x*x/10),rel_tol=1e-9)
        geometry(shown,summary['rows'],(-.5,3.5),(8,18));assert (plot/'captured.csv').read_bytes()==(r_directory/'prediction.csv').read_bytes()
        assert 'Mean 90 percent confidence interval (V)' in (plot/'plot.svg').read_text()
        assert shown['geometry'][0]['errorPixels']!=json.loads((attempt(root/'individual','plot')/'plot-summary.json').read_text())['geometry'][0]['errorPixels']
        report['accepted']['changedNewdataLevelType']={'level':summary['level'],'interval':summary['interval'],'errorPixels':shown['geometry'][0]['errorPixels']}
        # Incompatible consumers are refused before Gnuplot native execution.
        def variant(change):
            document=copy.deepcopy(base);change(document);return document
        plot_of=lambda d:d['operations'][1]['document']
        cases={'summary-artifact':('TYPE_MISMATCH',lambda d:plot_of(d)['source'].update(index=2)),
            'training-table-header':('INVALID_PLOT_DATA',lambda d:plot_of(d)['source'].update(index=1)),
            'artifact-index-out-of-range':('INVALID_SELECTION',lambda d:plot_of(d)['source'].update(index=7)),
            'half-width-unit':('PLOT_UNIT_MISMATCH',lambda d:plot_of(d)['columns'][5].update(unit='mV')),
            'axis-excludes-upper-endpoint':('PLOT_DATA_OUTSIDE_RANGE',lambda d:plot_of(d)['yAxis'].update(range=[8,17])),
            'declared-column-name':('INVALID_PLOT_DATA',lambda d:(plot_of(d)['columns'][1].update(name='x'),plot_of(d)['series'][0].update(x='x'))),
            'non-increasing-x':('INVALID_PLOT_DATA',lambda d:d['operations'][0]['document']['prediction'].update(newdata=[[1],[0]]))}
        for name,(code,change) in cases.items():
            fault=refusal(lambda:execute(variant(change),'refused-'+name),code,root/('refused-'+name))
            report['negative'][name]={'code':fault['code'],'location':fault['location'],'consumerNativeRuns':0}
        assert all(source_digest(name)==value for name,value in report['sourceDigests'].items()),'adaptor source changed during acceptance'
        report['verified']=True
    finally:atomic_json(root/'qualification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
