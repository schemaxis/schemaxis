"""Empirical flux of integrated pieces in a formal float-endpoint model.

Symbolic incidence closes; ideal-law and native-evaluation endpoint gaps need
not. All choice proxies and sampled maxima are empirical, not bounds.
"""
import math


def _passive_length_integral(function, start, end, tolerance, *, budget, depth=0):
    """Original G7/K15/depth18; passive length/area companions cannot refine."""
    from schemaxis.adaptors.freecad.gauss_green import _rule, finite, Unresolved
    start, end = finite(start), finite(end)
    tolerance = [finite(x) for x in tolerance]
    if len(tolerance) != 5 or any(x <= 0 for x in tolerance):
        raise Unresolved('monitored integral requires five positive targets')
    if type(depth) is not int or not 0 <= depth <= 18:
        raise Unresolved('monitored integral adaptive depth differs')
    budget.check()
    if start == end:
        return [0.]*7
    if end < start:
        return [-x for x in _passive_length_integral(function, end, start, tolerance, budget=budget, depth=depth)]
    values, errors = _rule(function, start, end, 7, budget)
    if all(error <= target for error, target in zip(errors[:5], tolerance)):
        return values
    if depth == 18:
        raise Unresolved('adaptive integration depth exhausted')
    mid = start+(end-start)/2
    if mid in (start, end):
        raise Unresolved('floating parameter resolution exhausted')
    budget.splits += 1
    target = [x/2 for x in tolerance]
    left = _passive_length_integral(function, start, mid, target, budget=budget, depth=depth+1)
    right = _passive_length_integral(function, mid, end, target, budget=budget, depth=depth+1)
    return [finite(math.fsum((a,b))) for a,b in zip(left,right)]


def complete_level(prepared, state, budget, row, *, fine):
    import FreeCAD as App
    from schemaxis.adaptors.freecad.gauss_green import (finite, partitions,
        coordinate_bounds, Unresolved, EvaluationLimit)
    from .mass_native import _surface
    beginning = budget.calls-row['evaluations']
    origin = App.Vector(*prepared['origin'])
    reference, targets, n = prepared['referenceVolume'], row['targets'], max(1,prepared['edges'])
    progress = {'fine':fine, 'pairs':0, 'collapsedFans':0, 'corners':0, 'connectorPatches':0,
                'pairEndpointTriangles':0, 'faceValues':0, 'faceDerivatives':0,
                'pcurveEvaluations':0, 'partitionEndpointSamples':0, 'gkSamples':0,
                'maximumPairGap':0., 'maximumCollapsedGap':0., 'maximumVertexGap':0.,
                'vertexComparisons':0, 'maximumUVGap':state['uvGapMaximum'],
                'prepareMaximumPhysicalEndpointGap':state['physicalEndpointMaximum'],
                'wireRuleCounts':{v:state['wireRules'].count(v) for v in sorted(set(state['wireRules']))}}
    state['progress'] = progress
    vertex_groups, vertices = {}, []
    ribbons, patches, caps, choice_edges, companions, edge_records, connector_records = [],[],[],[],[],[],[]
    area_trace_companions = []

    def tick():
        budget.tick()
        if budget.calls-beginning > 2_000_000:
            raise EvaluationLimit('completed-boundary unchanged per-level2M cap')
    def uv_at(curve,t):
        progress['pcurveEvaluations'] += 1
        return curve.evaluate(t)
    def point(face,curve,t):
        uv,_ = uv_at(curve,t)
        tick(); progress['faceValues'] += 1
        return face.valueAt(*uv)
    def trace(face,curve,t):
        uv,duv = uv_at(curve,t)
        tick(); progress['faceValues'] += 1; p = face.valueAt(*uv)
        tick(); progress['faceDerivatives'] += 1; su,sv = face.derivative1At(*uv)
        return p,su*duv[0]+sv*duv[1]
    def vertex_record(vertex):
        for index in vertex_groups.get(vertex.hashCode(),[]):
            tick(); progress['vertexComparisons'] += 1
            if vertex.isSame(vertices[index]['native']):
                return vertices[index]
        if vertex.isNull():
            raise Unresolved('completion missing native vertex')
        tick(); p = vertex.Point
        tick(); tolerance = finite(vertex.Tolerance)
        if tolerance < 0:
            raise Unresolved('negative native vertex tolerance')
        record = {'native':vertex,'point':p,'index':len(vertices),'tolerance':tolerance,
                  'maximumEndpointGap':0.,'maximumConnectorChord':0.,'maximumConnectorBow':0.,'endpoints':0}
        vertex_groups.setdefault(vertex.hashCode(),[]).append(len(vertices)); vertices.append(record)
        return record
    def endpoint_to_vertex(vertex,p):
        record = vertex_record(vertex); gap = finite((p-record['point']).Length)
        record['maximumEndpointGap'] = max(record['maximumEndpointGap'],gap); record['endpoints'] += 1
        progress['maximumVertexGap'] = max(progress['maximumVertexGap'],gap)
        if gap > record['tolerance']:
            raise Unresolved('endpoint exceeds native vertex tolerance: '+repr((gap,record['tolerance'],record['index'])))
        return record
    def flux(f,fp,e,ep,coefficient):
        d=e-f; dp=ep-fp; q=f-origin
        c0=q.dot(fp.cross(d)); c1=q.dot(dp.cross(d))
        volume=((f+e)*.5-origin).dot(((fp+ep)*.5).cross(d))/3
        moment=[(a*c0+(a*c1+b*c0)/2+b*c1/3)/(4*reference) for a,b in zip(q,d)]
        speed=max(fp.Length,ep.Length)
        return [coefficient*volume,*[coefficient*x for x in moment],finite(math.pi*d.Length**2*speed),finite(speed),finite(d.Length*speed)]
    def breaks_for(face,curve,bounds):
        envelope=coordinate_bounds(curve); d=list(face.ParameterRange)
        d=[min(d[0],envelope[0]),max(d[1],envelope[1]),min(d[2],envelope[2]),max(d[3],envelope[3])]
        uk,vk,_=_surface(face.Surface,d,budget)
        for axis,knots in ((0,uk),(1,vk)):
            for knot in knots:
                bounds.update(curve.crossings(axis,knot,budget=budget))
    def allocation(spans):
        divisor=4*n*(len(spans)-1)
        return [targets[1]/divisor,*[x/divisor for x in targets[2:]],targets[1]/divisor]
    def triangle(vertex,p,q,coefficient):
        pv=vertex_record(vertex)['point']-origin; p=p-origin; q=q-origin
        volume=coefficient*pv.dot(p.cross(q))/6; centre=(pv+p+q)*.25
        caps.append([volume,*[volume*x/reference for x in centre]])

    for piece in state['pairs']:
        i1,i2=piece.first,piece.second
        f1,s1,e1,c1,d1=state['occurrences'][i1]
        f2,s2,e2,c2,d2=state['occurrences'][i2]
        if (c1.start,c1.end)!=(c2.start,c2.end):
            raise Unresolved('completed-boundary paired intervals differ')
        progress['pairs'] += 1
        tick(); t1=finite(e1.Tolerance); tick(); t2=finite(e2.Tolerance)
        if min(t1,t2)<0: raise Unresolved('negative edge tolerance')
        allowed=t1+t2; bounds=set(c1.knots)|set(c2.knots)
        breaks_for(f1,c1,bounds); breaks_for(f2,c2,bounds)
        spans=partitions(c1.start,c1.end,sorted(bounds),third_cut=fine)
        record={'occurrences':[i1,i2],'tolerances':[t1,t2],'allowedPairGap':allowed,'maximumGap':0.,'partitionEndpoints':len(spans)}
        edge_records.append(record); endpoints={}
        def check_gap(p,q):
            gap=finite((p-q).Length); record['maximumGap']=max(record['maximumGap'],gap)
            progress['maximumPairGap']=max(progress['maximumPairGap'],gap)
            if gap>allowed:
                raise Unresolved('trace pair exceeds summed native edge tolerances: '+repr((gap,allowed,i1,i2)))
        for t in spans:
            p,q=point(f1,c1,t),point(f2,c2,t); check_gap(p,q)
            progress['partitionEndpointSamples'] += 1
            if t in (c1.start,c1.end): endpoints[t]=(p,q)
        for t,coefficient,vertex in ((c1.start,piece.start_cap,e1.firstVertex(False)),(c1.end,piece.end_cap,e1.lastVertex(False))):
            p,q=endpoints[t]; endpoint_to_vertex(vertex,p); endpoint_to_vertex(vertex,q)
            triangle(vertex,p,q,coefficient); progress['pairEndpointTriangles'] += 1
        lengths=[]
        def ribbon(t):
            p,pd=trace(f1,c1,t); q,qd=trace(f2,c2,t);check_gap(p,q)
            progress['gkSamples'] += 1
            return flux(p,pd,q,qd,piece.coefficient)
        for a,b in zip(spans,spans[1:]):
            result=_passive_length_integral(ribbon,a,b,allocation(spans),budget=budget)
            ribbons.append(result[:4]); companions.append(result[4]); lengths.append(result[5]); area_trace_companions.append(result[6]); tick()
        record['passiveLength']=math.fsum(lengths)
        choice_edges.append(math.pi*record['maximumGap']**2*record['passiveLength'])

    for piece in state['poles']:
        index=piece.occurrence
        face,sign,edge,curve,direction=state['occurrences'][index]
        vertex=piece.vertex
        if not vertex.isSame(edge.lastVertex(False)):
            raise Unresolved('collapsed edge endpoints differ')
        vr=vertex_record(vertex);pole=vr['point'];zero=App.Vector();bounds=set(curve.knots)
        breaks_for(face,curve,bounds);spans=partitions(curve.start,curve.end,sorted(bounds),third_cut=fine)
        progress['collapsedFans'] += 1; maximum=[0.]; lengths=[]
        def check(p):
            gap=finite((p-pole).Length);maximum[0]=max(maximum[0],gap)
            progress['maximumCollapsedGap']=max(progress['maximumCollapsedGap'],gap)
            if gap>vr['tolerance']: raise Unresolved('collapsed trace exceeds native vertex tolerance')
        for t in spans:
            p=point(face,curve,t);check(p);progress['partitionEndpointSamples']+=1
            if t in (curve.start,curve.end):endpoint_to_vertex(vertex,p)
        def fan(t):
            p,pd=trace(face,curve,t);check(p);progress['gkSamples']+=1
            return flux(p,pd,pole,zero,piece.coefficient)
        for a,b in zip(spans,spans[1:]):
            result=_passive_length_integral(fan,a,b,allocation(spans),budget=budget)
            ribbons.append(result[:4]);companions.append(result[4]);lengths.append(result[5]);area_trace_companions.append(result[6]);tick()
        choice_edges.append(math.pi*maximum[0]**2*math.fsum(lengths))
    area_choice=[]
    for piece in state['corners']:
        face,vertex,uv_i,uv_j=piece.face,piece.vertex,piece.before,piece.after
        progress['corners']+=1
        tick();progress['faceValues']+=1;fprev=face.valueAt(*uv_i)
        tick();progress['faceValues']+=1;fnext=face.valueAt(*uv_j)
        vr=endpoint_to_vertex(vertex,fprev);endpoint_to_vertex(vertex,fnext)
        chord=fnext-fprev;vr['maximumConnectorChord']=max(vr['maximumConnectorChord'],finite(chord.Length))
        triangle(vertex,fnext,fprev,piece.cap_coefficient)
        if uv_i==uv_j: continue
        progress['connectorPatches']+=1
        du,dv=uv_j[0]-uv_i[0],uv_j[1]-uv_i[1]
        rec={'vertex':vr['index'],'uvDelta':[du,dv],'uvNorm':math.hypot(du,dv),'chordLength':chord.Length,'maximumSampledNormal':0.,'maximumChordGap':0.}
        connector_records.append(rec)
        def patch(t):
            tick();progress['faceValues']+=1;f=face.valueAt(uv_i[0]+t*du,uv_i[1]+t*dv)
            tick();progress['faceDerivatives']+=1;su,sv=face.derivative1At(uv_i[0]+t*du,uv_i[1]+t*dv)
            e=fprev+chord*t;gap=finite((e-f).Length)
            rec['maximumSampledNormal']=max(rec['maximumSampledNormal'],finite(su.cross(sv).Length))
            rec['maximumChordGap']=max(rec['maximumChordGap'],gap)
            return flux(f,su*du+sv*dv,e,chord,piece.patch_coefficient)
        # Explicit endpoints too; do not rely on GK's open abscissae.
        patch(0.);patch(1.)
        spans=partitions(0.,1.,[],third_cut=fine)
        for a,b in zip(spans,spans[1:]):
            result=_passive_length_integral(patch,a,b,allocation(spans),budget=budget)
            patches.append(result[:4]);companions.append(result[4]);area_trace_companions.append(result[6]);tick()
        vr['maximumConnectorBow']=max(vr['maximumConnectorBow'],rec['maximumChordGap'])
        area_choice.append(math.pi/8*(du*du+dv*dv)*rec['maximumSampledNormal'])
    vertex_rows=[];vertex_choice=[]
    for v in vertices:
        # Every chord point lies within the endpoint ball; the surface
        # connector can additionally bow away from that chord.
        radius=v['maximumEndpointGap']+v['maximumConnectorBow']
        vertex_choice.append(4*math.pi*radius**3/3)
        vertex_rows.append({k:x for k,x in v.items() if k not in ('native','point')}|{'point':list(v['point']),'empiricalRadius':radius})
    correction=[math.fsum(x[i] for x in ribbons+patches+caps) for i in range(4)]
    volume=row['signedVolume']+correction[0]
    if not math.isfinite(volume) or volume == 0:
        raise Unresolved('completion has nonfinite or zero signed volume')
    relative=[(x-y)*row['signedVolume']/reference for x,y in zip(row['centre'],prepared['origin'])]
    centre=[x+(a+b)*reference/volume for x,a,b in zip(prepared['origin'],relative,correction[1:])]
    choice_volume=math.fsum(choice_edges+vertex_choice)
    from .line_endpoint_jumps import joint_choice
    line_proxy=row.get('lineEndpointJumpProxy',{'totals':[0.]*5})
    lens_proxy=row.get('conicLensProxy',{'records':[],'totals':[0.]*5})
    estimates=joint_choice(area_choice,choice_volume,line_proxy['totals'],
                           reference,centre,prepared['origin'],prepared['axisLevers'],volume=volume,
                           lens_totals=lens_proxy['totals']if lens_proxy.get('records')else None)
    limits=[max(1e-6,abs(row['area'])*1e-7),max(1e-6,abs(volume)*1e-7),*[max(1e-6,abs(x)*1e-7) for x in centre]]
    progress.update(evaluations=budget.calls-beginning,vertices=len(vertices),integratedCompanion=math.fsum(companions))
    if any(not math.isfinite(e) or e>limit/1000 for e,limit in zip(estimates,limits)):
        raise Unresolved('completed-boundary empirical choice exceeds unchangedL/1000')
    centre_targets=[finite((targets[i+2]*reference+abs(centre[i]-prepared['origin'][i])*targets[1])/abs(volume)) for i in range(3)]
    row.update(signedVolume=volume,centre=centre,propagatedCentreTargets=centre_targets,evaluations=budget.calls-beginning,completion={
        'method':'empirical-completed-boundary/1','certified':False,
        'areaDefinition':'winding-weighted original-chart area of the formal float-endpoint chain; declared auxiliary conic lenses may add local multiplicities in -2..3 (overperiod) or -1..2 (tangent); sampled and empirically small, not certified unit unsigned physical area; artificial skin excluded',
        'volumeDefinition':'empirical oriented flux of integrated pieces in the formal float-endpoint chain; endpoint jumps not integrated',
        'centreDefinition':'empirical first moments of those pieces divided by their signed volume',
        'boundarySpace':'formal-float-endpoint-incidence/1','idealLawClosureCertified':False,
        'counts':progress,'edges':edge_records,'vertices':vertex_rows,'connectors':connector_records,
        'empiricalChoice':estimates,'integratedGapSquaredSpeedCompanion':math.fsum(companions),
        'lineEndpointJumpProxy':line_proxy,
        'conicLensProxy':lens_proxy,
        'integratedTracePositionAreaCompanion':math.fsum(area_trace_companions),
        'areaCompanionDefinition':'integral of sampled trace gap times maximum paired trace speed; diagnostic, not a bound',
        'passiveLengthRule':'Kronrod on flux+gap-squared-companion accepted panels; length and trace-position area never adaptive drivers',
        'ribbonTotals':[math.fsum(x[i] for x in ribbons) for i in range(4)],
        'curvedConnectorTotals':[math.fsum(x[i] for x in patches) for i in range(4)],
        'vertexCapTotals':[math.fsum(x[i] for x in caps) for i in range(4)],
        'unresolved':['sampled maxima are not whole-curve bounds','UV half-disc and vertex-ball proxies require confined alternatives for a bound','shell non-self-intersection assumed; coarse mesh only discriminates gross winding',
            'conic/rational endpoint jumps are unmodelled',
            'auxiliary conic lens samples are not whole-support density bounds and exclude virtual-join one-form integrals',
            '3D ribbon/fan/patch end rungs versus float caps are unmodelled',
            'connector patch evaluated end versus declared next endpoint is unmodelled',
            'stored-slope versus native pcurve endpoints and quadrature/evaluation roundoff are unmodelled',
            'line chart one-form jump proxy is not total closure uncertainty or a bound']})
    return row
