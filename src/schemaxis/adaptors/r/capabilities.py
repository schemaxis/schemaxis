"""Domain guidance for declared small numeric regression models."""
def catalogue():
    return {'requirements':[
        'Declare numeric training rows in predictor order followed by the response, with explicit unit labels; labels do not convert units.',
        'Only an additive, unweighted, full-rank ordinary least-squares model is supported; no arbitrary formulas, categorical/missing values or external packages.',
        'Separate held-out observed rows from training. Finite error requirements assess declared rows, not future generalisation or causal effects.',
        'Inspect coefficient labels and units in the summary; numeric CSV tables remain reusable in Calc. Native RDS is retained replay evidence only.'],
        'references':['docs/r.md','src/schemaxis/adaptors/r/readiness.json'],
        'operations':{'linearRegression':{'purpose':'Fit a small numeric calibration or explanatory linear model and decide whether its declared fit/prediction requirements are met.',
            'semantics':['Predictor columns are RMS-scaled internally and checked with independent Householder QR; coefficients are restored to authored scales.',
                'Training rows must exceed coefficient count, with full rank and a scaled infinity-norm condition at most 1e6.',
                'A fresh native process reopens model.rds and repeats coefficients, predictions and residuals. Unmet fit requirements block successful publication and workflow reuse.'],
            'examples':[{'reference':'examples/schemaxis/r-regression.json','purpose':'Known intercept10 and slope2 with independently orthogonal finite residuals and held-out observations.'},
                {'reference':'examples/schemaxis/r-regression-variant.json','purpose':'Change the known slope to3 while retaining the same training/held-out error budget.'}]}}}
