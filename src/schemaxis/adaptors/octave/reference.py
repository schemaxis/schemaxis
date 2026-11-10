# Copyright (C) 2026 David L F Gaden
"""Independent host arithmetic used to verify native Octave publications."""
import cmath
import bisect
import math
import statistics
from schemaxis.errors import fail
from schemaxis.tabular import numeric


def increasing(x, location='$'):
    if any(b <= a for a,b in zip(x,x[1:])):
        fail('INVALID_SAMPLING', 'abscissae must be strictly increasing for this operation', location)


def fft(values):
    """Radix-2 reference; the application uses FFTW, not this implementation."""
    n=len(values)
    if n==1: return [complex(values[0])]
    even, odd=fft(values[::2]), fft(values[1::2])
    weights=[cmath.exp(-2j*math.pi*k/n)*v for k,v in enumerate(odd)]
    return [a+b for a,b in zip(even,weights)]+[a-b for a,b in zip(even,weights)]


def statistics_of(y):
    return {'count':len(y), 'mean':statistics.fmean(y), 'median':statistics.median(y),
            'stdSample':statistics.stdev(y), 'minimum':min(y), 'maximum':max(y),
            'rms':math.sqrt(math.fsum(v*v for v in y)/len(y))}


def evaluate(prepared, sources):
    result={}
    total=0
    for node in prepared['nodes']:
        op,o=node['filter'],node['options']
        metadata={}
        if op=='samples': x,y=list(o['x']),list(o['y'])
        elif op=='readCSV':
            table=sources[node['id']]
            try: xi,yi=table['columns'].index(o['xColumn']),table['columns'].index(o['yColumn'])
            except ValueError: fail('INVALID_TABLE', 'requested CSV column is absent',node['id'])
            x=[row[xi] for row in table['rows']];y=[row[yi] for row in table['rows']]
        elif op in ('sequence','wave'):
            if op=='sequence':
                x=[o['start']+(o['stop']-o['start'])*i/(o['count']-1) for i in range(o['count'])]
                y=list(x)
            else:
                x=[o['start']+o['step']*i for i in range(o['count'])]
                fn=math.sin if o['shape']=='sine' else math.cos
                y=[o['offset']+o['amplitude']*fn(2*math.pi*o['frequency']*v+o['phase']) for v in x]
        else:
            source=result[node['inputs']['input']]; x=list(source['x']); y=list(source['y'])
            if op=='scale': y=[o['factor']*v+o['offset'] for v in y]
            elif op=='resample':
                increasing(x,node['id'])
                target=[x[0]+(x[-1]-x[0])*i/(o['count']-1) for i in range(o['count'])]
                values=[]
                for coordinate in target:
                    right=min(max(bisect.bisect_right(x,coordinate),1),len(x)-1)
                    fraction=(coordinate-x[right-1])/(x[right]-x[right-1])
                    values.append(y[right-1]+fraction*(y[right]-y[right-1]))
                x,y=target,values
            elif op=='movingMean':
                if o['window']>len(y):fail('INVALID_SAMPLING','moving mean window exceeds sample count',node['id'])
                half=o['window']//2
                y=[statistics.fmean(y[max(0,i-half):min(len(y),i+half+1)]) for i in range(len(y))]
            elif op=='derivative':
                increasing(x,node['id'])
                y=[(y[min(i+1,len(y)-1)]-y[max(0,i-1)])/(x[min(i+1,len(x)-1)]-x[max(0,i-1)]) for i in range(len(y))]
            elif op=='integral':
                increasing(x,node['id'])
                partial=[o['initial']]
                for i in range(1,len(x)): partial.append(partial[-1]+(x[i]-x[i-1])*(y[i]+y[i-1])/2)
                y=partial
            elif op=='linearFit':
                centre=statistics.fmean(x); mean=statistics.fmean(y)
                variance=math.fsum((v-centre)**2 for v in x)
                if variance <= 1e-24: fail('SINGULAR_FIT','linear fit needs varying x',node['id'])
                slope=math.fsum((a-centre)*(b-mean) for a,b in zip(x,y))/variance
                intercept=mean-slope*centre
                fitted=[slope*v+intercept for v in x]
                residual=math.fsum((a-b)**2 for a,b in zip(y,fitted))
                metadata={'slope':slope,'intercept':intercept,'residualSumSquares':residual}
                y=fitted
            elif op=='fft':
                increasing(x,node['id']);n=len(x);step=(x[-1]-x[0])/(n-1)
                if n<4 or n>8192 or n & (n-1): fail('INVALID_SAMPLING','FFT needs 4 to 8192 samples in a power of two',node['id'])
                if any(not math.isclose(b-a,step,rel_tol=1e-8,abs_tol=1e-12) for a,b in zip(x,x[1:])):
                    fail('INVALID_SAMPLING','FFT needs uniform sampling',node['id'])
                spectrum=fft(y)
                y=[abs(spectrum[k])/n*(1 if k in (0,n//2) else 2) for k in range(n//2+1)]
                x=[k/(n*step) for k in range(n//2+1)]
                metadata={'sampleSpacing':step,'sourceCount':n}
        if len(x)!=len(y) or len(x)<2: fail('INVALID_TABLE','x and y need equal lengths of at least two',node['id'])
        x=[numeric(v,node['id']) for v in x];y=[numeric(v,node['id']) for v in y]
        total+=len(x)
        if total>100000: fail('RESOURCE_LIMIT','analysis exceeds 100000 intermediate samples',node['id'])
        result[node['id']]={'x':x,'y':y,'metadata':metadata,'statistics':statistics_of(y)}
    return result
