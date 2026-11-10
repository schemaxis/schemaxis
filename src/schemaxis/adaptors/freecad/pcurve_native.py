"""Evaluate original rational pcurve coefficients through an exact XY embedding.

The 2D public wrapper exposes only a unit tangent. A 3D B-spline with identical
XY poles, weights and knot multiplicities supplies the actual parameter
derivative. No interpolation, fitting, conversion tolerance or native mass
routine is involved. The stdlib homogeneous evaluator remains the independent
point/derivative check and the source of bounded curve envelopes and crossings.
"""
import itertools
import math

from .gauss_green import RationalCurve, Unresolved, finite


class NativeRationalCurve(RationalCurve):
    def __init__(self, degree, knots, poles, weights, budget):
        super().__init__(degree, knots, poles, weights)
        import FreeCAD as App
        import Part
        vectors=[]
        for point in poles:
            budget.tick()
            vectors.append(App.Vector(point[0],point[1],0))
        distinct=[];multiplicities=[]
        for knot,group in itertools.groupby(self.knots):
            distinct.append(knot);multiplicities.append(sum(1 for unused in group))
        budget.check()
        curve=Part.BSplineCurve()
        # False prevents the constructor's tolerance-based rationality check
        # from discarding small but real differences between stored weights.
        try:
            curve.buildFromPolesMultsKnots(vectors,multiplicities,distinct,False,
                                          degree,weights,False)
        except Part.OCCError as error:
            raise Unresolved('native exact pcurve basis is not representable: '+str(error)) from error
        budget.check()
        if (curve.Degree!=degree or curve.isPeriodic()
                or list(curve.getKnots())!=distinct
                or list(curve.getMultiplicities())!=multiplicities
                or list(curve.getWeights())!=list(weights)
                or curve.FirstParameter!=self.start or curve.LastParameter!=self.end):
            raise Unresolved('native pcurve embedding changed original basis data')
        actual=curve.getPoles()
        if len(actual)!=len(poles) or any(p.x!=q[0] or p.y!=q[1] or p.z!=0
                                         for p,q in zip(actual,poles)):
            raise Unresolved('native pcurve embedding changed original poles')
        try:
            self._edge=curve.toShape(self.start,self.end)
        except Part.OCCError as error:
            raise Unresolved('native exact pcurve edge is not representable: '+str(error)) from error
        maximum_point=maximum_derivative=0.
        for fraction in (0.,.13,.37,.71,.91,1.):
            budget.tick()
            parameter=self.start+(self.end-self.start)*fraction
            point,derivative=RationalCurve.evaluate(self,parameter)
            observed,tangent=self.evaluate(parameter)
            maximum_point=max(maximum_point,math.dist(point,observed))
            maximum_derivative=max(maximum_derivative,
                                   max(abs(a-b) for a,b in zip(derivative,tangent)))
            if maximum_point>1e-9 or any(not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
                                        for a,b in zip(derivative,tangent)):
                raise Unresolved('native pcurve embedding differs from original homogeneous evaluation')
        self.embedding={'method':'original-coefficients-XY-embedding',
                        'basisReadbackExact':True,'pointCheck':maximum_point,
                        'derivativeCheck':maximum_derivative}
        budget.check()

    def evaluate(self, parameter):
        parameter=finite(parameter)
        if not self.start<=parameter<=self.end:
            raise Unresolved('rational evaluation outside its domain')
        point=self._edge.valueAt(parameter)
        derivative=self._edge.derivative1At(parameter)
        return ([finite(point.x),finite(point.y)],
                [finite(derivative.x),finite(derivative.y)])
