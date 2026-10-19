"""Trusted NumPy PCA worker; copied into the owned run directory and never host-imported.

Run as: python -I -B native-worker.py compute|readback   (working directory = run directory)
Reads native-config.json and source.csv. Writes inspectable CSV/JSON only. Structured refusals
are written to <stage>-fault.json with exit status 3; readback failures exit 4. The summary
contains measurements and residual diagnostics only: the host verifier owns every requirement
and certification decision.
"""
import hashlib
import json
import math
import os
import re
import sys

REQUIRED_NUMPY = '2.5.4'
REQUIRED_BLAS = 'OpenBLAS 0.3.34'
EPS_U = 2.0**-53
TINY = 2.2250738585072014e-308          # smallest normal binary64
CELL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?\Z')
INTEGER = re.compile(r'[0-9]+\Z')
MAX_ROWS, MAX_CELLS, MAX_BYTES, MAX_K = 10000, 160000, 8 * 1024 * 1024, 10
RAW_MIN, RAW_MAX = 1e-48, 1e48
RATIO_MIN, RATIO_MAX = 1e-48, 1e48
HANDOFF = 1e100
OFFSET_RATIO = 1e6
THREADS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


class Fault(Exception):
    def __init__(self, code, message, location='$', **details):
        super().__init__(message)
        self.payload = {'code': code, 'message': message, 'location': location, 'details': details}


def bounded(name, limit=32 * 1024 * 1024):
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        import stat
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Fault('PCA_RESOURCE_LIMIT', 'native input is not a bounded regular file', name)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise Fault('PCA_RESOURCE_LIMIT', 'native input exceeds its byte budget', name)
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def finite_number(v):
    return type(v) in (int, float) and math.isfinite(v)


def validate_config(c):
    """Native-side checks of every configuration value the numerics depend on (host checks too)."""
    channels = c.get('channels')
    if not isinstance(channels, list) or not 2 <= len(channels) <= 32:
        raise Fault('PCA_INVALID_CONTRACT', 'declare 2-32 channels', '$.channels')
    mode = c.get('scaling')
    if mode not in ('none', 'standardise', 'declared'):
        raise Fault('PCA_INVALID_CONTRACT', 'scaling is none, standardise or declared', '$.scaling')
    for i, channel in enumerate(channels):
        if mode == 'declared' and not (finite_number(channel.get('scale')) and channel['scale'] > 0):
            raise Fault('PCA_INVALID_CONTRACT', 'declared scaling needs a finite positive scale for every channel', f'$.channels[{i}].scale')
        if mode != 'declared' and 'scale' in channel:
            raise Fault('PCA_INVALID_CONTRACT', 'a channel scale is only used with declared scaling', f'$.channels[{i}].scale')
    eta = c.get('loadingTolerance')
    if not finite_number(eta) or not 1e-9 <= eta <= 1e-2:
        raise Fault('PCA_INVALID_CONTRACT', 'loadingTolerance within [1e-9, 1e-2]', '$.loadingTolerance')
    retention = c.get('retention')
    if not isinstance(retention, dict) or len(retention) != 1:
        raise Fault('PCA_INVALID_CONTRACT', 'retention needs exactly one of components or minimumExplainedVariance', '$.retention')
    if 'components' in retention:
        if type(retention['components']) is not int or not 1 <= retention['components'] <= min(MAX_K, len(channels)):
            raise Fault('PCA_INVALID_CONTRACT', 'retain 1-10 components, at most the channel count', '$.retention.components')
    elif not (finite_number(retention.get('minimumExplainedVariance')) and 0 < retention['minimumExplainedVariance'] < 1):
        raise Fault('PCA_INVALID_CONTRACT', 'minimumExplainedVariance is a fraction in (0,1)', '$.retention.minimumExplainedVariance')
    if c.get('output') not in ('components', 'subspace'):
        raise Fault('PCA_INVALID_CONTRACT', 'output is components or subspace', '$.output')


def runtime_identity():
    """Observed native identity: NumPy version, the BLAS library actually mapped, Python."""
    import numpy as np
    for name in THREADS:
        if os.environ.get(name) != '1':
            raise Fault('PCA_UNSUPPORTED_RUNTIME', 'native BLAS/OpenMP threads must be capped to one', '$.runtime', variable=name)
    if np.__version__ != REQUIRED_NUMPY:
        raise Fault('PCA_UNSUPPORTED_RUNTIME', 'qualified for NumPy ' + REQUIRED_NUMPY + ' only', '$.runtime', observed=np.__version__)
    np.linalg.svd(np.eye(2))               # load and exercise the linked LAPACK/BLAS
    blas = 'unknown'
    try:
        with open('/proc/self/maps') as maps:
            for line in maps:
                found = re.search(r'libopenblas[a-z0-9_]*-r([0-9]+\.[0-9]+\.[0-9]+)', line)
                if found:
                    blas = 'OpenBLAS ' + found.group(1)
                    break
    except OSError:
        pass
    if blas != REQUIRED_BLAS:
        raise Fault('PCA_UNSUPPORTED_RUNTIME', 'qualified for ' + REQUIRED_BLAS + ' only', '$.runtime', observed=blas)
    return {'numpy': np.__version__, 'blas': blas, 'python': sys.version.split()[0], 'pid': os.getpid()}


def number(text, where):
    if not text:
        raise Fault('PCA_MISSING_VALUE', 'every cell needs a value; missing values are not imputed', where)
    if CELL.match(text) is None:
        raise Fault('PCA_INVALID_NUMBER', 'use plain decimal numbers without spaces, signs of infinity, nan, hex or digit separators', where)
    x = float(text)
    if not math.isfinite(x) or abs(x) > RAW_MAX or (x != 0 and abs(x) < RAW_MIN):
        raise Fault('PCA_VALUE_RANGE', 'raw values must be zero or have binary64 magnitude within [1e-48, 1e48]', where)
    return x


def load(config, data):
    """Strict reader: ASCII, comma separated, no quotes, LF or CRLF, exact declared header."""
    import numpy as np
    if len(data) > MAX_BYTES:
        raise Fault('PCA_RESOURCE_LIMIT', 'source exceeds 8 MiB', '$.source')
    if any(b > 127 for b in data):
        raise Fault('PCA_INVALID_CSV', 'source must be ASCII (no byte-order mark)', '$.source')
    text = data.decode('ascii')
    body = text[:-1] if text.endswith('\n') else text
    if text == '':
        raise Fault('PCA_INVALID_CSV', 'empty source', '$.source')
    header, keyed = config['header'], config['keyed']
    keys, values = [], []
    for index, raw in enumerate(body.split('\n')):
        line = raw[:-1] if raw.endswith('\r') else raw
        where = f'line {index + 1}'
        if '"' in line or '\r' in line:
            raise Fault('PCA_INVALID_CSV', 'quoted cells and bare carriage returns are not accepted', where)
        if not line:
            raise Fault('PCA_INVALID_CSV', 'blank lines are not accepted', where)
        parts = line.split(',')
        if index == 0:
            if parts != header:
                raise Fault('PCA_HEADER_MISMATCH', 'header must equal the declared row key and channels in order', where)
            continue
        if len(parts) != len(header):
            raise Fault('PCA_INVALID_CSV', 'ragged row', where)
        if index > MAX_ROWS:
            raise Fault('PCA_DIMENSIONS', 'more than 10000 data rows', where)
        row = [number(t, f'{where} column {j + 1}') for j, t in enumerate(parts)]
        if keyed:
            if keys and not row[0] > keys[-1]:
                raise Fault('PCA_ROW_KEY_ORDER', 'row key must increase strictly', where)
            keys.append(row.pop(0))
        values.append(row)
    n, p = len(values), len(config['channels'])
    if n < 3 or n * p > MAX_CELLS:
        raise Fault('PCA_DIMENSIONS', 'need 3-10000 rows and at most 160000 analysed cells', '$.source', rows=n)
    return (np.array(keys, dtype=np.float64) if keyed else None), np.array(values, dtype=np.float64)


def digest(a):
    import numpy as np
    return hashlib.sha256(np.ascontiguousarray(a, dtype='<f8').tobytes()).hexdigest()


def intermediate(name, values, *, positive=False):
    """Postcondition on an intermediate array/scalar: finite and within the handoff magnitude."""
    import numpy as np
    a = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(a)) or (a.size and float(np.max(np.abs(a))) > HANDOFF) or (positive and not np.all(a > 0)):
        raise Fault('PCA_VALUE_RANGE', 'intermediate value is non-finite or outside the representable contract range', 'intermediate:' + name)


def policy(n, p, total, eta):
    """Qualification budget and resolution policy shared with the host (empirical constants)."""
    c_tau = 16 + 48 * p + 8 * (n + p)
    tau = c_tau * EPS_U * total
    tol = {'cTau': c_tau, 'tauLambda': tau, 'gMin': 4 * c_tau * EPS_U / eta, 'gapThreshold': 4 * c_tau * EPS_U / eta * total,
           'band': 2 * tau, 'tauFraction': 2 * p * c_tau * EPS_U}
    for k, v in tol.items():
        if not math.isfinite(v) or (k != 'cTau' and v < TINY):
            raise Fault('PCA_VALUE_RANGE', 'tolerance model left the normal binary64 range', 'intermediate:tolerances.' + k)
    return tol


def retain(lam, config, tol):
    """Declared rule; lam has p entries (descending, zero padded). Raises Fault or returns K."""
    import numpy as np
    p, theta, band = len(lam), tol['gapThreshold'], tol['band']
    detail = {'eigenvalues': [float(x) for x in lam], 'threshold': theta, 'band': band}
    retention = config['retention']
    if 'components' in retention:
        K = retention['components']
    else:
        goal, whole, K = retention['minimumExplainedVariance'], float(np.sum(lam)), None
        cumulative = np.cumsum(lam) / whole
        for i in range(min(p, MAX_K)):
            if abs(cumulative[i] - goal) <= tol['tauFraction']:
                raise Fault('PCA_RETENTION_BORDERLINE', 'cumulative variance is numerically at the requested fraction', '$.retention', component=i + 1, **detail)
            if cumulative[i] >= goal:
                K = i + 1
                break
        if K is None:
            raise Fault('PCA_RETENTION_UNREACHABLE', 'more than 10 components would be needed', '$.retention', **detail)
    padded = np.append(lam, 0.0)
    messages = {'PCA_COMPONENT_BELOW_RESOLUTION': 'retained component variance is below the resolution threshold (rank deficiency or noise floor); retain fewer components or relax loadingTolerance',
                'PCA_DEGENERATE_COMPONENT': 'retained component shares a repeated or near-repeated eigenvalue; use output subspace or change retention',
                'PCA_RETENTION_SPLITS_CLUSTER': 'retention boundary splits a repeated eigenvalue cluster'}

    def judge(q, code, k):
        if abs(q - theta) <= band:
            raise Fault('PCA_SPECTRUM_BORDERLINE', 'spectral separation is numerically at the resolution threshold', '$.retention', component=k, quantity=float(q), **detail)
        if q < theta:
            raise Fault(code, messages[code], '$.retention', component=k, quantity=float(q), **detail)

    if config['output'] == 'components':
        for i in range(K):
            judge(padded[i], 'PCA_COMPONENT_BELOW_RESOLUTION', i + 1)
            if i > 0:
                judge(padded[i - 1] - padded[i], 'PCA_DEGENERATE_COMPONENT', i + 1)
            if i + 1 < p:
                judge(padded[i] - padded[i + 1], 'PCA_DEGENERATE_COMPONENT', i + 1)
    else:
        judge(padded[K - 1], 'PCA_COMPONENT_BELOW_RESOLUTION', K)
        if K < p:
            judge(padded[K - 1] - padded[K], 'PCA_RETENTION_SPLITS_CLUSTER', K)
    return K


def fmt(x, integer=False):
    return str(int(x)) if integer else repr(float(x))


def published_check(name, header, rows):
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if not math.isfinite(v) or abs(v) > HANDOFF:
                raise Fault('PCA_VALUE_RANGE', 'published value is non-finite or outside +/-1e100', f'published:{name} row {r + 1} column {header[c]}')


def summary_range_check(value, path):
    if isinstance(value, dict):
        for k, v in value.items():
            summary_range_check(v, f'{path}.{k}')
    elif isinstance(value, list):
        for i, v in enumerate(value):
            summary_range_check(v, f'{path}[{i}]')
    elif type(value) is float and (not math.isfinite(value) or abs(value) > HANDOFF):
        raise Fault('PCA_VALUE_RANGE', 'published summary value is non-finite or outside +/-1e100', 'published:' + path)


def scaled_rms(b, n):
    import numpy as np
    peak = float(np.max(np.abs(b))) if b.size else 0.0
    return 0.0 if peak == 0 else peak * math.sqrt(float(np.sum((b / peak) ** 2)) / n)


def compute():
    import numpy as np
    config_bytes, source = bounded('native-config.json', 1024 * 1024), bounded('source.csv', MAX_BYTES + 1)
    inputs = {'source.csv': sha(source), 'native-config.json': sha(config_bytes), 'native-worker.py': sha(bounded('native-worker.py'))}
    write_json('compute-inputs.json', inputs)
    config = strict_json(config_bytes.decode('utf-8'))
    validate_config(config)
    runtime = runtime_identity()
    keys, X = load(config, source)
    n, p = X.shape
    channels = [c['name'] for c in config['channels']]
    mode = config['scaling']
    # Corrected two-pass mean (Chan, Golub & LeVeque): error scales with spread, not offset.
    mu0 = X.mean(axis=0)
    mu = mu0 + (X - mu0).mean(axis=0)
    D = X - mu
    sd = np.sqrt((D * D).sum(axis=0) / (n - 1))
    peak = np.abs(X).max(axis=0)
    for j in range(p):
        if sd[j] == 0 or peak[j] > OFFSET_RATIO * sd[j]:
            raise Fault('PCA_CHANNEL_SPREAD', 'channel spread is zero or below 1e-6 of its largest magnitude', f'$.channels[{j}]',
                        channel=channels[j], spread=float(sd[j]), peak=float(peak[j]))
    scale = (np.ones(p) if mode == 'none' else sd if mode == 'standardise'
             else np.array([float(c['scale']) for c in config['channels']]))
    ratio = sd / scale
    for j in range(p):
        if not (RATIO_MIN <= ratio[j] <= RATIO_MAX):
            raise Fault('PCA_SCALE_RANGE', 'scaled spread sd/scale must lie within [1e-48, 1e48]', f'$.channels[{j}]',
                        channel=channels[j], ratio=float(ratio[j]))
    Z = (X - mu) / scale
    intermediate('Z', Z)
    total = float((Z * Z).sum() / (n - 1))
    intermediate('totalVariance', total, positive=True)
    _, S, Vh = np.linalg.svd(Z, full_matrices=False)       # LAPACK gesdd; S descending
    intermediate('singularValues', S)
    lam = np.zeros(p)
    lam[:S.size] = S * S / (n - 1)
    intermediate('eigenvalues', lam)
    eta = float(config['loadingTolerance'])
    tol = policy(n, p, total, eta)
    try:
        K = retain(lam, config, tol)
    except Fault as fault:
        fault.payload['details'].setdefault('eigenvalues', [float(x) for x in lam])
        fault.payload['details']['totalVariance'] = total
        raise
    V = Vh[:K].T.copy()
    raw_negative = []
    for k in range(K):
        v = V[:, k]
        first = int(np.flatnonzero(np.abs(v) >= np.abs(v).max() - 2 * eta)[0])
        raw_negative.append(bool(v[first] < 0))
        if v[first] < 0:
            V[:, k] = -v
    whole = float(np.sum(lam))
    fractions = lam / whole
    cumulative = np.cumsum(lam) / whole
    keyname = config['header'][0] if config['keyed'] else 'row'
    rowkeys = keys if keys is not None else np.arange(1, n + 1, dtype=np.float64)
    output = config['output']
    tables = {}
    P = V @ V.T
    if output == 'components':
        T = Z @ V                                              # scores are the projection of the scaled data
        recon = mu + (T @ V.T) * scale
        terms = np.abs(T) @ np.abs(V).T
        L = K
        tables['loadings.csv'] = (['component', *channels], [[k + 1, *V[:, k]] for k in range(K)], True)
        tables['scores.csv'] = ([keyname, *[f'PC{k + 1}' for k in range(K)]], [[rowkeys[i], *T[i]] for i in range(n)], keys is None)
    else:
        P = (P + P.T) / 2                                      # exact symmetry of the published projector
        recon = mu + (Z @ P) * scale
        terms = np.abs(Z) @ np.abs(P)
        L = p
        tables['projector.csv'] = (['channelIndex', *channels], [[j + 1, *P[j]] for j in range(p)], True)
    tables['spectrum.csv'] = (['component', 'eigenvalue', 'varianceFraction', 'cumulativeFraction'],
                              [[k + 1, lam[k], fractions[k], cumulative[k]] for k in range(p)], True)
    tables['reconstruction.csv'] = ([keyname, *channels], [[rowkeys[i], *recon[i]] for i in range(n)], keys is None)
    for name, (header, rows, _) in tables.items():
        published_check(name, header, [[float(x) for x in r] for r in rows])
    # Residual diagnostics on an exactly symmetric covariance (each pair from one computed value).
    C = Z.T @ Z / (n - 1)
    C = np.triu(C) + np.triu(C, 1).T
    residuals = [float(np.linalg.norm(C @ V[:, k] - lam[k] * V[:, k])) for k in range(K)]
    omega = float(np.linalg.norm(V.T @ V - np.eye(K)))
    if K < p:
        H = V.T @ C @ V
        H = np.triu(H) + np.triu(H, 1).T
        ritz_min = float(np.linalg.eigvalsh(H)[0])
        rho = float(np.linalg.norm(C @ V - V @ H))
        separation = ritz_min - float(lam[K]) - 2 * tol['tauLambda']
        beta = (min(1.0, (rho + 8 * EPS_U * total) / separation) if separation > 0 else 1.0) + 2 * omega
    else:
        ritz_min, rho, separation = float(lam[K - 1]), 0.0, None
        beta = float(np.linalg.norm(P - np.eye(p))) + 4 * p * p * EPS_U
    resid = X - recon
    residual_variance = float(((resid / scale) ** 2).sum() / (n - 1))
    rms = np.sqrt((resid ** 2).sum(axis=0) / n)
    # Early fail-safe: refuse a reconstruction the native residuals cannot support. The host
    # recomputes this criterion independently and owns the decision for published results.
    b = 4 * (L + 2) * EPS_U * (np.abs(mu) + scale * terms)
    floor = np.array([scaled_rms(b[:, j], n) for j in range(p)])
    tau_mu = 4 * EPS_U * peak + 2 * (n + 2) * EPS_U * sd
    mean_term = scale * (np.abs(np.eye(p) - P) @ (tau_mu / scale))
    subspace_term = scale * beta * math.sqrt((n - 1) * float(lam[0]) / n)
    uncertainty = floor + mean_term + subspace_term
    for j in range(p):
        if not (math.isfinite(uncertainty[j]) and uncertainty[j] <= eta * sd[j]):
            raise Fault('PCA_RECONSTRUCTION_UNCERTIFIED', 'the reconstruction of this channel cannot be supported to loadingTolerance x its spread',
                        f'$.channels[{j}]', channel=channels[j], ratio=float(uncertainty[j] / (eta * sd[j])),
                        uncertainty=float(uncertainty[j]), spread=float(sd[j]), eta=eta)
    w = np.linalg.eigvalsh(C)[::-1]
    arrays = {'X': X, 'keys': rowkeys, 'means': mu, 'scales': scale, 'eigenvalues': lam, 'reconstruction': recon}
    if output == 'components':
        arrays.update({'loadings': V.T, 'scores': T})
    else:
        arrays['projector'] = P
    for name, (header, rows, integer_first) in tables.items():
        with open(name, 'w', newline='') as stream:
            stream.write(','.join(header) + '\n')
            for row in rows:
                stream.write(','.join([fmt(row[0], integer_first)] + [fmt(x) for x in row[1:]]) + '\n')
    summary = {
        'version': 'schemaxis.numpy.summary/1', 'runtime': runtime,
        'source': {'sha256': sha(source), 'bytes': len(source)}, 'parsedDigest': digest(X),
        'n': n, 'p': p, 'scaling': mode, 'units': [c['unit'] for c in config['channels']], 'varianceDenominator': 'n-1',
        'centring': 'mean (corrected two-pass)', 'means': mu.tolist(), 'scales': scale.tolist(), 'scaledSpread': ratio.tolist(),
        'totalVariance': total, 'policy': tol, 'retained': K, 'output': output,
        'numericalRank': int(np.sum(lam >= tol['gapThreshold'])), 'singularValues': S.tolist(),
        'rawSignFlipped': raw_negative, 'residualVariance': residual_variance,
        'explainedFraction': float(cumulative[K - 1]), 'reconstructionRMS': rms.tolist(),
        'nativeResiduals': {'eigenpairResidual2': residuals, 'orthogonalityDefectF': omega, 'subspaceResidualF': rho,
                            'ritzMinimum': ritz_min, 'separation': separation,
                            'role': 'diagnostics evaluated natively with C = Z^T Z/(n-1); the host recomputes with its own covariance'},
        'eighCrossCheck': {'maxEigenvalueDifferenceOverTotal': float(np.max(np.abs(w - lam)) / total), 'role': 'diagnostic only'},
        'arrayDigests': {k: digest(a) for k, a in arrays.items()},
        'files': {name: sha(bounded(name)) for name in sorted(tables)},
    }
    summary_range_check(summary, 'pca-summary.json')
    write_json('pca-summary.json', summary)


def strict_json(text):
    def bad(token):
        raise ValueError('non-finite JSON constant ' + token)
    return json.loads(text, parse_constant=bad)


def write_json(name, value):
    with open(name + '.tmp', 'w') as stream:
        stream.write(json.dumps(value, indent=1, allow_nan=False, sort_keys=True) + '\n')
    os.replace(name + '.tmp', name)


def parse_table(name, integer_first):
    import numpy as np
    lines = bounded(name).decode('ascii').rstrip('\n').split('\n')
    rows = []
    for r, line in enumerate(lines[1:], 1):
        cells = line.split(',')
        if integer_first and INTEGER.match(cells[0]) is None:
            raise ValueError(f'{name} row {r}: index column is not an integer literal')
        if not all(CELL.match(x) for x in cells):
            raise ValueError(f'{name} row {r}: cell is not a plain decimal number')
        values = [float(x) for x in cells]
        if not all(math.isfinite(v) and abs(v) <= HANDOFF for v in values):
            raise ValueError(f'{name} row {r}: non-finite or out-of-range published value')
        rows.append(values)
    return lines[0].split(','), np.array(rows, dtype=np.float64)


def readback():
    """Separate process: published values must be finite, in range and round-trip to the computed arrays."""
    import numpy as np
    result = {'pid': os.getpid()}
    try:
        config_bytes, source = bounded('native-config.json', 1024 * 1024), bounded('source.csv', MAX_BYTES + 1)
        config = strict_json(config_bytes.decode('utf-8'))
        validate_config(config)
        result['runtime'] = runtime_identity()
        summary_bytes = bounded('pca-summary.json')
        summary = strict_json(summary_bytes.decode('utf-8'))
        names = sorted(summary['files'])
        write_json('readback-inputs.json', {'source.csv': sha(source), 'native-config.json': sha(config_bytes),
                                            'native-worker.py': sha(bounded('native-worker.py')), 'pca-summary.json': sha(summary_bytes),
                                            **{name: sha(bounded(name)) for name in names}})
        keys, X = load(config, source)
        keyed = keys is not None
        _, spec = parse_table('spectrum.csv', True)
        _, rec = parse_table('reconstruction.csv', not keyed)
        got = {'X': digest(X), 'keys': digest(rec[:, 0]), 'eigenvalues': digest(spec[:, 1]), 'reconstruction': digest(rec[:, 1:]),
               'means': digest(np.array(summary['means'])), 'scales': digest(np.array(summary['scales']))}
        checks = {}
        if summary['output'] == 'components':
            _, L = parse_table('loadings.csv', True)
            _, T = parse_table('scores.csv', not keyed)
            got['loadings'], got['scores'] = digest(L[:, 1:]), digest(T[:, 1:])
            Z = (X - np.array(summary['means'])) / np.array(summary['scales'])
            checks['recomputedScoresBitwiseEqual'] = bool(np.array_equal(Z @ np.ascontiguousarray(L[:, 1:].T), T[:, 1:]))
        else:
            _, P = parse_table('projector.csv', True)
            got['projector'] = digest(P[:, 1:])
        checks['digestsEqual'] = {k: got[k] == summary['arrayDigests'].get(k) for k in sorted(got)}
        checks['filesEqual'] = {f: sha(bounded(f)) == h for f, h in sorted(summary['files'].items())}
        ok = (set(got) == set(summary['arrayDigests']) and all(checks['digestsEqual'].values())
              and all(checks['filesEqual'].values()) and checks.get('recomputedScoresBitwiseEqual', True))
        result.update({'ok': ok, **checks})
    except (OSError, ValueError, KeyError, IndexError, TypeError, Fault) as error:
        result.update({'ok': False, 'reason': f'{type(error).__name__}: {error}'})
    write_json('readback.json', result)
    return result['ok']


def sanitise(value):
    if isinstance(value, dict):
        return {k: sanitise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitise(v) for v in value]
    if isinstance(value, float) or type(value).__name__.startswith('float'):
        value = float(value)
        return value if math.isfinite(value) else repr(value)
    if type(value).__name__.startswith('int') and not isinstance(value, bool):
        return int(value)
    return value


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    stage = sys.argv[1] if len(sys.argv) == 2 else None
    if stage == 'compute':
        try:
            compute()
        except Fault as fault:
            write_json('compute-fault.json', {**sanitise(fault.payload), 'pid': os.getpid()})
            sys.exit(3)
    elif stage == 'readback':
        sys.exit(0 if readback() else 4)
    else:
        sys.exit(2)


if __name__ == '__main__':
    main()
