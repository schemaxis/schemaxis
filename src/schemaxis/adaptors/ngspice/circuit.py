# Copyright (C) 2026 David L F Gaden
"""Dependency-free linear nodal solver and independently checked circuit tables."""
import cmath
import math
from pathlib import Path
from schemaxis.errors import fail


def check(condition,message):
    if not condition: fail('VERIFICATION_FAILED',message)


def solve(matrix,right,admittance_scale=0):
    """Partial-pivot Gaussian elimination for at most sixteen unknown voltages."""
    a=[list(row)+[b] for row,b in zip(matrix,right)]; count=len(a)
    for column in range(count):
        pivot=max(range(column,count),key=lambda i:abs(a[i][column]))
        scale=max(admittance_scale,max(abs(v) for row in a[column:] for v in row[:-1]))
        if not scale or abs(a[pivot][column]) <= 1e-14*scale:
            fail('ILL_CONDITIONED_CIRCUIT','linear network is singular or numerically ill-conditioned; add damping or use bounded component ratios')
        a[column],a[pivot]=a[pivot],a[column]
        for i in range(column+1,count):
            factor=a[i][column]/a[column][column]
            for j in range(column,count+1):a[i][j]-=factor*a[column][j]
    result=[0j]*count
    for i in range(count-1,-1,-1):
        result[i]=(a[i][-1]-sum(a[i][j]*result[j] for j in range(i+1,count)))/a[i][i]
    return result


def voltages(prepared,value):
    network=prepared['circuit']; drive=network['source']; nodes=prepared['nodes']
    fixed={'0':0j,drive:complex(value if prepared['operation']=='dcSweep' else prepared['amplitude'])}
    unknown=[node for node in nodes if node != drive]; indices={node:i for i,node in enumerate(unknown)}
    size=len(unknown); matrix=[[0j]*size for _ in range(size)]; rhs=[0j]*size
    edges=[(r['a'],r['b'],1/r['resistance']) for r in network['resistors']]
    if prepared['operation']=='acSweep':
        edges += [(c['a'],c['b'],2j*math.pi*value*c['capacitance']) for c in network['capacitors']]
        edges += [(ind['a'],ind['b'],1/(2j*math.pi*value*ind['inductance'])) for ind in network.get('inductors',[])]
    scales=[0.0]*size
    for a,b,admittance in edges:
        for node,other in ((a,b),(b,a)):
            if node in indices:
                i=indices[node];matrix[i][i]+=admittance;scales[i]+=abs(admittance)
                if other in indices:matrix[i][indices[other]]-=admittance
                else:rhs[i]+=admittance*fixed[other]
    # Preserve the uncancelled stamp scale: an undamped LC resonance can
    # otherwise look like a well-conditioned 1x1 matrix of numerical noise.
    fixed.update(zip(unknown,solve(matrix,rhs,max(scales,default=0))))
    return fixed


def samples(prepared):
    count=prepared['points'];start=prepared.get('start',0);stop=prepared['stop']
    spacing=prepared.get('spacing','linear')
    if spacing=='linear':return [start+(stop-start)*i/(count-1) for i in range(count)]
    # ngspice 47 acan.c: decade spans >= 1 decade redistribute floor(density*
    # log10(ratio)) intervals to include stop. Short decades and octaves retain
    # their nominal ratio. Independently reconstruct the expected sample grid.
    intervals=math.floor(math.log10(stop/start)*count)
    factor=(math.exp(math.log(stop/start)/intervals) if spacing=='decade' and stop/10>=start
            else math.exp(math.log(10 if spacing=='decade' else 2)/count))
    result=[];value=start
    while value<=stop+factor*stop*1e-9:
        result.append(value)
        if len(result)>512:return result  # admission rejects before native work
        value*=factor
    return result


def row_width(prepared):
    return 1+len(prepared['nodes'])*(2 if prepared['operation']=='acSweep' else 1)+2*bool(prepared.get('portMetrics'))


def branches(prepared,frequency,values):
    """Passive current a -> b and complex power from checked native voltages."""
    factor=.5 if prepared.get('amplitudeConvention','peak')=='peak' else 1
    result={}
    for kind,field in (('resistors','resistance'),('capacitors','capacitance'),('inductors','inductance')):
        for component in prepared['circuit'].get(kind,[]):
            drop=values[component['a']]-values[component['b']];parameter=component[field]
            y={'resistors':lambda:1/parameter,'capacitors':lambda:2j*math.pi*frequency*parameter,
               'inductors':lambda:1/(2j*math.pi*frequency*parameter)}[kind]()
            current=drop*y
            result[component['name']]={'voltage':drop,'current':current,'power':factor*drop*current.conjugate()}
    return result


def input_current(prepared,frequency,values):
    currents=branches(prepared,frequency,values);drive=prepared['circuit']['source'];total=0j
    for kind in ('resistors','capacitors','inductors'):
        for component in prepared['circuit'].get(kind,[]):
            i=currents[component['name']]['current']
            if component['a']==drive:total+=i
            if component['b']==drive:total-=i
    return total


def port_impedance(prepared,frequency,values):
    current=input_current(prepared,frequency,values)
    scale=sum(abs(branch['current']) for branch in branches(prepared,frequency,values).values())
    if abs(current)<=max(1e-30,1e-14*scale):
        fail('UNDEFINED_OBSERVABLE','input impedance is undefined or ill-conditioned near zero input current; disable portMetrics or add a physical load','$.portMetrics')
    return values[prepared['circuit']['source']]/current


def native_values(prepared,row):
    return {'0':0j,**{node:complex(row[1+2*i],row[2+2*i]) for i,node in enumerate(prepared['nodes'])}}


def source_current(prepared,row):
    offset=1+2*len(prepared['nodes'])
    return -complex(row[offset],row[offset+1])


def current_error(prepared,rows):
    maximum=0.0
    for frequency,row in zip(samples(prepared),rows):
        observed=source_current(prepared,row)
        independent=input_current(prepared,frequency,expected(prepared,frequency))
        kcl=input_current(prepared,frequency,native_values(prepared,row))
        error=max(abs(observed-independent),abs(observed-kcl));maximum=max(maximum,error)
        check(abs(observed)>0 and error<=1e-7*abs(independent),'independent source current/KCL differs (relative error; no absolute-current floor)')
    return maximum


def observables(prepared,row):
    """Named AC engineering quantities from checked native observations."""
    values=native_values(prepared,row);drive=values[prepared['circuit']['source']]
    result={}
    for node in prepared['circuit']['probes']:
        value=values[node];gain=value/drive
        result[node]={'magnitude_V':abs(value),'gainMagnitude':abs(gain)}
        if abs(gain)>1e-30:
            result[node].update(phase_deg=math.degrees(cmath.phase(gain)),gain_dB=20*math.log10(abs(gain)))
    for name,branch in branches(prepared,row[0],values).items():
        if name in prepared['circuit'].get('branchProbes',[]):
            result.setdefault(name,{}).update(currentMagnitude_A=abs(branch['current']),
                activePower_W=branch['power'].real,reactivePower_var=branch['power'].imag)
    if prepared.get('portMetrics'):
        current=source_current(prepared,row);check(abs(current)>0,'zero native input current cannot define impedance');factor=.5 if prepared['amplitudeConvention']=='peak' else 1
        power=factor*drive*current.conjugate()
        result['$input']={'currentMagnitude_A':abs(current),'impedanceMagnitude_Ohm':abs(drive/current),
                          'activePower_W':power.real,'reactivePower_var':power.imag}
    return result


def expected(prepared,axis):
    if prepared['operation'] != 'rcStep':return voltages(prepared,axis)
    amplitude=prepared['amplitude'];drive=prepared['circuit']['source'];node=prepared['responseNode']
    return {'0':0j,drive:complex(amplitude),node:complex(-amplitude*math.expm1(-axis/prepared['timeConstant']))}


def read_table(path,width,points):
    path=Path(path)
    check(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4*1024*1024,'missing or excessive native table')
    lines=path.read_text(encoding='ascii').splitlines()
    check(len(lines)==points+1 and len(lines[0].split())==width,'native table shape differs')
    rows=[list(map(float,line.split())) for line in lines[1:]]
    check(all(len(row)==width and all(math.isfinite(v) for v in row) for row in rows),'invalid native numeric table')
    return rows


def inspect(prepared,rows):
    complex_values=prepared['operation']=='acSweep';nodes=prepared['nodes']
    check(len(rows)==len(samples(prepared)),'unexpected native sample count')
    maximum=0.0
    for axis,row in zip(samples(prepared),rows):
        check(len(row)==row_width(prepared),'native row width differs')
        # Native DC stepping accumulates roundoff. Scale its absolute allowance
        # to the full interval, including when the authored endpoint is zero.
        scale=max(abs(prepared.get('start',0)),abs(prepared['stop']),1e-12)
        check(math.isclose(row[0],axis,rel_tol=1e-10,abs_tol=scale*1e-12),'native sample coordinates differ')
        reference=expected(prepared,axis)
        for index,node in enumerate(nodes):
            observed=complex(row[1+2*index],row[2+2*index]) if complex_values else complex(row[1+index])
            value=reference[node];error=abs(observed-value);maximum=max(maximum,error)
            tolerance=(2e-6*max(abs(prepared['amplitude']),1) if prepared['operation']=='rcStep'
                       else 1e-9+1e-7*abs(value))
            if complex_values:
                # Preserve transfer-function accuracy at tiny excitation levels.
                # The inherited fixed voltage floor is unsuitable for ratios.
                tolerance=1e-12*abs(prepared['amplitude'])+1e-7*abs(value)
                relative_required=any(entry['probe']==node and entry['quantity'] in ('gainMagnitude','gain_dB','phase_deg')
                    for entry in prepared.get('requirements',[]))
                if relative_required and abs(value)>0:tolerance=min(tolerance,1e-7*abs(value))
            check(math.isfinite(error) and error<=tolerance,'independent voltage differs for '+node)
    if prepared.get('portMetrics'):current_error(prepared,rows)
    return maximum


def publication(prepared,rows):
    complex_values=prepared['operation']=='acSweep'
    columns=[{'dcSweep':'sourceVoltage_V','acSweep':'frequency_Hz','rcStep':'time_s'}[prepared['operation']]]
    for node in prepared['circuit']['probes']:
        columns += ([node+'_real_V',node+'_imag_V',node+'_magnitude_V',node+'_phase_deg'] if complex_values else [node+'_V'])
    for name in prepared['circuit'].get('branchProbes',[]):
        columns += [name+suffix for suffix in ('_current_real_A','_current_imag_A','_current_magnitude_A','_current_phase_deg','_activePower_W','_reactivePower_var')]
    if prepared.get('portMetrics'):
        columns += ['$input'+suffix for suffix in ('_current_real_A','_current_imag_A','_current_magnitude_A','_current_phase_deg','_impedance_real_Ohm','_impedance_imag_Ohm','_impedance_magnitude_Ohm','_activePower_W','_reactivePower_var','_apparentPower_VA')]
    values=[]
    for row in rows:
        selected=[row[0]]
        for node in prepared['circuit']['probes']:
            index=prepared['nodes'].index(node)
            if complex_values:
                value=complex(row[1+2*index],row[2+2*index]);selected.extend([value.real,value.imag,abs(value),math.degrees(cmath.phase(value))])
            else:selected.append(row[index+1])
        if complex_values:
            native=native_values(prepared,row)
            branch_values=branches(prepared,row[0],native)
            for name in prepared['circuit'].get('branchProbes',[]):
                branch=branch_values[name];i=branch['current'];power=branch['power']
                selected.extend([i.real,i.imag,abs(i),math.degrees(cmath.phase(i)),power.real,power.imag])
            if prepared.get('portMetrics'):
                i=source_current(prepared,row);check(abs(i)>0,'zero native input current cannot define impedance');drive=native[prepared['circuit']['source']];z=drive/i
                power=drive*i.conjugate()*(.5 if prepared['amplitudeConvention']=='peak' else 1)
                selected.extend([i.real,i.imag,abs(i),math.degrees(cmath.phase(i)),z.real,z.imag,abs(z),power.real,power.imag,abs(power)])
        values.append(selected)
    return {'columns':columns,'rows':values}


def read_raw(path,prepared):
    """Parse the generated ASCII raw subset independently of ngspice readback."""
    path=Path(path)
    check(path.is_file() and not path.is_symlink() and path.stat().st_size<=4*1024*1024,'missing/excessive native raw data')
    text=path.read_text(encoding='ascii');lines=text.splitlines()
    check(lines.count('Variables:')==1 and lines.count('Values:')==1,'raw variable/value sections differ')
    start=lines.index('Variables:');stop=lines.index('Values:')
    headers={}
    for line in lines[:start]:
        key,separator,value=line.partition(':')
        check(bool(separator) and key not in headers,'invalid/repeated raw header')
        headers[key]=value.strip()
    complex_values=prepared['operation']=='acSweep';count=1+len(prepared['nodes'])+bool(prepared.get('portMetrics'))
    check(headers.get('Flags')==('complex' if complex_values else 'real'),'raw numerical kind differs')
    check(int(headers['No. Variables'])==count and int(headers['No. Points'])==len(samples(prepared)),'raw dimensions differ')
    variables=[line.split() for line in lines[start+1:stop]]
    scale={'dcSweep':'v(v-sweep)','acSweep':'frequency','rcStep':'time'}[prepared['operation']]
    if prepared.get('spacing','linear')!='linear' and variables and variables[0][-1:] == ['grid=3']:
        variables[0]=variables[0][:-1]
    check(len(variables)==count and all(len(v)==3 and v[0]==str(i) for i,v in enumerate(variables)),'raw variable indices differ')
    check([v[1] for v in variables]==[scale]+['v('+n+')' for n in prepared['nodes']]+(['i(vdrive)'] if prepared.get('portMetrics') else []),'raw variable names differ')
    values=' '.join(lines[stop+1:]).split()
    check(len(values)==len(samples(prepared))*(count+1),'raw value count differs')
    rows=[]
    for i in range(len(samples(prepared))):
        offset=i*(count+1);check(values[offset]==str(i),'raw sample index differs')
        parsed=[]
        for value in values[offset+1:offset+count+1]:
            pair=value.split(',');check(len(pair)==(2 if complex_values else 1),'invalid raw scalar')
            numbers=list(map(float,pair));check(all(math.isfinite(v) for v in numbers),'nonfinite raw scalar')
            parsed.append(complex(*numbers))
        check(parsed[0].imag==0,'complex sample coordinate')
        row=[parsed[0].real]
        for value in parsed[1:]:row.extend([value.real,value.imag] if complex_values else [value.real])
        rows.append(row)
    return rows
