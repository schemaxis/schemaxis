"""Pilot-only supplement to the frozen pixel grader; no producer receipts trusted.

Reject decoded images repeated across distinct requested times when the matching
reference images differ. This catches the recorded Luna stale-time escape without
tightening the existing pixel thresholds or claiming complete semantic coverage.
"""
import json
from pathlib import Path
import sys

from paraview_benchmark_native import grade as original_grade, image


def repeated_time_images(task, submission, reference):
    import numpy as np
    failures = []
    for case in task['cases']:
        for si in range(len(case['fractions'])):
            for ai in range(len(task['appearances'])):
                for ci in range(len(case['cameras'])):
                    previous = []
                    for ti, time in enumerate(case['times']):
                        name = f'slice-{ti}-{si}-appearance-{ai}-camera-{ci}.png'
                        try:
                            dims, actual = image(submission / case['id'] / name)
                            expected_dims, expected = image(reference / case['id'] / name)
                            for old_time, old_name, old_dims, old_actual, old_expected_dims, old_expected in previous:
                                references_differ = expected_dims != old_expected_dims or not np.array_equal(expected, old_expected)
                                if time != old_time and references_differ and dims == old_dims and np.array_equal(actual, old_actual):
                                    failures.append({'case': case['id'], 'file': name,
                                        'error': 'Decoded pixels repeat ' + old_name + ' across distinct times while references differ.'})
                                    break
                            previous.append((time, name, dims, actual, expected_dims, expected))
                        except Exception as error:
                            failures.append({'case': case['id'], 'file': name, 'error': 'Time comparison unavailable: ' + str(error)})
    return failures


def grade(task, submission, reference):
    result = original_grade(task, submission, reference)
    result['originalPixelGradePassed'] = result['passed']
    failures = repeated_time_images(task, submission, reference)
    for case in result['cases']:
        case['originalPixelGradePassed'] = case['passed']
        errors = [dict(file=f['file'], error=f['error']) for f in failures if f['case'] == case['id']]
        rejected = {e['file'] for e in errors}
        case['checks'] = [c for c in case['checks'] if c['file'] not in rejected]
        case['errors'].extend(errors)
        case['passed'] = case['originalPixelGradePassed'] and not case['errors']
    result['passed'] = result['originalPixelGradePassed'] and all(c['passed'] for c in result['cases'])
    result['timeDistinctnessFailures'] = failures
    result['scope'] += '; exact decoded duplicates rejected across times with distinct reference images'
    result['limitations'] = ['Pixel tolerances can admit small semantic errors.',
        'Nonidentical stale images can escape the duplicate check.',
        'Reference rendering is not independent validation of native ParaView or subjective quality.',
        'Artifact acceptance does not establish reusable procedure quality or accurate verification claims.']
    return result


if __name__ == '__main__':
    task, submission, reference, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(grade(json.loads(task.read_text()), submission, reference), indent=2)+'\n')
