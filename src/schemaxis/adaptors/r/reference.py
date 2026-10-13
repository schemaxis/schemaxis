"""Independent column-scaled Householder QR and finite fit assessments."""
import math

from schemaxis.errors import fail

CONDITION_LIMIT = 1e6


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
            'scaledInfinityCondition':condition, 'rank':columns, 'residualDF':count-columns}


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


def assess(prepared, tables):
    assessments=[]
    for requirement in prepared.get('requirements', []):
        rows=tables[requirement['scope']]['rows']; metric=requirement['metric']
        units=prepared['response']['unit']
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
    return {'version':'schemaxis.r.acceptance/1','accepted':all(item['accepted'] for item in assessments),
            'requirements':assessments,'limits':'Finite authored rows only; no inference, causal or future-generalisation guarantee.'}
