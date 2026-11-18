"""Acceptance cases of docs/design/expression-language.md for the standalone package."""
import ast
import math
import pathlib
import unittest

from schemaxis.expr import (CONSTANT, OBSERVED, VISIT, Binding, Environment, ExprFault, HostFunction, Info,
                            INVALID, Namespace, check, classify, evaluate, parse, to_json)

BODY = {'min': [0, -0.9, 0.2], 'max': [4.5, 0.9, 1.4]}
WHEELS = [0.5, 3.6, -1, 1, 0, 0.7]
MODEL = {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}
SECTIONS = {
    'dimensions': {'wheelbase': 2.7},
    'settings': {'zoom': 0.52, 'options': {'gap': 0.25}, 'sweeps': 4, 'wheel-left': 1},
    'definitions': {'body': BODY, 'wheels': WHEELS, 'ground': {'min': [-10, -5, 0], 'max': [20, 5, 0]},
                    'model': MODEL, 'wheel-left': 2, '😀': 1},
}


class Late(Binding):
    """A binding whose value is read from the evaluation context."""

    def __init__(self, kind, phase, key, dependencies=()):
        super().__init__(kind, phase, dependencies, label=key)
        self.key = key

    def read(self, context):
        return context[self.key]


class Section(Namespace):
    def __init__(self, name):
        super().__init__(name)
        self.name = name

    def member(self, name):
        if name not in SECTIONS[self.name]:
            return None
        value = SECTIONS[self.name][name]
        return Binding(classify(value), known=value, label=f'{self.name}.{name}')

    def available(self):
        return sorted(SECTIONS[self.name])


class Double(HostFunction):
    """A host function with one named argument, standing in for the catalogue."""

    def check(self, call, checker):
        info = checker.check(call.named[0].value)
        return Info('scalar', info.phase, info.dependencies)

    def evaluate(self, call, evaluator):
        return 2 * evaluator.evaluate(call.named[0].value)


class Document(Environment):
    """The fixture of section 13 with one axis and one observed entry."""

    LATE = {'t': Late('scalar', VISIT, 't'),
            'car': Late('box', OBSERVED, 'car', ['bodySurface', 'wheelSurface']),
            'obs': Late('unknown', OBSERVED, 'obs', ['bodySurface'])}

    def resolve(self, name, quoted):
        if name in SECTIONS and not quoted:
            return Section(name)
        found = [Section(section).member(name) for section in SECTIONS if name in SECTIONS[section]]
        if name in self.LATE:
            found.append(self.LATE[name])
        if len(found) > 1:
            raise ExprFault('EXPR_AMBIGUOUS_NAME', f'`{name}` is ambiguous', name=name,
                            candidates=[binding.label for binding in found])
        return found[0] if found else None

    def available(self):
        return sorted(set().union(*SECTIONS.values()))

    def function(self, name):
        return Double() if name == 'double' else None


DOCUMENT = Document()
CONTEXT = {'t': 0.5, 'car': [0, 4.5, -1, 1, 0, 1.4], 'obs': {'points': 12, 'bounds': [0, 4.5, -0.9, 0.9, 0.2, 1.4]}}


def value(text, context=CONTEXT):
    return to_json(evaluate(text, DOCUMENT, context))


class ExpressionCase(unittest.TestCase):
    def close(self, actual, expected):
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for key in expected:
                self.close(actual[key], expected[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for a, e in zip(actual, expected):
                self.close(a, e)
        elif isinstance(expected, bool) or isinstance(expected, str):
            self.assertEqual(actual, expected)
        else:
            self.assertTrue(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (actual, expected))

    def fault(self, text, code, **observed):
        with self.assertRaises(ExprFault) as caught:
            value(text)
        self.assertEqual(caught.exception.code, code, text)
        for key, expected in observed.items():
            actual = getattr(caught.exception, key) if key in ('position', 'length') else caught.exception.observed.get(key)
            self.assertEqual(actual, expected, (text, key))
        return caught.exception


class TwentyExamples(ExpressionCase):
    def test_constant_examples(self):
        cases = [
            ('2 * wheelbase + 0.3', 'scalar', 5.7),
            ('union(body, wheels)', 'box', MODEL),
            ('model.size', 'vector', [4.5, 2, 1.4]),
            ('model.span', 'scalar', 5.119570294468081),
            ('model.inflate(zoom)', 'box', {'min': [-1.17, -1.52, -0.364], 'max': [5.67, 1.52, 1.764]}),
            ('vector(model.mid.x, model.max.y, model.min.z)', 'vector', [2.25, 1, 0]),
            ('intersect(body, wheels)', 'box', {'min': [0.5, -0.9, 0.2], 'max': [3.6, 0.9, 0.7]}),
            ('intersect(body, ground).valid', 'boolean', False),
            ('union(model, intersect(body, ground))', 'box', MODEL),
            ('ground.inflate(0.1)', 'box', {'min': [-11.5, -5.5, 0], 'max': [21.5, 5.5, 0]}),
            ('subtract(ground, model)', 'box', {'min': [4.5, -5, 0], 'max': [20, 5, 0]}),
            ("subtract(ground, model, 'y-')", 'box', {'min': [-10, -5, 0], 'max': [20, -1, 0]}),
            ("model.push('x+', 2).pushAbs('z+', 0.5)", 'box', {'min': [0, -1, 0], 'max': [13.5, 1, 1.9]}),
            ("model.setFace('z-', -0.1).inflateYAbs(1)", 'box', {'min': [0, -1.5, -0.1], 'max': [4.5, 1.5, 1.4]}),
            ('contains(model, vector(2, 0, 5))', 'boolean', False),
        ]
        for text, kind, expected in cases:
            checked = check(text, DOCUMENT)
            self.assertEqual((checked.type, checked.phase), (kind, CONSTANT), text)
            self.close(to_json(evaluate(checked)), expected)

    def test_invalid_box_read(self):
        self.fault('intersect(body, ground).mid', 'EXPR_INVALID_BOX', source='intersect(body, ground)')
        self.fault('intersect(body, ground).corner(0)', 'EXPR_INVALID_BOX', source='intersect(body, ground)')

    def test_visit_and_observed(self):
        checked = check('lerp(model.min, model.max, t)', DOCUMENT)
        self.assertEqual((checked.type, checked.phase), ('vector', VISIT))
        for t, expected in ((0, [0, -1, 0]), (0.5, [2.25, 0, 0.7]), (1, [4.5, 1, 1.4])):
            self.close(to_json(evaluate(checked, context={'t': t})), expected)
        checked = check('vector(car.mid.x, car.min.y, car.max.z)', DOCUMENT)
        self.assertEqual(checked.phase, OBSERVED)
        self.assertEqual(checked.dependencies, {'bodySurface', 'wheelSurface'})
        self.close(value('vector(car.mid.x, car.min.y, car.max.z)'), [2.25, -1, 1.4])
        self.assertEqual(check('t + car.min.x', DOCUMENT).phase, OBSERVED)


class FurtherCases(ExpressionCase):
    def test_boxes_and_syntax(self):
        self.assertEqual(value('model.inflate(-2).valid'), False)
        self.close(value('model.inflate(-1)'), {'min': [2.25, 0, 0.7], 'max': [2.25, 0, 0.7]})
        self.close(value('subtract(model, ground)'), MODEL)
        self.assertEqual(value('overlaps(subtract(model, ground), ground)'), True)
        fault = self.fault("model.push('x+', 2", 'EXPR_SYNTAX', position=18)
        self.assertIn(')', fault.observed['expected'])
        self.assertIn(',', fault.observed['expected'])
        self.fault('`😀` + missing', 'EXPR_UNKNOWN_NAME', position=6, length=7)
        self.fault("model.double(x = 1)", 'EXPR_UNKNOWN_PROPERTY')
        self.assertEqual(value('box()'), to_json(INVALID))
        self.assertEqual(value('box(vector(1, 0, 0), vector(0, 0, 0)) == box()'), True)
        self.close(value('boxAt(vector(0, 0, 0), vector(2, 4, 0))'), {'min': [-1, -2, 0], 'max': [1, 2, 0]})
        self.close(value('ground.inflateAbs(1)'), {'min': [-10.5, -5.5, -0.5], 'max': [20.5, 5.5, 0.5]})
        self.close(value('translate(body, vector(1, 0, 0)).min'), [1, -0.9, 0.2])
        self.assertEqual(value('contains(model, body)'), True)
        self.assertEqual(value('contains(box(), body) || overlaps(box(), body)'), False)
        self.assertEqual(value('subtract(body, model).valid'), False)
        self.fault("model.push('up', 1)", 'EXPR_ARGUMENTS')

    def test_conditionals_comparisons_and_functions(self):
        self.assertEqual(value("model.deltaX > model.deltaY ? 'x+' : 'y+'"), 'x+')
        self.close(value('intersect(body, ground).valid ? intersect(body, ground).mid : model.mid'), [2.25, 0, 0.7])
        for t, expected in ((0, 0), (0.5, 1.4), (1, 1.4)):
            self.close(value('if(t >= 0.5, model.max.z, model.min.z)', {'t': t}), expected)
        self.assertEqual(value('model.valid && model.span > 5'), True)
        self.assertEqual(value('model.min == vector(0, -1, 0)'), True)
        self.assertEqual(value('1 == 1.0'), True)
        self.assertEqual(value('true ? 1 : false ? 2 : 3'), 1)
        self.fault('true ? 1 : vector(0, 0, 0)', 'EXPR_TYPE')
        self.fault('1 < 2 < 3', 'EXPR_SYNTAX')
        self.fault('2 ^ 3', 'EXPR_SYNTAX', reserved=True)
        self.fault('1 && true', 'EXPR_TYPE')
        self.assertEqual([value('7 % 3'), value('-7 % 3'), value('pos(-2)'), value('sign(0)'), value('clamp(7, 0, 5)')],
                         [1, -1, 0, 1, 5])
        self.close(value('atan2(1, 1)'), 45)
        self.close(value('sin(deg(pi / 2))'), 1)
        self.close(value('hypot(3, 4)'), 5)
        self.assertEqual(value('model.corner(0)'), [0, -1, 0])
        self.assertEqual(value('model.corner(2)'), [4.5, 1, 0])
        self.assertEqual(value('model.corner(6)'), [4.5, 1, 1.4])
        self.fault('model.corner(8)', 'EXPR_ARGUMENTS')
        self.assertEqual(value('-model.min.y + 2 * -3'), -5)
        self.assertEqual(value('round(2.5) + round(-2.5) + floor(1.5)'), 1)
        self.assertEqual(value('min(vector(1, 5, 3), vector(2, 4, 3))'), [1, 4, 3])
        self.assertEqual(value('vector(1, 2, 3) * 2 - 1'), [1, 3, 5])
        self.assertEqual(value('near(vector(0, 0, 0), vector(0, 0, 0.1), 0.2)'), True)

    def test_short_circuit_and_static_checks(self):
        self.assertEqual(value('if(false, 1 / 0, 42)'), 42)
        self.assertEqual(value('false && (1 / 0 > 0)'), False)
        self.assertEqual(value('true || (1 / 0 > 0)'), True)
        self.fault('if(true, 1 / 0, 42)', 'EXPR_DOMAIN')
        self.fault('if(false, missing, 42)', 'EXPR_UNKNOWN_NAME')
        self.fault("if(false, 'a', 42)", 'EXPR_TYPE')
        self.fault('false && sqrt(1, 2) > 0', 'EXPR_ARGUMENTS')

    def test_function_faults(self):
        for text in ('acosh(0)', 'atanh(1)', 'lgamma(0)', 'lgamma(-2)', 'sqrt(-1)', 'log(0)', 'acos(2)',
                     'pow(0, -1)', 'pow(-8, 0.5)', '1 % 0', 'vector(1, 2, 3) / vector(1, 0, 1)',
                     'normalize(vector(0, 0, 0))', 'clamp(1, 2, 0)'):
            self.fault(text, 'EXPR_DOMAIN')
        for text in ('exp(1000)', 'pow(10, 400)', 'sinh(1000)', '1e308 * 10'):
            self.fault(text, 'EXPR_NONFINITE')
        self.assertEqual(value('exp(-1000)'), 0)

    def test_reserved_forms(self):
        self.assertEqual([value('min(1, 2)'), value('pos(3)')], [1, 1])
        self.fault('min(1)', 'EXPR_ARGUMENTS', reserved=True)
        self.fault('pos()', 'EXPR_ARGUMENTS', reserved=True)
        self.fault('sqrt()', 'EXPR_ARGUMENTS', reserved=False)
        self.fault('grad(1)', 'EXPR_UNKNOWN_FUNCTION', reserved=True)
        self.fault('nothing(1)', 'EXPR_UNKNOWN_FUNCTION', reserved=False)
        for character in '^&|~@#;{}':
            self.fault(f'1 {character} 2', 'EXPR_SYNTAX', reserved=True)

    def test_names(self):
        self.fault('1 + `wheel-left`', 'EXPR_AMBIGUOUS_NAME', position=4, length=12)
        self.assertEqual(value('settings.`wheel-left`'), 1)
        self.assertEqual(value('definitions.`wheel-left` + 1'), 3)
        self.assertEqual([value('settings.`sweeps`'), value('settings.sweeps')], [4, 4])
        self.fault('settings', 'EXPR_TYPE')
        self.fault('settings + 1', 'EXPR_TYPE')
        self.fault('settings.nothing', 'EXPR_UNKNOWN_NAME')
        self.fault('pi()', 'EXPR_UNKNOWN_FUNCTION')

    def test_typing(self):
        self.assertEqual(value('settings.options.gap + 1'), 1.25)
        self.fault('settings.options.nothing', 'EXPR_UNKNOWN_PROPERTY')
        self.fault('obs.points * 2', 'EXPR_TYPE_UNKNOWN')
        self.assertEqual(value('scalar(obs.points) * 2'), 24)
        self.close(value('box(obs.bounds).mid'), [2.25, 0, 0.8])
        self.fault('vector(obs.bounds)', 'EXPR_TYPE')
        self.fault('obs.nothing', 'EXPR_UNKNOWN_PROPERTY')
        self.fault('scalar(body)', 'EXPR_TYPE')
        self.fault('body + 1', 'EXPR_TYPE')
        self.fault('model.nothing', 'EXPR_UNKNOWN_PROPERTY')
        self.close(value('model.min[1] + wheels.max.z'), -0.3)
        self.assertEqual(value('double(x = model.max.x)'), 9)
        self.fault('sqrt(x = 4)', 'EXPR_ARGUMENTS')

    def test_limits(self):
        self.fault('1' + ' + 1' * 1100, 'EXPR_LIMIT')
        self.fault('(' * 70 + '1' + ')' * 70, 'EXPR_LIMIT')
        self.fault('-' * 70 + '1', 'EXPR_LIMIT')
        self.fault('.5', 'EXPR_SYNTAX', position=0)
        self.fault('', 'EXPR_SYNTAX', position=0)
        self.fault("'open", 'EXPR_SYNTAX', position=5)
        self.assertEqual(parse('a ? b : c ? d : e').otherwise.condition.name, 'c')

    def test_long_chains_are_walked_without_recursion(self):
        self.assertEqual(value(' + '.join(['1'] * 500)), 500)
        self.assertEqual(value('model' + '.translate(vector(1, 0, 0))' * 150 + '.min.x'), 150)
        self.assertEqual(check(' - '.join(['1'] * 500)).type, 'scalar')

    def test_every_value_is_finite(self):
        for text in ('1e309', '1e309 > 0', 'box(-1e308, 1e308, 0, 1, 0, 1).deltaX',
                     'vector(1.7e308, 1.7e308, 0).length', 'box(-1e308, 1e308, 0, 1, 0, 1).size'):
            self.fault(text, 'EXPR_NONFINITE')
        self.assertEqual(value('if(false, 1e309, 1)'), 1)
        self.assertEqual(value('true || 1e309 > 0'), True)

    def test_face_tokens_are_checked_in_every_branch(self):
        self.fault("subtract(box(), box(), 'up')", 'EXPR_ARGUMENTS', expected=['x-', 'x+', 'y-', 'y+', 'z-', 'z+'])
        self.fault("if(false, box().push('up', 1), box())", 'EXPR_ARGUMENTS', position=21, length=4)
        self.fault("false && model.setFace('top', 1).valid", 'EXPR_ARGUMENTS')
        self.fault("model.pushAbs(model.deltaX > 1 ? 'up' : 'x+', 1)", 'EXPR_ARGUMENTS')
        self.assertEqual(value("model.pushAbs(model.deltaX > 1 ? 'x+' : 'up', 1).max.x"), 5.5)


class Standalone(unittest.TestCase):
    def test_package_imports_nothing_from_schemaxis(self):
        package = pathlib.Path(__file__).resolve().parents[2] / 'src' / 'schemaxis' / 'expr'
        allowed = {'math', 'operator'}
        for path in sorted(package.glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Import):
                    self.assertTrue({alias.name for alias in node.names} <= allowed, path.name)
                elif isinstance(node, ast.ImportFrom):
                    self.assertTrue(node.level == 1 or node.module in allowed, path.name)


if __name__ == '__main__':
    unittest.main()
