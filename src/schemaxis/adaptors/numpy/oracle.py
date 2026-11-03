# Copyright (C) 2026 David L F Gaden
"""Independent standard-library PCA oracle and saved verifier for schemaxis.numpy/1.

Never imports NumPy. Expected values come from correctly rounded sums (math.fsum), a
separately implemented cyclic Jacobi eigensolver and residual-based bounds.

Two kinds of tolerance are named differently:
- qualification budgets (tauLambda, tauTotal, ...) are declared empirical acceptance budgets
  for agreement between native NumPy and this oracle; they are not proven LAPACK bounds;
- a posteriori bounds (eigenvalue errors, loading sine angles alpha, retained-subspace
  distance beta) are derived from residuals computed here. Their floating-point evaluation
  uses first-order rounding allowances, not interval arithmetic.
"""
import csv
import hashlib
import io
import math
import re
import struct

from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail

U = 2.0**-53
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?')
INTEGER = re.compile(r'[0-9]+')
LIMITS = {'minRows': 3, 'maxRows': 10000, 'minChannels': 2, 'maxChannels': 32, 'maxCells': 160000,
          'maxComponents': 10, 'maxBytes': 8 * 1024 * 1024, 'rawMin': 1e-48, 'rawMax': 1e48,
          'scaledSpreadMin': 1e-48, 'scaledSpreadMax': 1e48, 'handoff': 1e100, 'maxOffsetRatio': 1e6}
HANDOFF = LIMITS['handoff']
SPECTRAL_CODES = ('PCA_COMPONENT_BELOW_RESOLUTION', 'PCA_DEGENERATE_COMPONENT', 'PCA_RETENTION_SPLITS_CLUSTER',
                  'PCA_SPECTRUM_BORDERLINE', 'PCA_RETENTION_BORDERLINE', 'PCA_RETENTION_UNREACHABLE')


def raise_fault(code, message, location, recovery=None, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


# ---------------------------------------------------------------- strict CSV grammar (app-owned)

def cell(text, location):
    if text == '':
        fail('PCA_MISSING_VALUE', 'every cell needs a value; missing values are not imputed', location)
    if not NUMBER.fullmatch(text):
        fail('PCA_INVALID_NUMBER', 'use plain decimal numbers without spaces, signs of infinity, nan, hex or digit separators', location)
    value = float(text)
    if not math.isfinite(value) or abs(value) > LIMITS['rawMax'] or (value != 0 and abs(value) < LIMITS['rawMin']):
        fail('PCA_VALUE_RANGE', 'raw values must be zero or have binary64 magnitude within [1e-48, 1e48]', location)
    return value


def parse(data, config):
    """Return (keys or None, rows) from captured bytes, refusing at the first fault in scan order."""
    if len(data) > LIMITS['maxBytes']:
        fail('PCA_RESOURCE_LIMIT', 'source exceeds 8 MiB', '$.source')
    try:
        text = data.decode('ascii')
    except UnicodeDecodeError:
        fail('PCA_INVALID_CSV', 'source must be ASCII (no byte-order mark)', '$.source')
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    lines = [line[:-1] if line.endswith('\r') else line for line in lines]
    if not lines:
        fail('PCA_INVALID_CSV', 'empty source', '$.source')
    header, keyed = config['header'], config['keyed']
    keys, rows = [], []
    for number, line in enumerate(lines, 1):
        if '"' in line or '\r' in line:
            fail('PCA_INVALID_CSV', 'quoted cells and bare carriage returns are not accepted', f'line {number}')
        if line == '':
            fail('PCA_INVALID_CSV', 'blank lines are not accepted', f'line {number}')
        cells = line.split(',')
        if number == 1:
            if cells != header:
                fail('PCA_HEADER_MISMATCH', 'header must equal the declared row key and channels in order', 'line 1',
                     expected=header)
            continue
        if len(cells) != len(header):
            fail('PCA_INVALID_CSV', 'ragged row', f'line {number}')
        if number - 1 > LIMITS['maxRows']:
            fail('PCA_DIMENSIONS', 'more than 10000 data rows', f'line {number}')
        values = [cell(v, f'line {number} column {j + 1}') for j, v in enumerate(cells)]
        if keyed:
            if keys and not values[0] > keys[-1]:
                fail('PCA_ROW_KEY_ORDER', 'row key must increase strictly', f'line {number}')
            keys.append(values[0])
            values = values[1:]
        rows.append(values)
    n, p = len(rows), len(config['channels'])
    if n < LIMITS['minRows'] or n * p > LIMITS['maxCells']:
        fail('PCA_DIMENSIONS', 'need 3-10000 rows and at most 160000 analysed cells', '$.source', rows=n)
    return (keys if keyed else None), rows


def array_digest(rows):
    """Digest of little-endian float64 values in row-major order; matches the native readback."""
    h = hashlib.sha256()
    for row in rows:
        h.update(struct.pack('<%dd' % len(row), *row))
    return h.hexdigest()


# ---------------------------------------------------------------- statistics and spectrum

def dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def statistics(rows, config):
    n, p = len(rows), len(rows[0])
    cols = [[r[j] for r in rows] for j in range(p)]
    means = [math.fsum(col) / n for col in cols]
    sds = [math.sqrt(math.fsum((x - m) * (x - m) for x in col) / (n - 1)) for col, m in zip(cols, means)]
    peaks = [max(abs(x) for x in col) for col in cols]
    names = [c['name'] for c in config['channels']]
    for j, (s, peak) in enumerate(zip(sds, peaks)):
        if s == 0 or peak > LIMITS['maxOffsetRatio'] * s:
            fail('PCA_CHANNEL_SPREAD', 'channel spread is zero or below 1e-6 of its largest magnitude', f'$.channels[{j}]',
                 channel=names[j], spread=s, peak=peak)
    mode = config['scaling']
    scales = ([1.0] * p if mode == 'none' else sds if mode == 'standardise'
              else [float(c['scale']) for c in config['channels']])
    ratios = [s / sc for s, sc in zip(sds, scales)]
    for j, r in enumerate(ratios):
        if not LIMITS['scaledSpreadMin'] <= r <= LIMITS['scaledSpreadMax']:
            fail('PCA_SCALE_RANGE', 'scaled spread sd/scale must lie within [1e-48, 1e48]', f'$.channels[{j}]',
                 channel=names[j], ratio=r)
    z = [[(x - m) / s for x, m, s in zip(r, means, scales)] for r in rows]
    zc = [[r[j] for r in z] for j in range(p)]
    cov = covariance(zc, n)
    total = math.fsum(cov[j][j] for j in range(p))
    return {'n': n, 'p': p, 'means': means, 'sds': sds, 'scales': scales, 'cov': cov, 'total': total,
            'peaks': peaks, 'ratios': ratios}


def covariance(columns, n):
    """fsum covariance; each symmetric pair is assigned from one computed value."""
    p = len(columns)
    cov = [[0.0] * p for _ in range(p)]
    for a in range(p):
        for b in range(a, p):
            cov[a][b] = cov[b][a] = math.fsum(x * y for x, y in zip(columns[a], columns[b])) / (n - 1)
    return cov


def jacobi(a, sweeps=60):
    """Cyclic two-sided Jacobi with Rutishauser's rotation (Golub & Van Loan, sym.schur2).
    Stops when every |a_pq| <= u*sqrt(|a_pp a_qq|) or below 1e-3*u*||A||_F."""
    p = len(a)
    a = [row[:] for row in a]
    v = [[float(i == j) for j in range(p)] for i in range(p)]
    floor = 1e-3 * U * math.sqrt(math.fsum(x * x for row in a for x in row))
    for sweep in range(1, sweeps + 1):
        rotated = 0
        for i in range(p - 1):
            for j in range(i + 1, p):
                aij = a[i][j]
                if abs(aij) <= max(U * math.sqrt(abs(a[i][i] * a[j][j])), floor):
                    continue
                theta = (a[j][j] - a[i][i]) / (2 * aij)
                t = math.copysign(1.0, theta) / (abs(theta) + math.hypot(theta, 1.0))
                cs = 1 / math.hypot(t, 1.0)
                sn = t * cs
                for k in range(p):
                    if k != i and k != j:
                        aki, akj = a[k][i], a[k][j]
                        a[k][i] = a[i][k] = cs * aki - sn * akj
                        a[k][j] = a[j][k] = sn * aki + cs * akj
                a[i][i] -= t * aij
                a[j][j] += t * aij
                a[i][j] = a[j][i] = 0.0
                for k in range(p):
                    vki, vkj = v[k][i], v[k][j]
                    v[k][i] = cs * vki - sn * vkj
                    v[k][j] = sn * vki + cs * vkj
                rotated += 1
        if rotated == 0:
            order = sorted(range(p), key=lambda i: -a[i][i])
            return [a[i][i] for i in order], [[v[k][i] for k in range(p)] for i in order], sweep
    fail('VERIFICATION_FAILED', 'independent Jacobi did not converge in 60 sweeps')


def certified(a, values, vectors):
    """A posteriori eigenvalue bounds for symmetric `a` from an approximate full decomposition.

    Hypotheses: `a` is exactly symmetric as stored; V has the given rows as columns; Lambda is
    diagonal. With R = A V - V Lambda and omega = ||V^T V - I||_F < 1:
      ||A - V Lambda V^T||_2 <= ||R||_F sqrt(1+omega) + ||A||_F omega  (since ||I - V V^T|| <= omega)
      eig(V Lambda V^T) = Lambda_i theta_i, theta_i in [1-omega, 1+omega]  (Ostrowski)
    hence |lambda_i(A) - Lambda_i| <= ||R||_F sqrt(1+omega) + ||A||_F omega + omega |Lambda_i| (Weyl).
    ||R||_F and omega are evaluated with fsum plus first-order product-rounding allowances."""
    p = len(a)
    norm_a = math.sqrt(math.fsum(x * x for row in a for x in row))
    r2, allow2, resid = [], [], []
    for lam, vec in zip(values, vectors):
        rk = []
        for i in range(p):
            prods = [a[i][j] * vec[j] for j in range(p)]
            r = math.fsum(prods + [-lam * vec[i]])
            rk.append(r)
            r2.append(r * r)
            allow2.append((2 * U * (math.fsum(abs(x) for x in prods) + abs(lam * vec[i]))) ** 2)
        resid.append(math.sqrt(math.fsum(x * x for x in rk)))
    rf = math.sqrt(math.fsum(r2)) + math.sqrt(math.fsum(allow2))
    m = len(vectors)
    omega = math.sqrt(math.fsum((dot(vectors[i], vectors[j]) - (i == j)) ** 2
                                for i in range(m) for j in range(m))) + 2 * (p + 2) * U * m
    if omega >= 1:
        return {'residualF': rf, 'omega': omega, 'errors': [math.inf] * m, 'vectorResidual': resid, 'normF': norm_a}
    errors = [(rf * math.sqrt(1 + omega) + norm_a * omega + omega * abs(lam)) * (1 + 16 * U) for lam in values]
    return {'residualF': rf, 'omega': omega, 'errors': errors, 'vectorResidual': resid, 'normF': norm_a}


def policy(n, p, total, eta, sweeps=12):
    """Qualification budgets and the resolution policy shared with the native worker.
    cTau sets the resolution threshold and borderline band; cCompare widens only the
    comparison budget when the oracle needed more than its 12-sweep allowance."""
    c_tau = 16 + 48 * p + 8 * (n + p)
    c_cmp = 16 + 4 * p * max(12, sweeps) + 8 * (n + p)
    g_min = 4 * c_tau * U / eta
    return {'cTau': c_tau, 'cCompare': c_cmp, 'tauLambda': c_cmp * U * total, 'gMin': g_min,
            'gapThreshold': g_min * total, 'band': 2 * c_tau * U * total, 'tauFraction': 2 * p * c_tau * U,
            'tauTotal': 2 * (n * p + 4) * U * total}


def decide(values, config, tol, band):
    """Declared retention/degeneracy rule on a descending eigenvalue list of length p.
    Returns (K, None) or (None, (code, details))."""
    p = len(values)
    theta = tol['gapThreshold']
    retention = config['retention']
    if 'components' in retention:
        k = retention['components']
    else:
        f = retention['minimumExplainedVariance']
        whole = math.fsum(values)
        k = None
        for i in range(1, min(p, LIMITS['maxComponents']) + 1):
            frac = math.fsum(values[:i]) / whole
            if abs(frac - f) <= tol['tauFraction'] * (band / tol['band']):
                return None, ('PCA_RETENTION_BORDERLINE', {'component': i, 'cumulativeFraction': frac})
            if frac >= f:
                k = i
                break
        if k is None:
            return None, ('PCA_RETENTION_UNREACHABLE', {'maximumComponents': LIMITS['maxComponents']})
    lam = list(values) + [0.0]

    def test(q, code, at):
        if abs(q - theta) <= band:
            return ('PCA_SPECTRUM_BORDERLINE', {'component': at, 'quantity': q, 'threshold': theta})
        if q < theta:
            return (code, {'component': at, 'quantity': q, 'threshold': theta})
        return None

    if config['output'] == 'components':
        for i in range(k):
            for q, code in ((lam[i], 'PCA_COMPONENT_BELOW_RESOLUTION'),
                            *(((lam[i - 1] - lam[i], 'PCA_DEGENERATE_COMPONENT'),) if i > 0 else ()),
                            *(((lam[i] - lam[i + 1], 'PCA_DEGENERATE_COMPONENT'),) if i + 1 < p else ())):
                fault = test(q, code, i + 1)
                if fault:
                    return None, fault
    else:
        fault = test(lam[k - 1], 'PCA_COMPONENT_BELOW_RESOLUTION', k)
        if not fault and k < p:
            fault = test(lam[k - 1] - lam[k], 'PCA_RETENTION_SPLITS_CLUSTER', k)
        if fault:
            return None, fault
    return k, None


def anchor(vec, eta):
    peak = max(abs(x) for x in vec)
    return next(i for i, x in enumerate(vec) if abs(x) >= peak - 2 * eta)


def gram_schmidt(vectors):
    q = []
    for v in vectors:
        w = list(v)
        for _ in range(2):                       # twice is enough (Kahan-Parlett)
            for e in q:
                d = dot(e, w)
                w = [x - d * y for x, y in zip(w, e)]
        nrm = math.sqrt(math.fsum(x * x for x in w))
        q.append([x / nrm for x in w])
    return q


def predict(config, data):
    """Host prediction from captured bytes: parse, statistics, spectrum and declared decision."""
    keys, rows = parse(data, config)
    st = statistics(rows, config)
    values, vectors, sweeps = jacobi(st['cov'])
    tol = policy(st['n'], st['p'], st['total'], config['loadingTolerance'], sweeps)
    k, fault = decide(values, config, tol, tol['band'])
    return {'keys': keys, 'rows': rows, 'stats': st, 'values': values, 'vectors': vectors,
            'sweeps': sweeps, 'tol': tol, 'K': k, 'fault': fault}


def within_band(prediction, config, band):
    k, fault = decide(prediction['values'], config, prediction['tol'], band)
    return fault is not None and fault[0] in ('PCA_SPECTRUM_BORDERLINE', 'PCA_RETENTION_BORDERLINE')


def three_state(m, t, b):
    if t is None or not math.isfinite(t):
        return 'indeterminate'
    return 'met' if m + t <= b else 'unmet' if m - t > b else 'indeterminate'


def scaled_rms(values, n):
    peak = max((abs(x) for x in values), default=0.0)
    return 0.0 if peak == 0 else peak * math.sqrt(math.fsum((x / peak) ** 2 for x in values) / n)


def finite_or_none(x):
    return x if math.isfinite(x) and abs(x) <= HANDOFF else None


# ---------------------------------------------------------------- reading native publications

def read_table(name, data, header, integer_first):
    try:
        rows = list(csv.reader(io.StringIO(data.decode('ascii')), strict=True))
    except (UnicodeDecodeError, csv.Error) as error:
        fail('VERIFICATION_FAILED', 'published table is not strict ASCII CSV: ' + str(error), name)
    if not rows or rows[0] != header:
        fail('VERIFICATION_FAILED', 'published table header differs', name, expected=header, actual=rows[0] if rows else None)
    out = []
    for i, r in enumerate(rows[1:], 1):
        if len(r) != len(header) or not all(NUMBER.fullmatch(x) for x in r):
            fail('VERIFICATION_FAILED', 'published table row is ragged or not numeric', f'{name} row {i}')
        if integer_first and not INTEGER.fullmatch(r[0]):
            fail('VERIFICATION_FAILED', 'published index column is not an integer literal', f'{name} row {i}')
        values = [float(x) for x in r]
        if not all(math.isfinite(v) and abs(v) <= HANDOFF for v in values):
            fail('VERIFICATION_FAILED', 'published value is non-finite or outside +/-1e100', f'{name} row {i}')
        out.append(values)
    return out


def table_layout(config, retained):
    names = [c['name'] for c in config['channels']]
    keyname = config['header'][0] if config['keyed'] else 'row'
    files = {'spectrum.csv': (['component', 'eigenvalue', 'varianceFraction', 'cumulativeFraction'], True)}
    if config['output'] == 'components':
        files['loadings.csv'] = (['component', *names], True)
        files['scores.csv'] = ([keyname] + [f'PC{i}' for i in range(1, retained + 1)], not config['keyed'])
    else:
        files['projector.csv'] = (['channelIndex', *names], True)
    files['reconstruction.csv'] = ([keyname, *names], not config['keyed'])
    return files


# ---------------------------------------------------------------- verification

class Ledger:
    """Fail-closed check ledger: the first failed check raises; passing margins are retained."""
    def __init__(self):
        self.items = []

    def check(self, layer, name, ok, value=None, bound=None, location='$'):
        for x in (value, bound):
            if type(x) is float and not math.isfinite(x):
                ok = False
        if not ok:
            fail('VERIFICATION_FAILED', 'independent verification failed: ' + name, location,
                 layer=layer, value=finite_or_none(value) if type(value) is float else value,
                 bound=finite_or_none(bound) if type(bound) is float else bound)
        if type(value) in (int, float) and type(bound) in (int, float) and not isinstance(value, bool):
            self.items.append({'layer': layer, 'check': name, 'value': value, 'bound': bound})


def assess(config, data, summary, publications):
    """Recompute every host decision from captured bytes and published bytes.

    `publications` maps CSV file names to bytes. Returns a deterministic JSON assessment.
    Raises VERIFICATION_FAILED for any disagreement; certification and requirement outcomes are
    returned (not raised) so the run can retain them as evidence before refusing."""
    try:
        pred = predict(config, data)
    except SchemaxisError as error:
        fail('VERIFICATION_FAILED', 'published result for input the host refuses: ' + error.fault.code, error.fault.location)
    st, tol = pred['stats'], pred['tol']
    n, p = st['n'], st['p']
    eta = config['loadingTolerance']
    names = [c['name'] for c in config['channels']]
    keys = pred['keys'] if config['keyed'] else [float(i) for i in range(1, n + 1)]
    ledger = Ledger()
    K = summary.get('retained')
    ledger.check('L0', 'retained component count is an integer in 1..p', type(K) is int and 1 <= K <= p, location='pca-summary.json')
    layout = table_layout(config, K)
    if set(publications) != set(layout):
        fail('VERIFICATION_FAILED', 'published table membership differs', 'publications',
             expected=sorted(layout), actual=sorted(publications))
    tables = {name: read_table(name, publications[name], header, integer)
              for name, (header, integer) in layout.items()}
    ledger.check('L0', 'summary source digest equals captured bytes', summary['source']['sha256'] == hashlib.sha256(data).hexdigest())
    ledger.check('L0', 'native parsed float64 digest equals independent parse', summary['parsedDigest'] == array_digest(pred['rows']))
    spec, rec = tables['spectrum.csv'], tables['reconstruction.csv']
    lam = [r[1] for r in spec]
    mu, scale = summary['means'], summary['scales']
    ledger.check('L0', 'spectrum has p rows indexed 1..p', [r[0] for r in spec] == [float(i) for i in range(1, p + 1)], location='spectrum.csv')
    ledger.check('L0', 'reconstruction keys equal source keys in order', len(rec) == n and [r[0] for r in rec] == keys, location='reconstruction.csv')
    ledger.check('L0', 'unit, scaling and denominator metadata', summary['scaling'] == config['scaling']
                 and summary['varianceDenominator'] == 'n-1' and summary['units'] == [c['unit'] for c in config['channels']]
                 and summary['output'] == config['output'], location='pca-summary.json')
    ledger.check('L0', 'means and scales are p finite numbers with positive scales', len(mu) == p and len(scale) == p
                 and all(type(x) in (int, float) and math.isfinite(x) for x in mu + scale) and all(s > 0 for s in scale),
                 location='pca-summary.json')
    V = P = None
    if config['output'] == 'components':
        load, scores = tables['loadings.csv'], tables['scores.csv']
        V = [r[1:] for r in load]
        ledger.check('L0', 'loadings rows are components 1..K', [r[0] for r in load] == [float(i) for i in range(1, K + 1)], location='loadings.csv')
        ledger.check('L0', 'score keys equal source keys in order', len(scores) == n and [r[0] for r in scores] == keys, location='scores.csv')
    else:
        P = [r[1:] for r in tables['projector.csv']]
        ledger.check('L0', 'projector rows indexed 1..p', [r[0] for r in tables['projector.csv']] == [float(i) for i in range(1, p + 1)], location='projector.csv')
    total_pub = summary['totalVariance']
    ntol = policy(n, p, total_pub, eta)
    k_rule, rule_fault = decide(lam, config, ntol, ntol['band'])
    zpub = [[(x - m) / s for x, m, s in zip(r, mu, scale)] for r in pred['rows']]
    znorm = math.sqrt(math.fsum(x * x for r in zpub for x in r))
    # L1: internal consistency of the published values.
    ledger.check('L1', 'eigenvalues non-negative and descending', all(x >= 0 for x in lam) and all(a >= b for a, b in zip(lam, lam[1:])), location='spectrum.csv')
    ledger.check('L1', 'declared retention rule on published eigenvalues gives published K', rule_fault is None and k_rule == K, location='$.retention')
    whole = math.fsum(lam)
    ledger.check('L1', 'fractions recompute from published eigenvalues', all(
        abs(r[2] - r[1] / whole) <= (p + 4) * U * max(r[2], U) and abs(r[3] - math.fsum(lam[:i + 1]) / whole) <= (p + 4) * U
        for i, r in enumerate(spec)), location='spectrum.csv')
    if V is not None:
        orth = max(abs(dot(V[a], V[b]) - (a == b)) for a in range(K) for b in range(K))
        ledger.check('L1', 'loadings orthonormal (budget 4(n+p)u)', orth <= 4 * (n + p) * U, orth, 4 * (n + p) * U, 'loadings.csv')
        ledger.check('L1', 'canonical sign: anchor entry positive', all(v[anchor(v, eta)] > 0 for v in V), location='loadings.csv')
        tau_s = 2 * (p + 6) * U * znorm
        worst = max(math.sqrt(math.fsum((scores[i][k + 1] - dot(zpub[i], V[k])) ** 2 for i in range(n))) for k in range(K))
        ledger.check('L1', 'scores equal scaled data times published loadings', worst <= tau_s, worst, tau_s, 'scores.csv')
        var_err = max(abs(math.fsum(scores[i][k + 1] ** 2 for i in range(n)) / (n - 1) - lam[k]) for k in range(K))
        bound = 2 * ntol['tauLambda'] + total_pub * eta ** 2
        ledger.check('L1', 'score variance equals published eigenvalue', var_err <= bound, var_err, bound, 'scores.csv')
        if K > 1:
            cross = max(abs(math.fsum(scores[i][a + 1] * scores[i][b + 1] for i in range(n)) / (n - 1))
                        for a in range(K) for b in range(a + 1, K))
            bound = 2 * ntol['tauLambda'] + 2 * total_pub * eta
            ledger.check('L1', 'scores mutually uncorrelated', cross <= bound, cross, bound, 'scores.csv')
        Phat = [[math.fsum(V[k][i] * V[k][j] for k in range(K)) for j in range(p)] for i in range(p)]
        terms = lambda i, j: [scores[i][k + 1] * V[k][j] for k in range(K)]
        length = K
    else:
        Phat = P
        sym = max(abs(P[i][j] - P[j][i]) for i in range(p) for j in range(p))
        idem = max(abs(math.fsum(P[i][m] * P[m][j] for m in range(p)) - P[i][j]) for i in range(p) for j in range(p))
        tr = math.fsum(P[i][i] for i in range(p))
        ledger.check('L1', 'projector symmetric', sym <= 8 * (n + p) * U, sym, 8 * (n + p) * U, 'projector.csv')
        ledger.check('L1', 'projector idempotent', idem <= 8 * (n + p) * U, idem, 8 * (n + p) * U, 'projector.csv')
        ledger.check('L1', 'projector trace equals K', abs(tr - K) <= 8 * (n + p) * U * p, abs(tr - K), 8 * (n + p) * U * p, 'projector.csv')
        terms = lambda i, j: [zpub[i][m] * P[m][j] for m in range(p)]
        length = p
    bounds, rec_err = [], 0.0
    for i in range(n):
        brow = []
        for j in range(p):
            t = terms(i, j)
            expect = mu[j] + scale[j] * math.fsum(t)
            bound = 4 * (length + 2) * U * (abs(mu[j]) + scale[j] * math.fsum(abs(x) for x in t))
            brow.append(bound)
            rec_err = max(rec_err, abs(rec[i][j + 1] - expect) / bound if bound else (0.0 if rec[i][j + 1] == expect else math.inf))
        bounds.append(brow)
    ledger.check('L1', 'reconstruction equals means + scale x retained projection', rec_err <= 1, rec_err, 1.0, 'reconstruction.csv')
    # L2: source-bound statistics by fsum.
    tm = [4 * U * pk + 2 * (n + 2) * U * s for pk, s in zip(st['peaks'], st['sds'])]
    ratio = max(abs(a - b) / t for a, b, t in zip(mu, st['means'], tm))
    ledger.check('L2', 'means within corrected two-pass bound of fsum mean', ratio <= 1, ratio, 1.0, 'pca-summary.json')
    if config['scaling'] == 'standardise':
        dev = max(abs(a - b) / b for a, b in zip(scale, st['sds']))
        ledger.check('L2', 'standardising scales equal n-1 sample deviations', dev <= (2 * n + 12) * U, dev, (2 * n + 12) * U, 'pca-summary.json')
    else:
        ledger.check('L2', 'scales equal declared or unit scales exactly', scale == st['scales'], location='pca-summary.json')
    dev = abs(total_pub - st['total'])
    ledger.check('L2', 'total variance within tauTotal of fsum', dev <= tol['tauTotal'], dev, tol['tauTotal'], 'pca-summary.json')
    resid = math.fsum(((x - r[j + 1]) / scale[j]) ** 2 for row, r in zip(pred['rows'], rec) for j, x in enumerate(row)) / (n - 1)
    dev, bound = abs(summary['residualVariance'] - resid), 2 * (n * p + 6) * U * resid
    ledger.check('L2', 'published residual variance equals source residual energy', dev <= bound, dev, bound, 'pca-summary.json')
    # L3: independent spectrum and a posteriori bounds.
    spectral = _spectral(ledger, pred, summary, config, n, p, K, lam, V, Phat, bounds, tm, resid)
    # L4: host-owned requirement and certification decisions.
    recon = [r[1:] for r in rec]
    decisions = _decisions(ledger, pred, summary, config, n, p, K, Phat, bounds, names, tm, recon, spectral)
    oracle_side = pred['K'] if pred['fault'] is None else pred['fault'][0]
    ledger.check('L3', 'oracle retention decision agrees or lies inside the doubled borderline band',
                 oracle_side == K or within_band(pred, config, 2 * tol['band']), location='$.retention')
    return {'retained': K, 'checks': ledger.items, 'spectral': spectral['record'], **decisions}


def _spectral(ledger, pred, summary, config, n, p, K, lam, V, Phat, bounds, tm, resid):
    st, tol, eta = pred['stats'], pred['tol'], config['loadingTolerance']
    scale = summary['scales']
    # Covariance of (x - mu_fsum)/s_published: one rescale rounding per entry, assigned symmetrically.
    f = [a / b for a, b in zip(st['scales'], scale)]
    C = [[0.0] * p for _ in range(p)]
    for i in range(p):
        for j in range(i, p):
            C[i][j] = C[j][i] = st['cov'][i][j] * (f[i] * f[j])
    T = math.fsum(C[i][i] for i in range(p))
    vals, vecs, sweeps = jacobi(C)
    cert = certified(C, vals, vecs)
    e = cert['errors']
    # Distance of C from the exact covariance of (x - mu*)/s for the parsed binary64 data:
    # product/fsum/division rounding <= 3uT, z rounding <= 4uT, rescale <= 3uT (+ margin);
    # a constant mean error enters only at second order: n ||delta/s||^2/(n-1).
    tau_mu = [2.01 * U * abs(m) for m in st['means']]
    eps_c = 11 * U * T * (1 + 1e-12) + n * math.fsum((t / s) ** 2 for t, s in zip(tau_mu, scale)) / (n - 1)
    dev = max(abs(a - b) for a, b in zip(lam, vals))
    ledger.check('L3', 'all p eigenvalues within qualification budget tauLambda of Jacobi oracle', dev <= tol['tauLambda'], dev, tol['tauLambda'], 'spectrum.csv')
    ledger.check('L3', 'oracle certificate finite', all(math.isfinite(x) for x in e), location='spectrum.csv')
    bound_eig = max(abs(a - b) + ek + eps_c for a, b, ek in zip(lam, vals, e))
    lam1 = vals[0] + e[0] + eps_c
    record = {'oracleSweeps': sweeps, 'oracleResidualF': cert['residualF'], 'oracleOrthogonality': cert['omega'],
              'oracleEigenvalueErrorMax': max(e), 'covarianceError': eps_c, 'publishedEigenvalueErrorBound': bound_eig,
              'totalVariance': T}
    if V is not None:
        alphas, residuals = [], []
        native = summary.get('nativeResiduals', {}).get('eigenpairResidual2', [])
        ledger.check('L3', 'native eigenpair residual diagnostics present', isinstance(native, list) and len(native) == K
                     and all(type(x) in (int, float) and math.isfinite(x) and x >= 0 for x in native), location='pca-summary.json')
        for k in range(K):
            nv = math.sqrt(math.fsum(x * x for x in V[k]))
            u = [x / nv for x in V[k]]
            rv = [math.fsum([C[i][j] * u[j] for j in range(p)] + [-lam[k] * u[i]]) for i in range(p)]
            allow = math.sqrt(math.fsum((2 * U * (math.fsum(abs(C[i][j] * u[j]) for j in range(p)) + abs(lam[k] * u[i]))) ** 2 for i in range(p)))
            r = math.sqrt(math.fsum(x * x for x in rv)) + allow + eps_c
            gap = min(abs(lam[k] - vals[j]) - e[j] - eps_c for j in range(p) if j != k)
            alpha = r / gap if gap > 0 else math.inf
            ledger.check('L3', f'PC{k + 1} loading sine angle validated a posteriori within loadingTolerance', alpha <= eta, alpha, eta, 'loadings.csv')
            bound = r + 2 * eps_c + 4 * (p + 2) * U * (cert['normF'] + abs(lam[k]))
            ledger.check('L3', f'PC{k + 1} native eigenpair residual consistent with host covariance', native[k] <= bound, native[k], bound, 'pca-summary.json')
            vo = vecs[k]
            ro = cert['vectorResidual'][k] + eps_c + 4 * (p + 2) * U * cert['normF']
            gap_o = min(abs(vals[k] - vals[j]) - e[j] - eps_c for j in range(p) if j != k)
            alpha_o = ro / gap_o if gap_o > 0 else math.inf
            sgn = 1.0 if dot(vo, u) >= 0 else -1.0
            dist = math.sqrt(math.fsum((a - sgn * b) ** 2 for a, b in zip(u, vo)))
            bound = math.sqrt(2) * (alpha + alpha_o)
            ledger.check('L3', f'PC{k + 1} loading agrees with Jacobi eigenvector within sqrt2*(alpha+alphaOracle)', dist <= bound, dist, bound, 'loadings.csv')
            alphas.append(alpha)
            residuals.append(r)
        record.update(loadingSineBounds=alphas, hostEigenpairResidual=residuals)
        basis = gram_schmidt(V)
    else:
        pv, pvec, _ = jacobi(Phat)
        basis = gram_schmidt(pvec[:K])
    # Retained-subspace distance beta = ||P^ - P*||_2 (Davis-Kahan sin-Theta, residual form).
    q = basis
    omega_q = math.sqrt(math.fsum((dot(q[a], q[b]) - (a == b)) ** 2 for a in range(K) for b in range(K))) + 2 * (p + 2) * U * K
    qq = [[math.fsum(q[k][i] * q[k][j] for k in range(K)) for j in range(p)] for i in range(p)]
    d_p = math.sqrt(math.fsum((qq[i][j] - Phat[i][j]) ** 2 for i in range(p) for j in range(p)))
    if K < p:
        cq = [[math.fsum(C[i][m] * q[k][m] for m in range(p)) for i in range(p)] for k in range(K)]
        H = [[dot(q[a], cq[b]) for b in range(K)] for a in range(K)]
        Hs = [[0.0] * K for _ in range(K)]
        for a in range(K):
            for b in range(a, K):
                Hs[a][b] = Hs[b][a] = (H[a][b] + H[b][a]) / 2
        hv, hvec, _ = jacobi(Hs)
        hcert = certified(Hs, hv, hvec)
        R = [[cq[k][i] - math.fsum(q[m][i] * Hs[m][k] for m in range(K)) for i in range(p)] for k in range(K)]
        rho = math.sqrt(math.fsum(x * x for r in R for x in r)) + eps_c + 4 * T * omega_q + 2 * (K + p) * U * T
        ritz = hv[-1] - hcert['errors'][-1] - eps_c - 2 * T * omega_q
        discarded_upper = vals[K] + e[K] + eps_c
        separation = ritz - discarded_upper
        sin_theta = min(1.0, rho / separation) if separation > 0 else math.inf
        beta = sin_theta + d_p + 2 * omega_q
        record.update(subspaceResidualF=rho, ritzMinimumLower=ritz, discardedUpper=discarded_upper, separation=separation)
    else:
        beta = math.sqrt(math.fsum((Phat[i][j] - (i == j)) ** 2 for i in range(p) for j in range(p))) + 4 * p * p * U
        record.update(fullRetention=True)
    record['subspaceDistanceBound'] = finite_or_none(beta)
    if config['output'] == 'subspace':
        ledger.check('L3', 'retained projector distance validated a posteriori within loadingTolerance', beta <= eta, beta, eta, 'projector.csv')
        Vo = vecs[:K]
        Po = [[math.fsum(Vo[k][i] * Vo[k][j] for k in range(K)) for j in range(p)] for i in range(p)]
        dist = math.sqrt(math.fsum((Phat[i][j] - Po[i][j]) ** 2 for i in range(p) for j in range(p)))
        if K < p:
            sep_o = vals[K - 1] - e[K - 1] - vals[K] - e[K] - 2 * eps_c
            beta_o = (min(1.0, (cert['residualF'] + eps_c) / sep_o) if sep_o > 0 else math.inf) + 2 * cert['omega']
        else:
            beta_o = 2 * cert['omega']
        bound = math.sqrt(2 * K) * (beta + beta_o)
        ledger.check('L3', 'projector agrees with Jacobi projector within sqrt(2K)*(beta+betaOracle)', dist <= bound, dist, bound, 'projector.csv')
    discarded = T - math.fsum(vals[:K])
    e_rec = math.fsum((b / s) ** 2 for brow in bounds for b, s in zip(brow, scale)) / (n - 1)
    e_mu = n * math.fsum((t / s) ** 2 for t, s in zip(tm, scale)) / (n - 1)
    tau_d = (math.fsum(e[:K]) + K * eps_c + math.sqrt(p) * eps_c + 2 * beta * math.sqrt(lam1 * max(discarded, 0.0))
             + beta * beta * lam1 + 2 * math.sqrt(max(discarded, 0.0) * (e_rec + e_mu)) + e_rec + e_mu + tol['tauTotal'])
    ledger.check('L3', 'residual energy against captured source equals validated discarded variance (Eckart-Young)',
                 abs(resid - discarded) <= tau_d, abs(resid - discarded), tau_d, 'reconstruction.csv')
    return {'record': record, 'vals': vals, 'errors': e, 'epsC': eps_c, 'T': T, 'beta': beta, 'lam1': lam1}


def _decisions(ledger, pred, summary, config, n, p, K, Phat, bounds, names, tm, recon, spectral):
    vals, e, eps_c, T, beta, lam1 = (spectral[k] for k in ('vals', 'errors', 'epsC', 'T', 'beta', 'lam1'))
    scale, rows, eta = summary['scales'], pred['rows'], config['loadingTolerance']
    rms = [math.sqrt(math.fsum((rows[i][j] - recon[i][j]) ** 2 for i in range(n)) / n) for j in range(p)]
    published = summary.get('reconstructionRMS')
    ledger.check('L4', 'native per-channel reconstruction RMS equals host evaluation from source and published reconstruction',
                 isinstance(published, list) and len(published) == p and all(
                     type(a) in (int, float) and abs(a - b) <= 2 * (n + 4) * U * b for a, b in zip(published, rms)),
                 location='pca-summary.json')
    floor = [scaled_rms([bounds[i][j] for i in range(n)], n) for j in range(p)]
    mean_term = [scale[j] * math.fsum(abs((j == m) - Phat[j][m]) * tm[m] / scale[m] for m in range(p)) for j in range(p)]
    sub_term = [scale[j] * beta * math.sqrt((n - 1) * lam1 / n) for j in range(p)]
    eval_term = [2 * (n + 4) * U * m for m in rms]
    uncertainty = [floor[j] + mean_term[j] + sub_term[j] for j in range(p)]
    tolerance = [uncertainty[j] + eval_term[j] for j in range(p)]
    sds = pred['stats']['sds']
    ratios = [u / (eta * s) for u, s in zip(uncertainty, sds)]
    frac = math.fsum(vals[:K]) / T
    published_frac = summary.get('explainedFraction')
    tau_f = (math.fsum(e[:K]) + K * eps_c + frac * math.sqrt(p) * eps_c) / T * (1 + 1e-12) + 8 * p * U
    budget = pred['tol']['tauFraction'] + tau_f
    ledger.check('L4', 'native explained fraction agrees with host spectrum within the qualification budget',
                 type(published_frac) in (int, float) and abs(published_frac - frac) <= budget,
                 abs(published_frac - frac) if type(published_frac) in (int, float) else None, budget, 'pca-summary.json')
    requirements = config['requirements']
    status = {}
    if 'minimumExplainedVariance' in requirements:
        status['minimumExplainedVariance'] = three_state(-frac, tau_f, -requirements['minimumExplainedVariance'])
    for item in requirements.get('reconstructionRMS', []):
        j = names.index(item['channel'])
        status['reconstructionRMS.' + item['channel']] = three_state(rms[j], finite_or_none(tolerance[j]), item['maximum'])
    overall = ('none' if not status else 'unmet' if 'unmet' in status.values()
               else 'indeterminate' if 'indeterminate' in status.values() else 'met')
    uncertified = [j for j, r in enumerate(ratios) if not (math.isfinite(r) and r <= 1)]
    outcome = ('uncertified' if uncertified else 'requirementsUnmet' if overall == 'unmet'
               else 'requirementsIndeterminate' if overall == 'indeterminate' else 'accepted')
    return {'outcome': outcome,
            'certification': {'criterion': 'reconstruction uncertainty <= loadingTolerance x sample deviation',
                              'ratio': [finite_or_none(r) for r in ratios], 'uncertifiedChannels': [names[j] for j in uncertified]},
            'requirements': {'status': status, 'overall': overall, 'explainedFraction': frac, 'explainedTolerance': tau_f,
                             'reconstructionRMS': rms, 'rmsTolerance': [finite_or_none(t) for t in tolerance],
                             'rmsToleranceParts': {'affineFloor': [finite_or_none(x) for x in floor],
                                                   'mean': [finite_or_none(x) for x in mean_term],
                                                   'subspaceFirstOrder': [finite_or_none(x) for x in sub_term],
                                                   'evaluation': [finite_or_none(x) for x in eval_term]},
                             'nullMeans': 'a null tolerance exceeds 1e100 or is not finite; the status is then indeterminate'}}
