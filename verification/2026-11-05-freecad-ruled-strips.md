# Original ruled-surface precision primitive

Qualified source: `feee40bcbde45b1a7330fefcd72753bdc42c7ac2`.
Runtime: FreeCAD 1.1.4, OCCT 7.8.1.

The numerical instrument recognizes an original BSpline surface only when its
U basis has degree one, two poles, two clamped knots and exactly equal
corresponding U-column weights. This proves that position is affine in U,
including rational V bases. The normal is affine, volume flux is affine and
first-moment fluxes are quadratic. The implementation uses the analytic norm
primitive for area and G2 for volume and moments. Full original U-span
derivative anchors avoid differencing over a tiny trim interval.

This selects from original coefficients. It does not fit or replace geometry,
change parameter charts, or relax topology, continuation, endpoint, numerical
resolution, evaluation-budget or deadline admission. A subnormal strip may
contribute zero only when its complete affine contribution bounds fit inside
its existing local target. Native floating-point error remains empirical;
there is no certified error-bound claim.

Validation on the qualified source:

- Nineteen independent native controls exercised the actual product functions,
  including a closed saddle solid with literal polynomial volume and centre,
  separately integrated area, rational V weights, transformations, changing and
  nearly parallel rulings, tiny and large original domains, continued U, exact
  unequal-weight refusal, subnormal bounds and pre-native resource faults.
- All 75 existing native accuracy controls and 32 native/STEP revolution cases
  passed, as did all 390 FreeCAD host tests.
- The public 12-turn Helix project, with output and intermediate named area,
  volume and centre measurements, passed in 102.277 seconds under the unchanged
  300-second default. Its native/STEP request used 994,532 evaluations under the
  unchanged 4,000,000 bound. Standalone verification also passed; the combined
  elapsed time was 135.775 seconds. The earlier qualified run of this project
  took 290.377 seconds before this primitive.

These results qualify this numerical primitive. The separate 24-turn boundary
completion investigation, complete Helix product qualification and the
application-wide FreeCAD inventory remain unfinished.
