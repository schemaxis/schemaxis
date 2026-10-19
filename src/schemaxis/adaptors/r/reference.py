"""Independent column-scaled Householder QR, classical OLS inference and finite fit assessments."""
import math

from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail

CONDITION_LIMIT = 1e6
# Inference needs a residual standard error well above the native comparison
# roundoff allowance; otherwise standard errors, t and p are numerical noise.
VARIANCE_RATIO = 1e6
INFERENCE_RELATIVE = 1e-4
DISTRIBUTION_RELATIVE = 1e-10
SQUARE_FLOOR = 1e-280


def _unsupported(code, message, location, recovery, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def response_tolerance(rows, condition):
    """Absolute response-unit roundoff allowance for native/independent comparison."""
    return 128*math.ulp(max(abs(row[-1]) for row in rows))*max(1, condition)


def decompose(rows, intercept):
    width = len(rows[0]) - 1
    raw = [([1.0] if intercept else []) + row[:width] for row in rows]
    count, columns = len(raw), len(raw[0])
    scales = [math.hypot(*(row[j] for row in raw)) / math.sqrt(count) for j in range(columns)]
    if any(scale == 0 for scale in scales):
        fail('RANK_DEFICIENT_DATA', 'every design column needs independent nonzero information', '$.training')
    matrix = [[value / scale for value, scale in zip(row, scales)] for row in raw]
    original = [row[:] for row in matrix]
    reflectors = []
    for column in range(columns):
        vector = [matrix[i][column] for i in range(column, count)]
        norm = math.hypot(*vector)
        if norm <= 1e-10 * math.sqrt(count):
            fail('RANK_DEFICIENT_DATA', 'predictors must form a full-rank design with the chosen intercept', '$.training')
        alpha = -math.copysign(norm, vector[0])
        vector[0] -= alpha
        normaliser = math.hypot(*vector)
        vector = [value / normaliser for value in vector]
        for j in range(column, columns):
            projection = 2 * math.fsum(vector[k] * matrix[column+k][j] for k in range(len(vector)))
            for k, value in enumerate(vector): matrix[column+k][j] -= projection * value
        reflectors.append((column, vector))
    def solve(response):
        transformed = list(response)
        for column, vector in reflectors:
            projection = 2 * math.fsum(value * transformed[column+k] for k, value in enumerate(vector))
            for k, value in enumerate(vector): transformed[column+k] -= projection * value
        result = [0.0] * columns
        for i in range(columns-1, -1, -1):
            result[i] = (transformed[i] - math.fsum(matrix[i][j]*result[j] for j in range(i+1,columns))) / matrix[i][i]
        return result
    # Actual infinity-norm condition of the scaled rectangular design:
    # ||A||_inf * ||A^+||_inf. A^+ columns come from solving each unit vector.
    inverse_rows = [0.0] * columns
    for i in range(count):
        unit = [0.0] * count; unit[i] = 1.0
        for j, value in enumerate(solve(unit)): inverse_rows[j] += abs(value)
    condition = max(math.fsum(map(abs,row)) for row in original) * max(inverse_rows)
    if not math.isfinite(condition) or condition > CONDITION_LIMIT:
        fail('ILL_CONDITIONED_DATA', 'column-scaled infinity-norm condition exceeds 1e6; use independent predictors and a better-supported design',
             '$.training', observedCondition=condition, maximumCondition=CONDITION_LIMIT)
    scaled = solve([row[-1] for row in rows])
    coefficients = [value / scale for value, scale in zip(scaled, scales)]
    if any(not math.isfinite(value) or abs(value)>1e100 for value in coefficients):
        fail('ILL_CONDITIONED_DATA', 'coefficient magnitude is not representable within the numeric table limit', '$.training')
    return {'scales':scales, 'scaledCoefficients':scaled, 'coefficients':coefficients,
            'scaledInfinityCondition':condition, 'rank':columns, 'residualDF':count-columns,
            'triangular':[row[:columns] for row in matrix[:columns]]}


def predicted(prepared, row, coefficients):
    features = ([1.0] if prepared['intercept'] else []) + row[:-1]
    products=[value*coefficient for value,coefficient in zip(features,coefficients)]
    if any(not math.isfinite(value) for value in products):
        fail('INVALID_PREDICTION','coefficient-feature product is not finite','$.heldout')
    try:return math.fsum(products)
    except (OverflowError,ValueError):fail('INVALID_PREDICTION','projected prediction is not representable','$.heldout')


def metrics(rows):
    errors = [row[3] for row in rows]
    worst = max(range(len(rows)), key=lambda i:abs(errors[i]))
    return {'rmse':math.hypot(*errors)/math.sqrt(len(errors)),
            'maxAbsoluteError':abs(errors[worst]), 'worstSampleIndex':worst}


def _fraction(a, b, x):
    """Modified Lentz continued fraction for the regularized incomplete beta."""
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a+b)*x/(a+1)
    d = 1/(d if abs(d) >= tiny else tiny); value = d
    for m in range(1, 10001):
        for numerator in (m*(b-m)*x/((a+2*m-1)*(a+2*m)), -(a+m)*(a+b+m)*x/((a+2*m)*(a+2*m+1))):
            d = 1 + numerator*d; d = 1/(d if abs(d) >= tiny else tiny)
            c = 1 + numerator/c; c = c if abs(c) >= tiny else tiny
            step = c*d; value *= step
        if abs(step-1) <= 4*2.0**-52:
            return value
    fail('VERIFICATION_FAILED', 'independent distribution evaluation did not converge', '$.inference')


def regularized_beta(a, b, x, y):
    """I_x(a,b) with y=1-x supplied separately to avoid cancellation."""
    if x <= 0: return 0.0
    if y <= 0: return 1.0
    log_x = math.log1p(-y) if x > .5 else math.log(x)
    log_y = math.log1p(-x) if y > .5 else math.log(y)
    front = a*log_x + b*log_y - (math.lgamma(a)+math.lgamma(b)-math.lgamma(a+b))
    if x < (a+1)/(a+b+2):
        return math.exp(front)*_fraction(a, b, x)/a
    return 1 - math.exp(front)*_fraction(b, a, y)/b


def t_two_sided(t, df):
    """P(|T| >= |t|) for Student's t with df degrees of freedom."""
    ratio = abs(t)/math.sqrt(df)
    if ratio == 0: return 1.0
    square = ratio*ratio
    if not math.isfinite(square): return 0.0
    return regularized_beta(df/2, .5, 1/(1+square), square/(1+square))


def f_upper(f, numerator, denominator):
    """P(F >= f) for Fisher's F with the stated degrees of freedom."""
    if f <= 0: return 1.0
    scaled = numerator*f/denominator
    if not math.isfinite(scaled): return 0.0
    return regularized_beta(denominator/2, numerator/2, 1/(1+scaled), scaled/(1+scaled))


def t_quantile(level, df):
    """Two-sided critical value q with P(|T| >= q) = 1-level, by monotone bisection."""
    target = 1-level; low, high = 0.0, 1.0
    while t_two_sided(high, df) > target: low, high = high, 2*high
    for _ in range(400):
        middle = (low+high)/2
        if not low < middle < high: break
        if t_two_sided(middle, df) > target: low = middle
        else: high = middle
    return (low+high)/2


def residual_variance(prepared, independent):
    """Residuals, residual standard error and the inference support guards."""
    rows = prepared['training']; df = independent['residualDF']
    fitted = [predicted(prepared, row, independent['coefficients']) for row in rows]
    residuals = [row[-1]-value for row, value in zip(rows, fitted)]
    norm = math.hypot(*residuals); sigma = norm/math.sqrt(df)
    floor = VARIANCE_RATIO*response_tolerance(rows, independent['scaledInfinityCondition'])
    if not sigma >= floor:
        _unsupported('NO_RESIDUAL_VARIANCE', 'training residuals are zero or indistinguishable from numerical roundoff, so standard errors, t, p and confidence intervals are undefined',
             '$.inference', 'Remove inference for an exact or synthetic fit, or supply observations with genuine measured scatter and more rows than coefficients.',
             residualStandardError=sigma, minimumResidualStandardError=floor)
    if norm*norm < SQUARE_FLOOR:
        _unsupported('UNSUPPORTED_INFERENCE', 'residual sum of squares is below 1e-280 and cannot be compared reliably in floating point',
             '$.training', 'Express the response in larger units and rerun.', residualSumOfSquares=norm*norm)
    return fitted, residuals, norm, sigma


def inference(prepared, independent):
    """Classical OLS inference from the independent QR factor only (never native values).

    SE_j = sigma*sqrt(diag((R^T R)^-1)); t_j = b_j/SE_j; two-sided Student-t
    p-values; b_j -/+ t_{1-(1-level)/2,df}*SE_j intervals. R^2 = MSS/(MSS+RSS),
    centred on the mean fitted value with an intercept and on zero without one.
    """
    fitted, residuals, norm, sigma = residual_variance(prepared, independent)
    count = len(fitted); df = independent['residualDF']; columns = independent['rank']
    triangular = independent['triangular']; inverse = [[0.0]*columns for _ in range(columns)]
    for j in range(columns):
        inverse[j][j] = 1/triangular[j][j]
        for i in range(j-1, -1, -1):
            inverse[i][j] = -math.fsum(triangular[i][k]*inverse[k][j] for k in range(i+1, j+1))/triangular[i][i]
    level = prepared['inference']['level']; critical = t_quantile(level, df)
    coefficients = []
    for j, estimate in enumerate(independent['scaledCoefficients']):
        error = sigma*math.hypot(*inverse[j]); statistic = estimate/error
        coefficients.append({'scaledEstimate':estimate, 'scaledStandardError':error, 'tStatistic':statistic,
            'pValue':t_two_sided(statistic, df), 'scaledLower':estimate-critical*error, 'scaledUpper':estimate+critical*error})
    centre = math.fsum(fitted)/count if prepared['intercept'] else 0.0
    explained = math.hypot(*(value-centre for value in fitted)); numerator = len(prepared['predictors'])
    ratio = (explained/norm)**2
    r_squared = ratio/(1+ratio)
    adjusted = 1-(1-r_squared)*(count-int(prepared['intercept']))/df
    statistic = ratio*df/numerator
    return {'level':level, 'residualDF':df, 'criticalValue':critical, 'sigma':sigma,
            'rSquared':r_squared, 'adjustedRSquared':adjusted, 'fStatistic':statistic,
            'fNumeratorDF':numerator, 'fDenominatorDF':df, 'fPValue':f_upper(statistic, numerator, df),
            'coefficients':coefficients}


def within(native, low, high):
    """Interval check with evaluation slack for independently propagated p-values."""
    return low*(1-DISTRIBUTION_RELATIVE)-1e-300 <= native <= high*(1+DISTRIBUTION_RELATIVE)+1e-300


def compare_inference(native, expected, tolerance):
    """Return the first differing native inference quantity, or None.

    Tolerances follow from the residual-variance guard: response roundoff below
    1e-6*sigma bounds relative sigma/SE/F error far below INFERENCE_RELATIVE.
    p-values are checked against the independent monotone image of the t/F
    tolerance interval, not with a fixed absolute threshold.
    """
    relative = INFERENCE_RELATIVE
    if native['level'] != expected['level']: return 'level'
    for key in ('residualDF', 'fNumeratorDF', 'fDenominatorDF'):
        if native[key] != expected[key]: return key
    if not math.isclose(native['criticalValue'], expected['criticalValue'], rel_tol=DISTRIBUTION_RELATIVE): return 'criticalValue'
    if not math.isclose(native['sigma'], expected['sigma'], rel_tol=relative): return 'sigma'
    for key in ('rSquared', 'adjustedRSquared'):
        if abs(native[key]-expected[key]) > relative*(1-expected[key])+1e-15: return key
    f, df = expected['fStatistic'], expected['residualDF']
    spread = relative*f+relative*math.sqrt(f)
    if abs(native['fStatistic']-f) > spread: return 'fStatistic'
    if not within(native['fPValue'], f_upper(f+spread, expected['fNumeratorDF'], df), f_upper(max(f-spread, 0), expected['fNumeratorDF'], df)):
        return 'fPValue'
    if len(native['coefficients']) != len(expected['coefficients']): return 'coefficients'
    for actual, item in zip(native['coefficients'], expected['coefficients']):
        estimate, error = item['scaledEstimate'], item['scaledStandardError']
        absolute = 1e-10*abs(estimate)+tolerance; half = expected['criticalValue']*error
        if not math.isclose(actual['scaledEstimate'], estimate, rel_tol=1e-10, abs_tol=tolerance): return 'scaledEstimate'
        if not math.isclose(actual['scaledStandardError'], error, rel_tol=relative): return 'scaledStandardError'
        statistic = abs(item['tStatistic']); spread = relative*statistic+absolute/error
        if abs(actual['tStatistic']-item['tStatistic']) > spread: return 'tStatistic'
        if not within(actual['pValue'], t_two_sided(statistic+spread, df), t_two_sided(max(statistic-spread, 0), df)): return 'pValue'
        for key in ('scaledLower', 'scaledUpper'):
            if abs(actual[key]-item[key]) > absolute+relative*half: return key
    return None


def coefficient_units(prepared):
    response = prepared['response']['unit']
    return ([response] if prepared['intercept'] else [])+[response+'/'+p['unit'] for p in prepared['predictors']]


def assess(prepared, tables, inferred=None):
    assessments=[]
    for requirement in prepared.get('requirements', []):
        metric=requirement['metric']; units=prepared['response']['unit']
        if metric=='coefficientInterval':
            assessments.append(_interval_assessment(prepared, requirement, inferred));continue
        rows=tables[requirement['scope']]['rows']
        if metric=='prediction':
            index=requirement['sampleIndex']; actual=rows[index][2]
            worst={'sampleIndex':index,'predictors':prepared[requirement['scope']][index][:-1],
                   'observed':rows[index][1],'prediction':actual,'residual':rows[index][3]}
        else:
            measured=metrics(rows);actual=measured[metric];index=measured['worstSampleIndex']
            worst={'sampleIndex':index,'predictors':prepared[requirement['scope']][index][:-1],
                   'observed':rows[index][1],'prediction':rows[index][2],'residual':rows[index][3]}
        checks=[]
        for bound in ('minimum','maximum'):
            if bound not in requirement:continue
            margin=actual-requirement[bound] if bound=='minimum' else requirement[bound]-actual
            checks.append({'bound':bound,'expected':requirement[bound],'observed':actual,'margin':margin,'passed':margin>=0})
        accepted=all(check['passed'] for check in checks)
        assessments.append({**requirement,'units':units,'observed':actual,'checks':checks,'accepted':accepted,
            'worstCondition':worst,'coverage':'Aggregate error over the declared rows.' if metric=='rmse' else 'Only the declared rows or selected prediction.',
            'nextAction':'Accept this finite requirement.' if accepted else 'Inspect the observed error or prediction and declared sample; revise the model/data or justified bound and rerun a fresh attempt.'})
    limits=('Finite authored rows only; no inference, causal or future-generalisation guarantee.' if 'inference' not in prepared else
        'Error/prediction requirements cover finite authored rows only. Coefficient intervals hold only under the stated OLS assumptions; no causal or future-generalisation guarantee.')
    return {'version':'schemaxis.r.acceptance/1','accepted':all(item['accepted'] for item in assessments),
            'requirements':assessments,'limits':limits}


def _interval_assessment(prepared, requirement, inferred):
    names=(['intercept'] if prepared['intercept'] else [])+[p['name'] for p in prepared['predictors']]
    index=names.index(requirement['term']); item=inferred['coefficients'][index]
    observed={'estimate':item['estimate'],'lower':item['lower'],'upper':item['upper']}
    checks=[]
    for bound,key in (('minimum','lower'),('maximum','upper')):
        if bound not in requirement:continue
        margin=item[key]-requirement[bound] if bound=='minimum' else requirement[bound]-item[key]
        checks.append({'bound':bound,'expected':requirement[bound],'observed':item[key],'margin':margin,'passed':margin>=0})
    accepted=all(check['passed'] for check in checks)
    binding=min(checks,key=lambda check:check['margin'])['bound']
    level=inferred['level']
    return {**requirement,'units':coefficient_units(prepared)[index],'observed':observed,'checks':checks,'accepted':accepted,
        'worstCondition':{'term':requirement['term'],'binding':binding,'estimate':item['estimate'],'standardError':item['standardError'],
            'criticalValue':inferred['criticalValue'],'level':level,'residualDF':inferred['residualDF']},
        'coverage':f'Two-sided {level:g} Student-t confidence interval from training residuals; each declared bound is a one-sided test at {(1-level)/2:g} under the stated assumptions.',
        'nextAction':'Accept this coefficient interval requirement.' if accepted else
            'The confidence interval crosses a declared bound: the estimate may be displaced or too imprecise. Review residuals and assumptions; add genuinely independent observations or revise a justified bound, then rerun a fresh attempt.'}
