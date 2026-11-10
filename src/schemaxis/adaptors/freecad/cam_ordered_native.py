"""Internal ordered-stock geometry; no public policy or submitted restore.

Only a fresh trusted constructor may provide the tool objects to profiles().
Neither receipt dimensions nor the final desired void establish physical access.
"""
import math
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .cam_mixed_geometry_native import Geometry,disc,capsule,arc_faces
from .cam_mixed_budget import LIMITS
from .cam_pointed import ENDMILL_SHANK_OVERLAP
from .cam_pointed_source_native import topology


class OrderedGeometry(Geometry):
    def __init__(self):
        super().__init__();self.distances=0;self.minimum_gap=None

    def _call(self):
        remaining_timeout()
        if self.budget.operations+self.distances>=LIMITS['booleans']:
            fail('RESOURCE_LIMIT','Ordered stock geometry exceeds its combined Boolean/distance budget')

    def boolean(self,left,right,kind):
        self._call();return super().boolean(left,right,kind)

    def separated(self,mask,stock,gap,location):
        """Explicit material overlap PLUS direct minimum distance, without close()."""
        if type(gap) not in (int,float) or not math.isfinite(gap) or gap<=0:
            raise ValueError('Ordered stock separation needs a positive finite engineering gap')
        self.mass(mask)
        if stock.isNull():return None
        overlap=self.boolean(mask,stock,'common')
        if self.mass(overlap,boundary=True)['solids']:
            fail('TOOL_COLLISION','Complete physical tool or holder intersects current stock',location)
        # distToShape can return positive distance for a contained solid. The
        # overlap test above is mandatory, including all positive Solid pieces.
        self._call();a,_=topology(mask);b,_=topology(stock)
        if a*b>LIMITS['facePairs']-self.budget.face_pairs:
            fail('RESOURCE_LIMIT','Ordered stock distance exceeds its cumulative face-pair budget')
        self.budget.face_pairs+=a*b;self.distances+=1
        distance=mask.distToShape(stock)[0];remaining_timeout()
        if not math.isfinite(distance) or distance<gap:
            fail('TOOL_CLEARANCE','Complete physical tool or holder lacks the declared stock separation',
                 location,distance=distance,required=gap)
        self.minimum_gap=distance if self.minimum_gap is None else min(self.minimum_gap,distance)
        return distance

    def unoccupied(self,mask,stock,location):
        """Rapid/installation Q_rapid: contact only, ZERO removal credit."""
        self.mass(mask)
        if stock.isNull():return
        overlap=self.boolean(mask,stock,'common')
        # mass validates signed occurrence topology before classifying an
        # intersection as boundary-only. No finish-quality epsilon applies.
        if self.mass(overlap,boundary=True)['solids']:
            fail('TOOL_COLLISION','Rapid cutting occupancy intersects actual remaining stock',location)


def cylinder(xy,low,high,radius):
    import FreeCAD as A,Part
    if (not all(math.isfinite(v) for v in [*xy,low,high,radius])
            or radius<=0 or high<=low):
        fail('VERIFICATION_FAILED','Physical axial envelope must have finite positive radius and length')
    remaining_timeout();shape=Part.makeCylinder(radius,high-low,A.Vector(*xy,low));topology(shape)
    return shape


def profiles(doc,prepared,geometry):
    """Derive masks from actual tools in an installed, freshly generated Job.

    Caller must bind the whole submitted source/Job before using these fresh
    objects. This function is not an authored shape/native-property interface.
    Actual complete bit containment and cutting-credit containment are tested;
    template/readback volume agreement alone cannot establish either relation.
    """
    from .cam_pointed_native import physical,holder_readback
    import FreeCAD as A,Part
    result={}
    for tool in prepared['tools']:
        remaining_timeout();native=doc.getObject(tool['controller']).Tool
        physical(native,tool);holder_readback(doc,tool);shape=native.Shape
        geometry.mass(shape)
        # Bounds conservatively enclose the fresh fixed template. They are not
        # editable witnesses, and complete set containment is still mandatory.
        b=shape.BoundBox
        outer=max(abs(b.XMin),abs(b.XMax),abs(b.YMin),abs(b.YMax))
        length=b.ZMax
        # OCCT bounds may include padding below an actual planar tip. Do not
        # classify that box as physical material or clamp the shape: the full
        # native set-difference below must prove containment from actual Z=0.
        full=cylinder([0,0],0,length,outer)
        if geometry.mass(geometry.difference(shape,full),boundary=True)['solids']:
            fail('VERIFICATION_FAILED','Full fresh physical bit is outside its complete rapid mask')
        r=tool['diameter']/2
        if tool['kind']=='drill':
            h=tool['tipHeight'];end=tool['cuttingReach']
            cone=Part.makeCone(0,r,h,A.Vector());topology(cone)
            cut=geometry.union(cone,cylinder([0,0],h,end,r))
            # A smaller radius is allowed only after the actual complete
            # shoulder/shank profile above was independently measured. Full
            # B subset C_cut union H below still binds every native region.
            guard_radius=tool['shankDiameter']/2 if 'shankDiameter' in tool else outer
        else:
            h=0.;end=tool['cuttingLength']-ENDMILL_SHANK_OVERLAP
            cut=cylinder([0,0],0,end,r);guard_radius=outer
        if geometry.mass(geometry.difference(cut,shape),boundary=True)['solids']:
            fail('VERIFICATION_FAILED','Declared finite cutting credit is outside the fresh physical bit')
        guards=[{'low':end,'high':length,'radius':guard_radius}]
        partition=geometry.union(cut,cylinder([0,0],end,length,guard_radius))
        if geometry.mass(geometry.difference(shape,partition),boundary=True)['solids']:
            fail('VERIFICATION_FAILED','Fresh physical bit is not covered by credited cutting and complete guarded material')
        rapid=[{'low':0.,'high':length,'radius':outer}]
        if 'holder' in tool:
            for index,step in enumerate(tool['holder']['steps']):
                part=doc.getObject('Holder'+str(tool['number']-1)+'Step'+str(index))
                # Finite owner/group/role, frame and every shape/property were
                # checked against compiled intent by holder_readback above.
                item={'low':part.Placement.Base.z,'high':part.Placement.Base.z+part.Height.Value,
                      'radius':part.Radius.Value}
                enclosing=cylinder([0,0],item['low'],item['high'],item['radius'])
                if geometry.mass(geometry.difference(part.Shape,enclosing),boundary=True)['solids']:
                    fail('VERIFICATION_FAILED','Actual holder step is outside its complete guarded mask',part.Name)
                guards.append(item);rapid.append(dict(item))
        result[tool['id']]={'radius':r,'height':h,'cuttingEnd':end,
                             'guards':guards,'rapid':rapid,'kind':tool['kind']}
    return result


def above_original(motion,interval,top,gap):
    """Whole axial interval plus gap above the ORIGINAL blank, not current void."""
    lower=math.nextafter(min(motion['from'][2],motion['to'][2])+interval['low'],-math.inf)
    return lower>=math.nextafter(top+gap,math.inf)


def sweep(motion,interval,geometry):
    """Exact cylindrical axial-piece sweep for vertical or planar movement."""
    a,b=motion['from'],motion['to'];low=interval['low'];high=interval['high'];r=interval['radius']
    vertical=a[:2]==b[:2];planar=a[2]==b[2]
    if motion['code'] in (2,3):
        if not planar:fail('UNSUPPORTED_TOOLPATH','Ordered circular sweep must be exactly planar')
        return [geometry.prism(face,area,high-low) for face,area in arc_faces(motion,a[2]+low,r,geometry)]
    if vertical:return [cylinder(a[:2],min(a[2],b[2])+low,max(a[2],b[2])+high,r)]
    if planar:
        face,area=capsule([*a[:2],a[2]+low],[*b[:2],b[2]+low],r)
        return [geometry.prism(face,area,high-low)]
    fail('UNSUPPORTED_TOOLPATH','Ordered physical sweep needs exact vertical or planar motion')


def cutting(motion,profile,geometry):
    """Actual FINITE cutting occupancy; no original-top or deepest-only shortcut."""
    import FreeCAD as A,Part
    a,b=motion['from'],motion['to'];h=profile['height'];r=profile['radius'];end=profile['cuttingEnd']
    if profile['kind']=='drill':
        if a[:2]!=b[:2] or motion['code']!=1:
            fail('UNSUPPORTED_TOOLPATH','Pointed feed cutting requires exact vertical movement')
        lo,hi=sorted((a[2],b[2]));cone=Part.makeCone(0,r,h,A.Vector(*a[:2],lo));topology(cone)
        return [geometry.union(cone,cylinder(a[:2],lo+h,hi+end,r))]
    return sweep(motion,{'low':0.,'high':end,'radius':r},geometry)


def descending_credit(motion,profile,interval,gap):
    """Restricted temporal proof, never a substitute for the full side-gap test."""
    a,b=motion['from'],motion['to'];h=profile['height']
    if (motion['code']!=1 or a[:2]!=b[:2] or b[2]>=a[2]
            or interval['low']-gap<=h):return None
    return cylinder(a[:2],b[2]+h,a[2]+h,profile['radius'])


def rapid_cutting(motion,profile,geometry):
    """Q_rapid has ZERO removal credit; planar pointed occupancy is conservative."""
    if profile['kind']=='drill' and motion['from'][:2]!=motion['to'][:2]:
        return sweep(motion,{'low':0.,'high':profile['cuttingEnd'],'radius':profile['radius']},geometry)
    return cutting(dict(motion,code=1) if motion['code']==0 else motion,profile,geometry)


def replay_geometry(prepared,replay,source,fresh_profiles,geometry):
    """Prefix stock in actual NC order, with no future-operation access credit.

    Unconnected until the public family gate is complete. Fresh profile handles
    and the Geometry ledger must come from the trusted reference factory, after
    whole submitted source/native/program admission, never saved witnesses.
    """
    import FreeCAD as A,Part
    from .cam_ordered import preflight_ordered,reusable_vertical_rapid,cleared_column
    from .cam_pointed import admit_tip_clearance
    costs=preflight_ordered(prepared,replay);admit_tip_clearance(prepared,replay)
    if set(fresh_profiles)!={t['id'] for t in prepared['tools']}:
        fail('VERIFICATION_FAILED','Fresh physical profiles do not cover every declared active tool')
    box=prepared['stockBounds'];top=box[5];gap=prepared['setup']['toolClearance']['minimumSeparation']
    remaining=Part.makeBox(box[1]-box[0],box[3]-box[2],top-box[4],A.Vector(box[0],box[2],box[4]))
    stock_mass=geometry.mass(remaining);target_mass=geometry.mass(source)
    active=None;position=None;prefix=[];cut_sweeps=checks=transitions=feeds=credits=reuses=0
    last_feed=None;last_cut=None
    def outside(motion,low,margin=0.):
        return above_original(motion,{'low':low},top,margin)
    def guard_motion(motion,profile,cut_shapes,location,feed):
        nonlocal checks,credits
        after_credit=None;credit=None
        for interval in profile['guards']:
            if above_original(motion,interval,top,gap):continue
            state=remaining
            eligible=(feed and motion['code']==1 and motion['from'][:2]==motion['to'][:2]
                      and motion['to'][2]<motion['from'][2] and interval['low']-gap>profile['height'])
            if eligible:
                if credit is None:
                    credit=descending_credit(motion,profile,interval,gap)
                    if len(cut_shapes)!=1 or geometry.mass(geometry.difference(credit,cut_shapes[0]),boundary=True)['solids']:
                        fail('VERIFICATION_FAILED','Finite temporal credit is outside the actual current cutting sweep')
                    after_credit=geometry.difference(remaining,credit);credits+=1
                state=after_credit
            for shape in sweep(motion,interval,geometry):
                geometry.separated(shape,state,gap,location);checks+=1
    for ordinal,event in enumerate(replay['events']):
        remaining_timeout()
        if 'toolChange' in event:
            last_feed=last_cut=None
            item=event['toolChange'];active=item['tool'];position=item['position'];transitions+=1
            if position is None:continue #unknown physical initial/toolchanger trajectory
            motion={'code':0,'tool':active,'from':position,'to':position};feed=False
        elif 'positioned' in event:
            item=event['positioned'];active=item['tool'];position=item['position']
            motion={'code':0,'tool':active,'from':position,'to':position};feed=False
        else:
            motion=replay['motions'][event['motion']];position=motion['to'];feed=motion['code']!=0
        profile=fresh_profiles[active];location='event['+str(ordinal)+'].'+active
        cuts=[]
        if not outside(motion,0.):
            if feed:cuts=cutting(motion,profile,geometry)
            else:
                # Every cutting Q_rapid piece is checked with the strict zero-
                # material predicate. Pure boundary contact is allowed ONLY
                # here, not in H's positive engineering separation below.
                if last_cut is not None and reusable_vertical_rapid(motion,last_feed,top):
                    occupancy=[last_cut];reuses+=1
                else:occupancy=rapid_cutting(motion,profile,geometry)
                for shape in occupancy:
                    geometry.unoccupied(shape,remaining,location);checks+=1
        guard_motion(motion,profile,cuts,location,feed)
        if feed:
            feeds+=1;before=geometry.mass(remaining,boundary=True)['volume']
            for shape in cuts:
                remaining=geometry.difference(remaining,shape);cut_sweeps+=1
            after=geometry.mass(remaining,boundary=True)['volume']
            prefix.append({'event':ordinal,'tool':active,'before':before,'after':after})
            if cuts and len(cuts)==1 and motion['code']==1 and motion['from'][:2]==motion['to'][:2]:
                last_feed,action=cleared_column(motion,last_feed)
                if action=='merge':last_cut=geometry.union(last_cut,cuts[0])
                elif action=='replace':last_cut=cuts[0]
            else:last_feed=last_cut=None
    residual=geometry.difference(remaining,source);gouge=geometry.difference(source,remaining)
    rm=geometry.mass(remaining,boundary=True);em=geometry.mass(residual,boundary=True);gm=geometry.mass(gouge,boundary=True)
    removed=stock_mass['volume']-rm['volume']
    conservation=abs(rm['volume']-target_mass['volume']-em['volume']+gm['volume'])
    error=math.fsum([geometry.balance_error,conservation])
    if not math.isfinite(error) or removed<0:
        fail('MATERIAL_REPLAY_FAILED','Ordered stock has nonfinite balance or negative total removal')
    # No removal centre is inferred from a union of final visits. Actual prefix
    # stock and signed first moments give the removed material's moment.
    removed_moment=[a-b for a,b in zip(stock_mass['moment'],rm['moment'])]
    record={'method':'continuous-ordered-physical-stock','stockVolume':stock_mass['volume'],
            'targetVolume':target_mass['volume'],'remainingVolume':rm['volume'],
            'remainingCentreOfMass':rm['centreOfMass'],'removedVolume':removed,
            'removedCentreOfMass':[v/removed for v in removed_moment] if removed else None,
            'residualVolume':em['volume'],'gougeVolume':gm['volume'],'balanceErrorVolume':error,
            'assessedResidualVolume':em['volume']+error,'assessedGougeVolume':gm['volume']+error,
            'conservationErrors':[conservation],'tracks':feeds,'sweeps':cut_sweeps,
            'motions':len(replay['motions']),'events':len(replay['events']),
            'toolTransitions':transitions,'clearanceChecks':checks,'temporalCredits':credits,
            'reusedRapidMasks':reuses,
            'minimumObservedGuardGap':geometry.minimum_gap,'prefixVolumes':prefix,'prospectiveWork':costs,
            'initialStateBoundary':'afterProgrammedClearancePositioningAndDeclaredToolAssignments',
            'work':{'booleans':geometry.budget.operations,'nativeFacePairs':geometry.budget.face_pairs,
                    'identityComparisons':geometry.identity_checks,'distances':geometry.distances}}
    return record,{'remaining.brep':remaining,'residual.brep':residual,'gouge.brep':gouge}
