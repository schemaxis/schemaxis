"""Domain guidance for declared small numeric regression models."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'R',
                'purpose':'Fit small declared numeric linear models with R stats::lm, verify them independently and judge named fit, prediction and optional coefficient-interval requirements.',
                'keywords':['statistics','statistical computing','GNU R']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':[
        'Declare numeric training rows in predictor order followed by the response, with explicit unit labels; labels do not convert units.',
        'Only an additive, unweighted, full-rank ordinary least-squares model is supported; no arbitrary formulas, categorical/missing values or external packages.',
        'Separate held-out observed rows from training. Finite error requirements assess declared rows, not future generalisation or causal effects.',
        'Optional inference reports classical standard errors, t statistics, p-values, confidence intervals, R-squared and an overall F test under independent, constant-variance, normal errors; it needs genuine residual scatter.',
        'Inspect coefficient labels and units in the summary; numeric CSV tables remain reusable in Calc. Native RDS is retained replay evidence only.'],
        'references':['docs/r.md','src/schemaxis/adaptors/r/readiness.json'],
        'operations':{'linearRegression':{'purpose':'Fit a small numeric calibration or explanatory linear model, optionally with coefficient standard errors and confidence intervals, and decide whether its declared fit/prediction/interval requirements are met.',
            'keywords':['linear regression','least squares','OLS','calibration curve','line fit','slope and intercept',
                'confidence interval','standard error','p-value','coefficient uncertainty','R-squared','F test','lm','summary.lm','confint'],
            'semantics':['Predictor columns are RMS-scaled internally and checked with independent Householder QR; coefficients are restored to authored scales.',
                'Training rows must exceed coefficient count, with full rank and a scaled infinity-norm condition at most 1e6.',
                'A fresh native process reopens model.rds and repeats coefficients, predictions and residuals. Unmet fit requirements block successful publication and workflow reuse.',
                'With inference, native summary.lm/confint values are compared with QR-derived standard errors and an independent Student-t/F evaluation; exact or roundoff-level fits are rejected as NO_RESIDUAL_VARIANCE.'],
            'examples':[{'reference':'examples/schemaxis/r-regression.json','purpose':'Known intercept10 and slope2 with independently orthogonal finite residuals and held-out observations.'},
                {'reference':'examples/schemaxis/r-regression-variant.json','purpose':'Change the known slope to3 while retaining the same training/held-out error budget.'},
                {'reference':'examples/schemaxis/r-inference.json','purpose':'Closed-form 95% slope interval 2 +/- 4.3027*sqrt(0.005) V/degC with two residual degrees of freedom, required inside [1.5, 2.5].'},
                {'reference':'examples/schemaxis/r-inference-variant.json','purpose':'Eight-point 90% calibration with slope3 and intercept10 intervals required within declared equivalence bounds.'}]}}}
