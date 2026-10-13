# ParaView selection queries

`pvSelectionQuerySource` is ParaView's Find Data selection. Schemaxis accepts its
`QueryString` only as a closed JSON structure. Schemaxis writes the native query
text itself and checks it again before ParaView receives it. Query text written by
an author or produced at run time is never accepted.

## Why the query is structured

ParaView 5.13.3 evaluates query text as Python when the selection is extracted:

1. `VTKExtensions/Extraction/vtkPVExtractSelection.cxx:256-273` (`NewSelectionOperator`)
   returns a `vtkPythonSelector` for `vtkSelectionNode::QUERY` content.
2. `VTKExtensions/ExtractionPython/vtkPythonSelector.cxx:71-120` (`Execute`) imports
   `paraview.detail.python_selector` and calls `execute`.
3. `Wrapping/Python/paraview/detail/python_selector.py:58-93` (`execute`) reads the query
   string, binds every array of the chosen association by its sanitised name (plus `id`
   when the text mentions it) and calls `calculator.compute(inputs, query, ns=elocals)`.
4. `Wrapping/Python/paraview/detail/calculator.py:138-172` (`compute`) adds `inputs` and
   `points`, splits the text on `' and '`, and runs `eval(subEx, globals(), mylocals)`.
   The globals are those of `calculator.py`: its imports (`numpy as np`, `paraview`,
   `sys`, `dsa`, the VTK classes it names), everything that
   `vtkmodules.numpy_interface.algorithms` exports through `import *`, the module's own
   functions, and the Python built-ins, including `__import__`.

Escaping or blacklisting text that later reaches `eval` is not a defence, so authored
text never reaches this property. The other options were to validate authored text
with an allow-list alone, or to drop the operation. A structured query covers every
operator ParaView's own Find Data panel offers, so it keeps the operation useful.
The allow-list is kept as a second, independent check on the generated text.

## Grammar

```json
{"QueryString": {"any": [
  {"all": [
    {"array": "RTData", "test": ">", "value": 150},
    {"array": "RTData", "test": "<", "value": 200}
  ]},
  {"all": [{"ids": true, "test": "oneOf", "values": [0, 1, 2]}]}
]}}
```

The query matches an element when at least one `any` group matches. A group matches
when every clause in its `all` list matches. Use one group for an ordinary AND query.
Set `"negate": true` on a clause to invert it. The source's `InsideOut` option inverts
the whole selection. Limits: 16 groups, 16 clauses per group and 256 `values`.

Each clause has one `test` plus the members that test needs:

| `test` | Members | Generated text |
|---|---|---|
| `==` `!=` `<` `<=` `>` `>=` | term, `value` | `T > 150` |
| `between` | term, `minimum` < `maximum` | `(T > min) & (T < max)` (strict, as in Find Data) |
| `oneOf` | term, `values` | `in1d(T, [v, ...])` |
| `isMinimum` `isMaximum` | term | `T == min(T)`, `T == max(T)` |
| `isMinimumPerBlock` `isMaximumPerBlock` | term | `T == min_per_block(T)` |
| `isNaN` | term | `isnan(T)` |
| `atMostMean` `atLeastMean` | term | `T <= mean(T)`, `T >= mean(T)` |
| `nearMean` | term, `tolerance` | `abs(T - mean(T)) <= tolerance` |
| `pointNear` | `point`, `tolerance` | `pointIsNear([(x, y, z)], tolerance, inputs)` (point queries) |
| `cellContaining` | `point` | `cellContainsPoint(inputs, [(x, y, z)])` (cell queries) |

A term is either `"array": name`, optionally with `"component": n` (`T[:, n]`) or
`"magnitude": true` (`mag(T)`), or `"ids": true` for element indices (`id`). The
operators and functions match `pqSelectionQueryPropertyWidget.cxx:542-574` in
ParaView 5.13.3. The functions are defined in that release's
`vtkmodules/numpy_interface/algorithms.py` (`in1d`, `isnan`, `abs`, `mag`, `min`,
`max`, `mean`, `min_per_block`, `max_per_block`, `logical_not`) and in
`paraview/detail/calculator.py` (`pointIsNear`, `cellContainsPoint`).
Clauses are wrapped in parentheses and joined with `&`. Groups are joined with `|`.
Negation uses `logical_not` because composite-dataset arrays do not support `~`.

## Array names

Write the array name as it appears in the data. Schemaxis applies ParaView's
`vtkSMCoreUtilities::SanitizeName` (the same rule as `paraview.make_name_valid`):
it keeps ASCII letters, digits and `_`, and puts `a` in front when the result does
not start with a letter. So `Temperature (K)` becomes `TemperatureK`. Two arrays
that sanitise to the same name cannot be told apart, which is also true in ParaView.
Planning rejects a name that sanitises to nothing or to a name containing `__`. It
also rejects names that equal a Python keyword, a Python built-in function or
constant, a query function, `inputs`, `points` or `id`. Use `"ids": true` for element
indices. Rename a conflicting array upstream, for example with `pvPassArrays`.

## Enforcement

- **Schema.** Studio forms, the JSON schemas and the generated reference offer only
  the structured form. The binding carries `compiler: paraview.selectionQuery`.
- **Planning.** Structural errors use the shared declaration codes
  (`INVALID_ARGUMENT`, `UNKNOWN_ARGUMENT`). This includes Python text supplied as the
  query. Semantic errors use `INVALID_SELECTION_QUERY`. Source diagnostics give the
  RFC 6901 pointer, for example `/nodes/1/options/QueryString/any/0/all/0/maximum`.
  The check runs for each option and each axis value, even when other options on
  the node are dynamic.
- **Runtime values.** Values that arrive through `$observe`, `$sample`, `$axis`,
  `$call` or `$calc` are validated and compiled again after resolution, before the
  backend sees them.
- **Native boundary.** `native.assign` looks up the ParaView property's command
  before every assignment. For `SetQueryString` it accepts only text inside the
  generated language (`UNSAFE_NATIVE_QUERY` otherwise). Properties that ParaView
  always runs as Python, such as `SetScript` and `SetPythonExpression`, are never
  assigned (`UNSAFE_NATIVE_PROPERTY`). Proxies whose VTK class contains `Python` are
  never created (`UNSAFE_NATIVE_PROXY`). Constructor values pass the same guard.
- **Catalogue import.** `catalogue_import.py` recognises the Python-evaluated
  commands listed in `selection_query.py` (`PYTHON_EVALUATED`). It compiles
  `SetQueryString` through the grammar and excludes proxies that have any other such
  command. Unit tests fail if a regenerated catalogue adds an unreviewed text option
  whose name suggests evaluation.

The independent allow-list (`selection_query.check_text`) accepts only printable
ASCII without quotes and nothing longer than 16384 characters. It rejects nesting
deeper than 32, the word `and` (which `compute` splits on), attribute access,
subscripts other than `[:, n]`, keyword or starred arguments, lambdas,
comprehensions, conditionals and assignment expressions, chained comparisons,
string or byte literals, and any call outside the function list.

## Scope

A clause whose element type does not match is not rejected by Schemaxis. Examples
are `pointNear` on a cell query (`ElementType` `"Cell Data"`, the ParaView default) or
`component` on a one-component array. ParaView reports these when the selection is
extracted.
