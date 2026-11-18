# Expression language

Status: design approved on 10 November 2026 after three review rounds.
`docs/reference` and the README say what is implemented. From here the grammar
changes only through a recorded amendment (section 15).

This document specifies the string form of `$expr`: a closed, typed language
for scalars, vectors and boxes that is the same in every adaptor's documents.
It covers the grammar, the types, every function, how Schemaxis decides when an
expression is evaluated, the faults, the records and host actions Studio and
agents use, and worked examples with expected results.

## 1. Summary

```json
{"$expr": "model.inflate(0.52)"}
```

- The wrapper contains only `$expr`. A **string** value is this language. An
  **object** value is the existing composition form (`op`, `args`), which is
  unchanged. `$calc`, `$value`, `$call`, `$observe`, `$sweep`, `$analytic` and
  the other markers keep working; section 12 states how they combine with
  string expressions.
- An expression is one value. It has arithmetic, comparisons, logic and
  conditionals, but no statements, assignments, loops, imports or I/O. It can
  call only the functions listed here and the functions in the registered
  function catalogue.
- The language is meant to grow into a general expression facility with the
  reach of swak4Foam (fields, reductions, stored state, control logic).
  Appendix B maps that scope, says what is in this specification and what is
  planned, and lists what is reserved now so later amendments only add.
- The author never states when an expression is evaluated. Schemaxis derives
  that from what the expression depends on (section 8).
- The host implementation is the only authority. Studio and agents obtain
  parsing, types, phases and values from the host actions in appendix A; they
  do not parse, plan or evaluate expressions themselves.

## 2. Lexical rules

| Token | Rule |
| --- | --- |
| Whitespace | Space, tab, carriage return and line feed separate tokens and are otherwise ignored. |
| Number | `digits [ "." digits ] [ ("e" \| "E") [ "+" \| "-" ] digits ]`. A leading digit is required (`0.5`, not `.5`). No sign (see unary minus), no hexadecimal, no digit separators, no percent sign. |
| String | `'…'` or `"…"`. No escape sequences; a string cannot contain its own delimiter or a control character. Single quotes avoid JSON escaping and are the documented style. |
| Identifier | `[A-Za-z_][A-Za-z0-9_]*`. Case-sensitive. |
| Quoted name | `` `…` ``: any characters except a backtick or control character. It is a name or key, never a function, and is how a name containing `-` or other punctuation is written: `` `wheel-left` ``. |
| Operators and punctuation | `+ - * / % ( ) , . [ ] = ? : < <= > >= == != && \|\| !` |
| Reserved | `^ & \| ~ @ # ; { }` have no meaning yet. Using one is `EXPR_SYNTAX`, with `reserved: true`. `^` is deliberately not defined: it means power in spreadsheets and cross product in swak4Foam; write `pow` or `cross`. |

Limits: at most 4096 Unicode code points, 64 levels of nesting and 1024 syntax
nodes per expression. Exceeding one is `EXPR_LIMIT`.

## 3. Grammar

```ebnf
expression  = conditional ;
conditional = or [ "?" expression ":" conditional ] ;
or          = and { "||" and } ;
and         = equality { "&&" equality } ;
equality    = comparison [ ( "==" | "!=" ) comparison ] ;
comparison  = sum [ ( "<" | "<=" | ">" | ">=" ) sum ] ;
sum         = product { ( "+" | "-" ) product } ;
product     = unary { ( "*" | "/" | "%" ) unary } ;
unary       = ( "-" | "+" | "!" ) unary | postfix ;
postfix    = primary { selector } ;
selector   = "." identifier [ arguments ]
           | "." quoted-name
           | "[" integer "]" ;
primary    = number | string
           | identifier [ arguments ]
           | quoted-name
           | "(" expression ")" ;
arguments  = "(" [ argument { "," argument } ] ")" ;
argument   = identifier "=" expression
           | expression ;
integer    = digits ;
```

- Precedence, loosest first: `? :`, `||`, `&&`, `== !=`, `< <= > >=`, `+ -`,
  `* / %`, unary `- + !`, selectors. This is the order C and swak4Foam use.
- `+ - * / %`, `&&` and `||` associate to the left. `? :` associates to the
  right: `a ? b : c ? d : e` is `a ? b : (c ? d : e)`.
- Comparisons do not chain: `1 < 2 < 3` is `EXPR_SYNTAX`. Write
  `1 < 2 && 2 < 3`.
- Unary operators bind tighter than `*` but looser than a selector: `-a.x` is
  `-(a.x)`, `2 * -3` is valid.
- There is no power operator; use `pow` or `sqrt`.
- `true` and `false` are identifiers with built-in meaning (section 5).
- An identifier followed by `(` is a function call; otherwise it is a name. A
  user entry may therefore share a name with a function. A quoted name cannot
  be called.
- After `.`, a quoted name selects an entry or key with that exact spelling:
  `` settings.`wheel-left` ``.
- Parsing needs one token of lookahead everywhere except `argument`, where a
  named argument is recognised by an identifier immediately followed by `=`
  (two tokens).
- **Method form.** `x.f(a, b)` is exactly `f(x, a, b)` for the functions of
  sections 6.3 and 6.5. It is not available for construction and casts (6.4,
  6.7), `extents` (6.6), catalogue functions (6.8) or `sweep` (6.9);
  those are `EXPR_UNKNOWN_PROPERTY` in method position.
- `name = value` arguments are accepted only by catalogue functions, and those
  accept only named arguments. Built-in functions accept only positional
  arguments.

## 4. Types

| Type | Value | JSON form |
| --- | --- | --- |
| scalar | Finite double. | number |
| vector | Three scalars. | `[x, y, z]` |
| box | Axis-aligned box (section 7). | `{"min":[x,y,z],"max":[x,y,z]}`; `[xmin,xmax,ymin,ymax,zmin,zmax]` also accepted on input |
| boolean | `true` or `false`. | boolean |
| string | Literal only; used for face tokens, sync names and catalogue enumerations. | string |
| json | A JSON object, or an array that is not a vector or box, whose content is known when the expression is checked. | as is |
| unknown | A value whose type cannot be determined until it is evaluated. | — |

`line`, `plane`, `tensor`, `symmTensor`, `list` and `field` are reserved type
names for later amendments (appendix B).

Type rules:

- Every expression has one static type, determined before evaluation.
  A mismatch is `EXPR_TYPE`, reported with the expected and actual types and
  the range of the offending sub-expression.
- There are no implicit conversions between types. In particular a scalar is
  not a vector and a vector is not a box.
- `json` and `unknown` values support only `.key`, `[index]` and the casts of
  section 6.7. An `unknown` value may also be the whole result of an
  expression; the destination then validates it. Using `unknown` where a
  specific type is required is `EXPR_TYPE_UNKNOWN`.
- A scalar result is an integer when every operand was an integer and only
  `+`, `-`, `*`, `%`, unary minus, `abs`, `min`, `max`, `floor`, `ceil`,
  `round` or a conditional were applied. `/` always yields a real number.
- A boolean is not a number and a number is not a boolean. Use a comparison to
  get a boolean and a conditional (or `pos`, `neg`) to get a number.
- Every intermediate and final number must be finite; otherwise
  `EXPR_NONFINITE`.

### 4.1 Classification

A known JSON value, or a declared JSON shape, is classified as:

| Value or declaration | Type |
| --- | --- |
| Number | scalar |
| Array of exactly three numbers | vector |
| Object with exactly `min` and `max`, each three numbers | box |
| Array of exactly six numbers | box (`[xmin,xmax,ymin,ymax,zmin,zmax]`) |
| Boolean, string | boolean, string |
| Anything else | json |

### 4.2 Selection typing

`.key` and `[n]` (zero-based integer literal) select from a `json` or `unknown`
value; `[n]` also selects a vector component.

| Selecting from | Result type |
| --- | --- |
| A literal or other constant-phase value | Classification of the selected value. A missing key or index is `EXPR_UNKNOWN_PROPERTY` when checked. |
| A catalogue function result with a declared shape | Classification of the selected property's declaration. An undeclared property is `EXPR_UNKNOWN_PROPERTY` when checked. This applies in every phase, so the type does not change with the arguments' phase. |
| `unknown` | `unknown`. A missing key or index is `EXPR_UNKNOWN_PROPERTY` when evaluated. |

## 5. Names

A name resolves, in the document that contains the expression, to:

1. a direct key of `dimensions`, `settings` or `definitions`;
2. a declared sweep in `sweeps` (its value at the current visit);
3. one of the built-in names `dataExtents`, `time`, `pi`, `true`, `false`.

Rules:

- If a name matches more than one of the above, the expression is rejected
  with `EXPR_AMBIGUOUS_NAME`, listing the candidates. Nothing is chosen
  silently. Qualify the name with a reserved root to select one:
  `dimensions.radius`, `settings.radius`, `definitions.radius`, `sweeps.radius`,
  `` settings.`wheel-left` ``.
- In a workflow operation document, names resolve in that operation's own
  document. The envelope's sections are reached with the reserved root
  `workflow`: `workflow.settings.gap`.
- `dimensions`, `settings`, `definitions`, `sweeps` and `workflow` are reserved
  roots and cannot be used as bare entry names in an expression. An entry with
  such a key is reached by qualification, for example `` settings.`sweeps` `` or
  `settings.sweeps`.
- An unknown name is `EXPR_UNKNOWN_NAME`, with the available names of each
  section in the fault.
- A pipeline node is never a bare name. Its bounds are read with
  `extents(nodeId)` (section 6.6), so a node and an entry may share a name.
- Entries may refer to each other. A cycle is `EXPR_CYCLE`, listing the chain.

**Entry identity.** An entry is identified by scope, section and key, never by
key alone: `{"scope": "document", "section": "definitions", "key": "model"}`.
`scope` is `document` (the document holding the expression) or `workflow` (the
envelope). Where records from several operations appear together, each also
carries `operation`, the operation ID. Records, dependency lists and results
all use this identity.

### 5.1 Type of a named entry

| Entry value | Type |
| --- | --- |
| Literal JSON | Classification (section 4.1). |
| `{"$expr": "…"}` | The expression's type. |
| `{"$expr": {…}}` add, subtract, multiply, divide | scalar |
| `{"$calc": "vector" \| "midpoint" \| "boundsMin" \| "boundsMax"}` | vector |
| `{"$calc": "add" \| "subtract" \| "multiply" \| "divide" \| "min" \| "max"}` | scalar if both arguments are scalars; vector if either is a vector and the other a scalar or vector; unknown if either is unknown; otherwise json. |
| `{"$value": f, "args": …}`, `{"$call": f, "args": …}` | Classification of the catalogue's declared result. |
| `{"$observe": n, "path": ["bounds"]}` | box |
| `{"$sweep": a, "path": p}` | Apply `p` to each declared value of `a`, then classify. If the selected values do not all have one type, unknown. |
| `{"$analytic": …}` | Classification of the generated values (`orbit` gives json). |
| `{"$time": true}` | scalar |
| `{"$document": …}` | The type of its target. |
| Any other marker (`$observe` with another path, `$sample`, `$value` with `path`, `$artifact`, `$fill`) | unknown |

An `unknown` entry is read through selection and a cast, for example
`scalar(obs.points)` or `box(obs.bounds)`; the cast is checked when the value
arrives.

## 6. Functions and properties

In the tables, `s` is a scalar, `v` a vector, `b` a box. Wrong argument count,
an unknown named argument or an unknown token value is `EXPR_ARGUMENTS`; an
unknown function is `EXPR_UNKNOWN_FUNCTION`; an unknown property is
`EXPR_UNKNOWN_PROPERTY`.

### 6.1 Properties

| Property | On | Result | Meaning |
| --- | --- | --- | --- |
| `.x .y .z` | vector | scalar | Components. |
| `.length` | vector | scalar | Euclidean length. |
| `.valid` | box | boolean | False for an invalid box (section 7). Never faults. |
| `.min .max` | box | vector | Lower and upper corners. |
| `.mid` | box | vector | `min/2 + max/2` per axis. |
| `.size` | box | vector | `max - min` per axis; a flat axis gives 0. |
| `.span` | box | scalar | Length of the diagonal, `size.length`. |
| `.deltaX .deltaY .deltaZ` | box | scalar | `size.x`, `size.y`, `size.z`. |

Every box property except `.valid` faults with `EXPR_INVALID_BOX` on an invalid
box. On a `json` or `unknown` value these spellings are ordinary key
selections.

### 6.2 Arithmetic operators

| Operands | `+` `-` | `*` | `/` |
| --- | --- | --- | --- |
| scalar, scalar | scalar | scalar | scalar |
| vector, vector | per component | per component | per component |
| vector, scalar | per component | per component | per component |
| scalar, vector | per component | per component | per component |

These match `$calc`. Unary `-` and `+` apply to a scalar or vector. `%` is the
remainder of scalars only, with the sign of the left operand (`-7 % 3` is
`-1`). Division or remainder by zero in any component is `EXPR_DOMAIN`. No
arithmetic operator accepts a box, boolean, string, json or unknown value; use
the box functions and casts.

### 6.2a Comparison, logic and conditionals

| Form | Operands | Result | Meaning |
| --- | --- | --- | --- |
| `a < b`, `a <= b`, `a > b`, `a >= b` | scalars | boolean | Ordering. |
| `a == b`, `a != b` | two scalars, booleans, strings, vectors or boxes of the same type | boolean | Exact equality; vectors and boxes compare every component; all invalid boxes are equal. Use `near` for tolerant comparison. |
| `!a` | boolean | boolean | Not. |
| `a && b`, `a \|\| b` | booleans | boolean | And, or. |
| `c ? a : b` | `c` boolean; `a`, `b` of one type | that type | `a` when `c` is true, otherwise `b`. |
| `if(c, a, b)` | as above | that type | The same thing, spelled as a function. |

- `a` and `b` of a conditional must have the same type (`EXPR_TYPE`
  otherwise); `json` and `unknown` branches need a cast.
- **Only the chosen branch is evaluated.** `&&` and `||` likewise stop as soon
  as the answer is known. A fault in a branch that is not chosen does not
  occur, so `b.valid ? b.mid : fallback` is safe.
- **Checking is not short-circuited.** Every branch and both operands are
  parsed, name-resolved and type-checked whether or not they will be
  evaluated, so an unknown name, a wrong argument count or branches of
  different types is a fault even in a branch that can never be chosen. Only
  faults that depend on values (`EXPR_DOMAIN`, `EXPR_NONFINITE`,
  `EXPR_INVALID_BOX`, a failed cast, `FUNCTION_FAILED` and the extents and
  observation faults) are suppressed in a branch that is not chosen.
- Replacing a constant expression by its value (section 9) follows the same
  rule: a constant sub-expression in an unchosen branch is never evaluated,
  so `if(false, 1 / 0, 42)` is `42`.
- Phase and dependencies are static: a conditional has the latest phase of its
  condition and both branches, and depends on everything either branch reads.
  A `sweep` in either branch is a sweep whether or not that branch is chosen.

### 6.3 Scalar and vector functions

| Function | Result | Meaning |
| --- | --- | --- |
| `min(a, b, …)`, `max(a, b, …)` | as arguments | Two or more scalars, or two or more vectors (per component). Mixing is `EXPR_TYPE`. |
| `abs(a)` | as argument | Scalar or vector (per component). |
| `mag(a)` | scalar | `abs` of a scalar; length of a vector. |
| `magSqr(a)` | scalar | Square of `mag`. |
| `sqr(s)`, `sqrt(s)`, `cbrt(s)` | scalar | Square, square root (`s < 0` is `EXPR_DOMAIN`), cube root. |
| `pow(s, s)` | scalar | A negative base with a non-integer exponent, or a zero base with a negative exponent, is `EXPR_DOMAIN`. |
| `hypot(s, s)` | scalar | `sqrt(a² + b²)`. |
| `exp(s)`, `log(s)`, `log10(s)` | scalar | Natural exponential and logarithms; `s ≤ 0` in a logarithm is `EXPR_DOMAIN`. |
| `floor(s)`, `ceil(s)`, `round(s)` | scalar (integer) | `round` rounds halves away from zero. |
| `sign(s)` | scalar (integer) | `1` when `s ≥ 0`, otherwise `-1` (as in OpenFOAM). |
| `pos(s)`, `neg(s)` | scalar (integer) | `pos`: `1` when `s ≥ 0`, else `0`. `neg`: `1` when `s < 0`, else `0`. |
| `clamp(s, lo, hi)` | scalar | `s` limited to `[lo, hi]`; `lo > hi` is `EXPR_DOMAIN`. |
| `near(a, b, tol)` | boolean | Scalars: `abs(a - b) ≤ tol`. Vectors: `length(a - b) ≤ tol`. |
| `sin(s)`, `cos(s)`, `tan(s)` | scalar | Argument in degrees. |
| `asin(s)`, `acos(s)`, `atan(s)`, `atan2(y, x)` | scalar | Result in degrees. Out of domain is `EXPR_DOMAIN`. |
| `sinh`, `cosh`, `tanh`, `asinh`, `acosh`, `atanh` | scalar | Hyperbolic functions; dimensionless argument. |
| `deg(s)`, `rad(s)` | scalar | Radians to degrees; degrees to radians. A value in radians is passed as `sin(deg(r))`. |
| `erf(s)`, `erfc(s)`, `lgamma(s)` | scalar | Error functions and log-gamma. |
| `length(v)` | scalar | Same as `v.length`. |
| `dot(v, v)` | scalar | Dot product. |
| `cross(v, v)` | vector | Cross product. |
| `normalize(v)` | vector | Unit vector; zero length is `EXPR_DOMAIN`. |
| `lerp(a, b, t)` | as `a`, `b` | `(1 - t) * a + t * b`. `a` and `b` are both scalars or both vectors; `t` is a scalar and is not clamped. |

`pi` is a built-in name (section 5).

One rule assigns the faults of every function in this table:

- **`EXPR_DOMAIN`**: an argument is outside the set where the function has a
  finite real value. That covers undefined results and poles alike:
  `sqrt(-1)`, `log(0)`, `acos(2)`, `acosh(0)`, `atanh(1)`, `lgamma(0)`,
  `lgamma(-2)`, `pow(0, -1)`.
- **`EXPR_NONFINITE`**: the arguments are inside the domain but the result is
  too large for a double: `exp(1000)`, `pow(10, 400)`, `sinh(1000)`. The same
  code covers arithmetic overflow such as `1e308 * 10`.
- A result too small for a double is `0` and is not a fault.

### 6.4 Construction

| Function | Result | Meaning |
| --- | --- | --- |
| `vector(s, s, s)` | vector | Build a vector. |
| `box()` | box | The invalid box. |
| `box(v, v)` | box | From `min` and `max` corners. |
| `box(s, s, s, s, s, s)` | box | From `xmin, xmax, ymin, ymax, zmin, zmax`. |
| `boxAt(v, v)` | box | From centre and size. A negative size component gives the invalid box. |

Construction never faults on `min > max`; it yields the invalid box.

### 6.5 Box operations

Face tokens are the strings `'x-' 'x+' 'y-' 'y+' 'z-' 'z+'`. "Outward" means
towards negative coordinates for a `-` face and positive for a `+` face.

Unless stated otherwise, an operation given an invalid box returns the invalid
box and does not fault, and an operation whose result would have `min > max`
on any axis returns the invalid box.

| Function | Result | Meaning |
| --- | --- | --- |
| `union(b, …)` | box | One or more boxes. Smallest box containing every valid operand. Invalid operands are ignored; if all are invalid the result is invalid. |
| `intersect(b, b, …)` | box | Two or more boxes. The common region. Invalid if any operand is invalid or there is no common point. Boxes that only touch give a flat box, which is valid. |
| `overlaps(b, b)` | boolean | True when `intersect` of the two is valid; touching counts. False if either is invalid. |
| `contains(b, x)` | boolean | `x` is a box or vector. True when `x` lies inside `b`, boundary included. False if `b` or `x` is invalid. |
| `subtract(a, b)` | box | Largest box inside what remains of `a` after removing `b`; see section 7.3. |
| `subtract(a, b, keep)` | box | As above, restricted to the side named by the face token `keep`. |
| `translate(b, v)` | box | Move by `v`. |
| `inflate(b, f)` | box | `f` is a scalar or a vector of per-axis factors. Each axis size becomes `size × (1 + f)` with the centre fixed, so each face moves out by `f/2 × size`. Negative shrinks; `f = -1` collapses the axis to the centre; `f < -1` gives the invalid box. A flat axis stays flat. |
| `inflateAbs(b, d)` | box | `d` is a scalar or vector. Each axis size becomes `size + d`, centre fixed, so each face moves out by `d/2`. A flat axis becomes `d` thick. |
| `inflateX(b, f)`, `inflateY`, `inflateZ` | box | `inflate` on one axis. |
| `inflateXAbs(b, d)`, `inflateYAbs`, `inflateZAbs` | box | `inflateAbs` on one axis. |
| `push(b, face, f)` | box | Move one face outward by `f ×` the box's size along that face's axis. Negative moves it inward. |
| `pushAbs(b, face, d)` | box | Move one face outward by the distance `d`. |
| `setFace(b, face, s)` | box | Place one face at coordinate `s`. |
| `corner(b, n)` | vector | One of the eight corners; `n` is an integer literal 0 to 7. Faults with `EXPR_INVALID_BOX` on an invalid box. |

Corners are numbered as the vertices of an OpenFOAM hexahedron:

| `n` | x | y | z |
| --- | --- | --- | --- |
| 0 | min | min | min |
| 1 | max | min | min |
| 2 | max | max | min |
| 3 | min | max | min |
| 4 | min | min | max |
| 5 | max | min | max |
| 6 | max | max | max |
| 7 | min | max | max |

### 6.6 Late-bound boxes

| Form | Result | Meaning |
| --- | --- | --- |
| `extents(nodeId)` | box | Bounds of output port 0 of the pipeline node, after the node has been updated for the current visit. |
| `extents(nodeId, port)` | box | The same for another output port; `port` is an integer literal. |
| `dataExtents` | box | Union of the bounds of **every output port** of every data-loading node in the document. Invalid if there are none or all are empty. |

- The argument of `extents` is a node ID written as a name (`extents(body)`,
  ``extents(`wheel-left`)``). It is not an expression and is looked up only
  among the document's nodes. An unknown node is `UNKNOWN_NODE`.
- Coordinates are in the adaptor's model (world) frame, in the units the
  adaptor reports.
- `extents(n)` makes the expression's consumer depend on `n`, exactly as
  `$observe` does. `dataExtents` depends on every data-loading node. A node
  that would depend on itself is `PIPELINE_CYCLE`.
- Where the provider exists, `extents(n)` equals
  `box({"$observe": n, "path": ["bounds"]})`.

**Extents contract.** This is a declared, optional adaptor capability with no
framework knowledge of any application:

- An adaptor declares an extents provider in its `adaptor.json`. Discovery
  reports it as the capability `extents`. In a document of an adaptor without
  it, any use of `extents` or `dataExtents` is `EXTENTS_UNSUPPORTED`, reported
  when the document is validated.
- A node declaration marks itself as data-loading with `loadsData: true`. This
  is what `dataExtents` enumerates; the dependency planner reads it from the
  declarations, without native imports.
- For an updated node the provider returns one result per output port the
  object actually has, in port order. Each result is one of: six finite
  numbers; **empty** (the output has no geometry at this visit); **not
  spatial** (the output has no bounds by nature, for example a table).

| Provider result | `extents(n, port)` | Contribution to `dataExtents` |
| --- | --- | --- |
| Six numbers | That box. | Included. |
| Empty | The invalid box; no fault until a coordinate is read. | Ignored. |
| Not spatial | Fault `EXTENTS_UNAVAILABLE`. | Ignored. |
| No such port | Fault `INVALID_OUTPUT_PORT` (existing code); reported at validation when the declaration fixes the number of ports, otherwise at the visit. | — |

### 6.7 Casts

| Function | Meaning |
| --- | --- |
| `scalar(x)` | Asserts a finite number. |
| `vector(x)` | Asserts an array of three finite numbers. |
| `box(x)` | Asserts `{min,max}` or a six-number array. |

The one-argument forms of `vector` and `box` are casts; `x` must be `json` or
`unknown`, or already the target type. A cast of a known value is checked
statically. Otherwise it is checked when the value is available; failure is
`EXPR_TYPE`.

### 6.8 Catalogue functions

Any function in the registered function catalogue (`boundsFrame`, `fitCamera`,
`orbitCameras`, `slicePositions`, `directionVector`, … and functions an adaptor
registers) can be called with named arguments:

```text
fitCamera(bounds = model.inflate(0.52), direction = 'x+')
```

- Arguments are checked against the function's declaration; defaults apply.
- A box argument is passed in the form the parameter declares (`{min,max}` or
  six numbers).
- The result type is the classification of the declared result; selection
  from it follows section 4.2, so `fitCamera(bounds = model).focalPoint.x` is
  a scalar.
- A catalogue function may not have the same name as a built-in function;
  registration rejects it.
- Functions that take or return process-local objects (`objectKind`) cannot be
  called from an expression (`EXPR_UNKNOWN_FUNCTION`).
- A failure inside the function is `FUNCTION_FAILED`, as today.

### 6.9 Sweeps

| Function | Result | Meaning |
| --- | --- | --- |
| `sweep(a, b, count)` | as `a`, `b` | Declares a scheduled sweep with `count` positions. At a visit whose coordinate **on that sweep** is `i`, it evaluates to `lerp(a, b, i / (count - 1))`. |
| `sweep(a, b, count, sync)` | as `a`, `b` | As above; sweeps and `$analytic` members with the same `sync` string share one sweep and advance together. |

- `a` and `b` are both scalars or both vectors and may be late (visit or
  observed phase). They are re-evaluated at every visit.
- `count` must be a constant-phase integer from 1 to the document's
  `maxStates`; otherwise `SWEEP_COUNT`. The number of visits is therefore known
  at planning time even when the endpoints are not.
- `count = 1` evaluates to `lerp(a, b, 0.5)`.
- A sweep is accepted where a member `$analytic` is accepted today (varying,
  non-constructor options and entries read by them). Elsewhere it is
  `SWEEP_PLACEMENT`.
- An existing sweep is used by name: `lerp(model.min, model.max, t)` where `t`
  is a declared sweep. An entry holding `$sweep` or `$analytic` is used by its
  entry name in the same way.

**Sweeps and visits.**

- Each `sweep(…)` in the text is one sweep, owned by the marker that contains
  it. An entry that contains a sweep and is read in several places is still one
  sweep, so every reader sees the same position.
- Only sweeps reachable from the options of the active (selected) nodes
  contribute visits, as with existing sweeps. A sweep in an entry nothing active
  reads contributes none.
- Sweep identity: `sweep:<pointer>#<n>`, where `<pointer>` is the JSON pointer
  of the owning `$expr` marker and `<n>` the zero-based order of that
  `sweep(` in its text. Sweeps and analytics sharing a `sync` string are the
  single sweep `sync:<name>`; their counts must be equal
  (`ANALYTIC_LENGTH_MISMATCH`). These identities cannot collide with declared
  sweep names.
- Order, fastest first: declared sweeps in `sweeps` order (as today); then
  generated sweeps (sweeps and member analytics together) in order of first use,
  walking active nodes in `nodes` order, each node's options in authored key
  order, each expression left to right, and entering a named entry at its
  first reference. Time is slowest, as today. Plans and reports list this order
  as `sweepsFastestFirst`.
- A visit's state is its time index and one coordinate per sweep. Two sweeps
  without a common `sync` are independent; the number of states is the product
  of the counts and is bounded by `maxStates` (`EXPANSION_TOO_LARGE`).

**One schedule for the whole run (amendment 7).**

- A run has one schedule, and every sweep is stepped by it: a declared sweep,
  a `sweep(…)` and an `$analytic`, whether the ends are constant, change with
  time or wait for observed data. Nothing steps a sweep a second time on its
  own.
- Everything that shares a `sync` string advances together across the whole
  run: across the options and named entries of a document and across the
  operations of a workflow, including a member whose ends are late. The
  counts are equal everywhere (`ANALYTIC_LENGTH_MISMATCH`).
- A `sync` string used in two operations makes the workflow one schedule.
  Each visit runs every operation once, at the same position on that sweep.
  Operations that share no `sync` string, no envelope sweep and no named
  analytic are planned on their own, as before.
- The order above holds across the run. In a workflow the declared sweeps of
  the envelope come first, then those of each operation in `operations`
  order, then generated sweeps in order of first use, walking the operations
  in that order. A declared sweep therefore steps faster than a `sync` group,
  also when a member of that group waits for data.
- Where the schedule is made before the application starts (a study: for
  example a document that holds an `$analytic` or a `$sweep` in `dimensions`,
  `settings` or `definitions`, a workflow whose envelope declares a sweep or
  names an analytic, or a workflow as above), each visit is one run of the
  application. A pipeline is then told where the
  schedule stands: the chosen value of each declared sweep, and its position
  on every other sweep. It evaluates a late end at that position, steps
  nothing but its own `times`, and reports one position per sweep. Within
  such a visit time is therefore the fastest, as it has been for studies.
- The number of visits, times the number of times of a pipeline that still
  evaluates something at its own visits, is bounded by `maxStates`
  (`EXPANSION_TOO_LARGE`). In a workflow the bound is the envelope's
  `maxStates` unless the operation states its own.
- An operation whose late values read the envelope's entries is given their
  values at the visit. An entry that waits only for the envelope's sweeps is
  a value by then.
- The positions travel in a visit's document under the internal fields
  `%%studyPositions%%` (sweep identity to zero-based position) and
  `%%studyVisits%%` (the number of visits). The schedule writes them. A
  document that carries them is one visit and is not planned again.
- A field name written between double percent signs is reserved for records
  Schemaxis adds itself. The command line and Studio's validation refuse an
  authored document that uses one (`RESERVED_KEY`), as strict MCP admission
  already does by refusing unknown fields.
- An `$analytic` whose ends are a verified result of an earlier operation
  (`$value` with `path`) cannot be scheduled before that operation has run.
  Its own operation steps it afterwards. It may share its `sync` name only
  with analytics that wait in the same operation; a workflow that shares the
  name with anything else is refused (`UNSCHEDULABLE_SYNC`), because the two
  could not step together. What an analytic waits for is read after its
  document references are followed. Another sweep of that operation whose
  ends do not wait for the result steps with the run as usual.

## 7. Box semantics

### 7.1 Forms

The canonical form is `{"min":[x,y,z],"max":[x,y,z]}`. The six-number form
`[xmin,xmax,ymin,ymax,zmin,zmax]` is accepted wherever a box is read: named
entries, catalogue function arguments, casts and adaptor observations. When an
expression's box result is written to a destination, it takes the form the
destination declares:

| Destination | Form written |
| --- | --- |
| Option or catalogue parameter declared as six numbers | six numbers |
| Option or catalogue parameter declared as `{min,max}` | canonical |
| Argument of `$calc` | six numbers (the only form its bounds operations read) |
| Argument of object-form `$expr`, named entry, record, result, undeclared destination | canonical |

### 7.2 Validity

- A box is **valid** when `min ≤ max` on all three axes. Zero size on one, two
  or three axes (a patch, a line, a point) is valid.
- A box is **invalid** when `min > max` on any axis. All invalid boxes are the
  same value. Its canonical form is `min (1,1,1)`, `max (-1,-1,-1)`
  (`[1,-1,1,-1,1,-1]`), and that is what is written whenever an invalid box is
  serialised. It is what an unset or empty box holds.
- VTK and ParaView follow the same convention: bounds with `min > max` on an
  axis mean the object has no valid geometry. The ParaView provider therefore
  reports any such bounds as **empty** (section 7.1), whatever the six numbers
  are, and they arrive as the invalid box.
- Coordinates must be finite; a non-finite coordinate is `EXPR_NONFINITE`, not
  an invalid box.
- An invalid box may be held in a named entry, combined, tested with `.valid`,
  and reported by the CLI and Studio. Reading a coordinate of it
  (section 6.1), or delivering it as the value of an operation option, is
  `EXPR_INVALID_BOX`, naming the entry or sub-expression that produced it.

`contains` and `overlaps` return false for invalid operands by decision: an
invalid box means "no box", and neither question has a useful true answer for
it.

### 7.3 `subtract`

Let `c = intersect(a, b)`.

1. If `a` is invalid the result is invalid.
2. If `c` is invalid (`b` invalid or no common point) the result is `a`.
3. Otherwise up to six candidates exist, one per face token. The candidate for
   `x-` is `a` with `max.x` set to `c.min.x`, and exists when
   `c.min.x > a.min.x`. The candidate for `x+` is `a` with `min.x` set to
   `c.max.x`, and exists when `c.max.x < a.max.x`. Likewise for `y` and `z`.
4. `subtract(a, b)` returns the largest candidate, comparing in order: volume,
   then total face area (`dx·dy + dy·dz + dz·dx`), then span, then the fixed
   order `x- x+ y- y+ z- z+` (first wins). The later measures make the result
   well defined when `a` is flat.
5. `subtract(a, b, keep)` returns the candidate for `keep`.
6. If the required candidate does not exist (in 4, none exists because `b`
   covers `a`), the result is invalid.

Boundary convention: boxes are closed, so the result shares the cut face with
`b`. `overlaps(subtract(a, b), b)` is therefore usually **true** (they touch).
The result's interior never intersects `b`'s interior.

## 8. Phases

Each expression, and each named entry, has one phase, derived from its
dependencies. The author does not declare it.

| Phase | Depends on | Known |
| --- | --- | --- |
| constant | Literals and constant entries only. | When the document is resolved, before planning. |
| visit | A declared sweep, a `sweep(…)`, `time`, an `$analytic`. | At each scheduled visit, before any native update. |
| observed | `extents`, `dataExtents`, `$observe`, `$sample`. | At each visit, after the nodes it depends on have been updated. |

- The phase of an expression, or of any marker, is the latest phase among its
  parts and the entries it reads (constant < visit < observed).
- An entry that reads a verified result of an earlier workflow operation
  (`$value` with `path`, `$artifact`) is constant inside its own operation, but
  cannot be resolved until that producer has been verified. Records show this
  as `awaits` with the producer's ID.
- A named entry is evaluated at most once per visit; every reader in that visit
  sees the same value.
- An observed expression in an option of node `N` is evaluated after every node
  it depends on has been updated for the visit and before `N` is configured.

### 8.1 Where each phase is accepted

| Destination | constant | visit | observed |
| --- | --- | --- | --- |
| Entry in `dimensions`, `settings`, `definitions` | yes | yes | yes |
| Node option, not a constructor option | yes | yes | yes |
| Node constructor option | yes | no | no |
| Scene camera and appearance values | yes | declared sweeps and `time`, as today; no `sweep` | yes |
| `sweeps[].values`, `sweeps[].series`, `times`, `maxStates` | yes | no | no |
| `sweep` count, `extents` port, `[index]` | yes | no | no |
| `$analytic` `linear` `start`, `end` | yes | yes | yes |
| Other `$analytic` keys (`values`, `count`, `orbit` keys) | yes | no | no |
| Options of adaptors without a scheduled graph | yes | where the common runtime schedules studies today | only with the extents capability |

Acceptance is by dependency, not only by the single phase label: a scene value
may depend on declared sweeps, `time` and observed data together, so
`t + extents(body).min.x` is accepted in a camera, while anything containing a
`sweep` is `SWEEP_PLACEMENT` there. Observed values in scene cameras are new
with this work; they are what lets a camera frame `model.inflate(0.52)` when
`model` is built from `extents`.

### 8.2 Reporting misuse

A destination that does not accept an expression's dependencies rejects it when
the document is validated, before any native process starts. The fault names
the destination, the entry, and the dependency that makes it late, following
the chain of entries. For a constructor option the existing code
`DYNAMIC_CONSTRUCTOR` is kept so current clients keep working:

```text
DYNAMIC_CONSTRUCTOR at $/nodes/3/options/resolution
`cells` cannot be used in constructor option slicer.resolution: it is only
known after node `body` has been updated (cells → model → extents(body)).
```

Every other destination uses `EXPR_PHASE` with the same message form and
observed fields.

## 9. Evaluation rules

- Arithmetic is IEEE 754 double precision. Results are not rounded. `.mid` is
  computed as `min/2 + max/2`.
- Evaluation has no side effects and is deterministic: the same document,
  state and observations give the same value.
- Argument evaluation order is not observable.
- A fault in any evaluated sub-expression is the fault of the whole
  expression; there is no way to catch one. Avoid a fault by testing first:
  `b.valid ? b.mid : fallback` (section 6.2a).
- Constant expressions are replaced by their value when the document is
  resolved, and recorded in provenance as `$value` functions are today. A
  constant sub-expression in a branch that is not chosen is not evaluated
  (section 6.2a).

## 10. Faults

All are structured faults with the stable codes below.

- `location` is `$` followed by the RFC 6901 pointer of the `$expr` marker in
  the document that was submitted, as existing document faults are written:
  `$/definitions/model`; inside a workflow,
  `$/operations/2/document/definitions/model`.
- For faults inside the text, `observed` carries `expression` (the text) and
  `position` and `length`, counted in **Unicode code points** from zero. Studio
  converts to UTF-16 offsets at the browser boundary; the host never emits
  UTF-16 offsets.
- Faults found before evaluation have phase `input`; faults during evaluation
  have phase `pipeline`.

| Code | Raised when | `observed` also holds |
| --- | --- | --- |
| `EXPR_SYNTAX` | The text does not match the grammar, or uses a reserved character. | `expected` (token kinds), `found`, `reserved` |
| `EXPR_LIMIT` | Length, depth or node limit exceeded. | `limit`, `actual` |
| `EXPR_UNKNOWN_NAME` | A name resolves to nothing. | `name`, `available` |
| `EXPR_AMBIGUOUS_NAME` | A name resolves to more than one thing. | `name`, `candidates` |
| `EXPR_UNKNOWN_FUNCTION` | No built-in or callable catalogue function has that name. | `name`, `available` |
| `EXPR_UNKNOWN_PROPERTY` | Property, key, index or method does not exist on that value. | `name`, `type`, `available` |
| `EXPR_ARGUMENTS` | Wrong count, wrong named argument, or an unknown token value such as a face. | `function`, `expected` |
| `EXPR_TYPE` | A value has the wrong type, statically, in a cast, or for its destination. | `expected`, `actual` |
| `EXPR_TYPE_UNKNOWN` | An `unknown` value is used where a type is required, without a cast. | `source` |
| `EXPR_CYCLE` | Entries refer to each other in a loop. | `chain` |
| `EXPR_PHASE` | The destination does not accept the expression's dependencies. | `variable`, `phase`, `accepted`, `chain` |
| `DYNAMIC_CONSTRUCTOR` | As `EXPR_PHASE`, for a constructor option (existing code). | as `EXPR_PHASE` |
| `EXPR_INVALID_BOX` | A coordinate of an invalid box is read, or an invalid box reaches an option. | `source` (entry or sub-expression) |
| `EXPR_DOMAIN` | A function or operator is outside its domain: division or remainder by zero, `sqrt` or `log` of a negative, `normalize` of zero, and the like. | `function`, `arguments` |
| `EXPR_NONFINITE` | A result is not finite although the operands were in the domain (overflow). | `function` or `operator`, `arguments` |
| `SWEEP_COUNT` | Count is not a constant integer in range. | `count`, `limit` |
| `SWEEP_PLACEMENT` | A sweep is used where scheduled variation is not accepted. | `destination` |
| `EXTENTS_UNSUPPORTED` | `extents` or `dataExtents` is used and the document's adaptor has no extents capability. | `adaptor` |
| `EXTENTS_UNAVAILABLE` | The selected output has no spatial bounds. | `node`, `port` |

Existing codes reused with their current meaning: `UNKNOWN_NODE`,
`INVALID_OUTPUT_PORT`, `PIPELINE_CYCLE`, `OBSERVATION_UNAVAILABLE` (bounds
requested before the node was updated), `FUNCTION_FAILED`, `INVALID_ANALYTIC`,
`ANALYTIC_LENGTH_MISMATCH`, `EXPANSION_TOO_LARGE`, `INVALID_EXPRESSION`
(wrapper has extra keys, or the object form is malformed).

## 11. Records and results

### 11.1 Entry record

One record describes one named entry of type scalar, vector or box (a "spatial
entry"), or one ad-hoc expression:

```json
{
  "entry": {"scope": "document", "section": "definitions", "key": "model"},
  "operation": "render",
  "expression": "union(extents(body), extents(wheels))",
  "type": "box",
  "phase": "observed",
  "dependsOn": {
    "entries": [],
    "nodes": [{"node": "body", "port": 0}, {"node": "wheels", "port": 0}],
    "sweeps": [],
    "awaits": []
  },
  "state": "resolved",
  "value": {"min": [0, -1, 0], "max": [4.5, 1, 1.4]},
  "valid": true,
  "source": {"kind": "live", "inputDigest": "…", "state": {"timeIndex": 0, "indices": {}}}
}
```

- `operation` is present only for records from a workflow. `expression` is
  absent for literal entries. An ad-hoc expression has no `entry`.
- `dependsOn.entries` holds entry identities (section 5); `sweeps` holds sweep
  identities (section 6.9); `awaits` holds producer operation IDs. All are
  transitive.
- `state` is `resolved`, `unresolved` (with `reason`: `needs-data`,
  `stale-data`, `needs-state`, `awaits-producer`) or `fault` (with `fault`).
- `value`, `valid` and `source` are present only when `state` is `resolved`.
  `valid` is present only for a resolved box. Nothing is ever reported for an
  unresolved entry beyond its type, phase and dependencies.
- `source.kind` is `literal`, `constant`, `live` or `run`. `inputDigest` is the
  digest of the input the data came from; `state` is the visit it belongs to.

### 11.2 In verified results

A run writes its spatial entries into each **verified receipt**
(`verification.json`), which is what `$value` with `path` already reads:

```json
"spatial": {
  "sweepsFastestFirst": ["sweep:/nodes/2/options/origin/$expr#0"],
  "inputs": {
    "extents": [
      {"node": "body", "port": 0, "values": [[0, 4.5, -0.9, 0.9, 0.2, 1.4], [0, 4.5, -0.9, 0.9, 0.2, 1.4]]}
    ],
    "observations": [],
    "samples": [],
    "upstream": [],
    "updated": [{"node": "body", "values": [true, true]}]
  },
  "entries": {
    "definitions": {"model": {"type": "box", "phase": "observed", "values": [{"min": [0, -1, 0], "max": [4.5, 1, 1.4]}, {"min": [0, -1, 0], "max": [4.5, 1, 1.4]}]}},
    "settings":    {"model": {"type": "box", "phase": "constant", "values": [{"min": [0, 0, 0], "max": [1, 1, 1]}, {"min": [0, 0, 0], "max": [1, 1, 1]}]}}
  }
}
```

- `entries` is keyed by section, then key, so same-named entries in different
  sections stay distinct. Each operation has its own receipts, so the operation
  is identified by the `$value` reference itself.
- `values` has one element per graph visit covered by that receipt, in visit
  order; a receipt covering one visit has one element. An element is the value
  in canonical form, the canonical invalid box, or `null` when the entry was
  not resolved at that visit.
- `inputs` records every late value a spatial entry read, one element per
  visit, so the entries can be replayed without the native application:
  `extents` (six numbers, the canonical invalid six numbers for empty, `null`
  for not spatial); `observations`, one item per `$observe` read, as
  `{"node", "path", "values"}`; `samples`, one item per `$sample` marker, as
  `{"pointer", "values"}`; `updated`, one item per node read, as
  `{"node", "values"}`, saying whether the node was updated at each visit.
  `upstream` is always an empty list: a value read from a verified producer
  (`$value` with `path`, or `$artifact`) is bound into the operation's
  document before it runs and is recorded and verified as that operation's
  handoff, not here (amendments 1 and 3).
- An entry that nothing active reads is still recorded when its dependencies
  were updated; if it cannot be evaluated its element is `null` and the run is
  not failed by it.
- Verification recomputes every entry from the recorded `inputs`, sweeps and
  time, and fails with `VERIFICATION_FAILED` on any difference. Numbers are
  compared to a tolerance of 1e-12, relative and absolute. A receipt with no
  spatial record is a difference whenever the document has a scalar, vector
  or box entry (amendments 2 and 4). An entry whose
  inputs are not all recorded has `null` values and is not offered for
  handoff. The guarantee is about the evaluation: the recorded inputs
  themselves are adaptor observations and carry the same trust as existing
  observations, no more.

Reading it from a later operation uses the existing mechanism unchanged,
including `AMBIGUOUS_VALUE` when several producer receipts exist and `visit` is
omitted. Producer `measure` has both `settings.model` and `definitions.model`
and two graph visits in one receipt; the consumer takes the second visit of
the `definitions` entry:

```json
{"definitions": {"upstream": {"$value": "measure", "path": "/spatial/entries/definitions/model/values/1"}}}
```

```text
box(upstream).inflate(0.1)
```

When the producer instead ran as isolated visits (one receipt per visit), the
same selection is `"visit": 1` with `path` ending `/values/0`.

## 12. Compatibility and legacy markers

- A document containing no string `$expr` gives the same results as before.
- Old markers and the new language may be mixed: an entry written with any
  marker can be read by name, and a string `$expr` can appear inside the
  arguments of `$call`, `$calc`, `$value` and object-form `$expr`, and as the
  `start` or `end` of an `$analytic` `linear`.

One phase rule applies to every marker (section 8): a marker is evaluated at
the latest phase of its arguments. Consequences:

| Marker | Rule |
| --- | --- |
| `$value` with `args` | Constant arguments: resolved at document resolution, as today. Late arguments: accepted, evaluated at their phase. `$value` with `args` and `$call` are then equivalent. |
| `$call` | Late arguments: as today. Constant arguments: constant; the value is the same as today, a failure is reported at validation instead of at the visit, and it is now accepted in a constructor option. |
| `$calc` | Phase of its arguments. A box argument produced by a string expression arrives as six numbers (section 7.1). |
| Object-form `$expr` | Phase of its arguments; arithmetic on late scalars is evaluated at their phase. |
| `$analytic` `linear` | `start` and `end` may be late; it then behaves as `sweep(start, end, count, sync)` and its sweep follows section 6.9. With `count: 1` the endpoints must be equal at each visit, else `INVALID_ANALYTIC` at that visit. `values`, `count` and `orbit` keys stay constant. |

The two review cases:

| Input | Phase | Result |
| --- | --- | --- |
| `{"$value":"boundsCentre3D","args":{"bounds":{"$expr":"extents(bodySurface)"}}}` | observed; evaluated after `bodySurface` is updated | `[2.25, 0, 0.8]` with the fixture of section 13 |
| `{"$calc":"midpoint","args":[{"$expr":"box(0, 2, 0, 4, 0, 6)"}]}` | constant | `[1, 2, 3]` |

Catalogue functions `boundsCentre`, `boundsCentre3D`, `boundsSize`,
`boundsExtend`, `boundsUnion`, `boundsFrame`, `boundsFromExtents`,
`boundsPoint`, `slicePositions`, `fitCamera` and `orbitCameras` keep their
names, arguments and results. Inputs that were valid before give the same
results. Two deliberate relaxations:

- each accepts either box form;
- flat boxes are accepted, with one qualification: `fitCamera` and
  `orbitCameras` fail with `FUNCTION_FAILED` ("bounds have no extent in this
  view") when the computed `scale` or `distance` is exactly zero, which
  happens for a point box and for a line box viewed along its length. No
  tolerance is applied; give the box thickness first, for example with
  `inflateAbs`.

`$calc` `midpoint`, `boundsMin` and `boundsMax` are unchanged.

Equivalences, for orientation:

| Existing | String form |
| --- | --- |
| `{"$call":"boundsCentre","args":{"bounds":{"$observe":"data","path":["bounds"]}}}` | `extents(data).mid` |
| `{"$calc":"multiply","args":[{"$sweep":"offset"},2]}` | `offset * 2` |
| `{"$value":"boundsExtend","args":{"bounds":B,"before":[0.1,0.1,0.1],"after":[0.1,0.1,0.1]}}` | `B.inflate(0.2)` |
| `{"$analytic":{"type":"linear","start":0,"end":1,"count":5}}` | `sweep(0, 1, 5)` |

## 13. Worked examples

All examples use this document fragment. `wheels` is deliberately in the
six-number form and `ground` is flat.

```json
{
  "dimensions": {"wheelbase": 2.7},
  "settings": {"zoom": 0.52},
  "definitions": {
    "body":   {"min": [0, -0.9, 0.2], "max": [4.5, 0.9, 1.4]},
    "wheels": [0.5, 3.6, -1, 1, 0, 0.7],
    "ground": {"min": [-10, -5, 0], "max": [20, 5, 0]},
    "model":  {"$expr": "union(body, wheels)"},
    "car":    {"$expr": "union(extents(bodySurface), extents(wheelSurface))"}
  },
  "sweeps": [{"name": "t", "values": [0, 0.5, 1]}]
}
```

For the observed examples, node `bodySurface` reports
`[0, 4.5, -0.9, 0.9, 0.2, 1.4]` and `wheelSurface` reports
`[0.5, 3.6, -1, 1, 0, 0.7]`, so `car` equals `model` once data is loaded.
Numeric results are exact unless marked ≈; comparisons use a relative
tolerance of 1e-12.

### 13.1 Twenty examples

| # | Expression | Type, phase | Expected result |
| --- | --- | --- | --- |
| 1 | `2 * wheelbase + 0.3` | scalar, constant | `5.7` |
| 2 | `union(body, wheels)` | box, constant | `{min:[0,-1,0], max:[4.5,1,1.4]}` |
| 3 | `model.size` | vector, constant | `[4.5, 2, 1.4]` |
| 4 | `model.span` | scalar, constant | ≈ `5.119570294468081` |
| 5 | `model.inflate(zoom)` | box, constant | ≈ `{min:[-1.17,-1.52,-0.364], max:[5.67,1.52,1.764]}` |
| 6 | `vector(model.mid.x, model.max.y, model.min.z)` | vector, constant | `[2.25, 1, 0]` |
| 7 | `intersect(body, wheels)` | box, constant | `{min:[0.5,-0.9,0.2], max:[3.6,0.9,0.7]}` |
| 8 | `intersect(body, ground).valid` | boolean, constant | `false` (the invalid box) |
| 9 | `intersect(body, ground).mid` | vector, constant | fault `EXPR_INVALID_BOX`, source `intersect(body, ground)` |
| 10 | `union(model, intersect(body, ground))` | box, constant | `{min:[0,-1,0], max:[4.5,1,1.4]}` (invalid operand ignored) |
| 11 | `ground.inflate(0.1)` | box, constant | `{min:[-11.5,-5.5,0], max:[21.5,5.5,0]}` (stays flat) |
| 12 | `subtract(ground, model)` | box, constant | `{min:[4.5,-5,0], max:[20,5,0]}` (candidate areas: `x-` 100, `x+` 155, `y-` 120, `y+` 120) |
| 13 | `subtract(ground, model, 'y-')` | box, constant | `{min:[-10,-5,0], max:[20,-1,0]}` |
| 14 | `model.push('x+', 2).pushAbs('z+', 0.5)` | box, constant | `{min:[0,-1,0], max:[13.5,1,1.9]}` |
| 15 | `model.setFace('z-', -0.1).inflateYAbs(1)` | box, constant | `{min:[0,-1.5,-0.1], max:[4.5,1.5,1.4]}` |
| 16 | `contains(model, vector(2, 0, 5))` | boolean, constant | `false` |
| 17 | `lerp(model.min, model.max, t)` | vector, visit | 3 visits: `[0,-1,0]`, `[2.25,0,0.7]`, `[4.5,1,1.4]` |
| 18 | `sweep(model.min.y, model.max.y, 5)` | scalar, visit | 5 visits: `-1`, `-0.5`, `0`, `0.5`, `1` |
| 19 | `vector(car.mid.x, sweep(car.min.y, car.max.y, 5), car.max.z)` | vector, observed | 5 visits: `[2.25,-1,1.4]`, `[2.25,-0.5,1.4]`, `[2.25,0,1.4]`, `[2.25,0.5,1.4]`, `[2.25,1,1.4]`; consumer depends on `bodySurface`, `wheelSurface` |
| 20 | `fitCamera(bounds = car.inflate(zoom), direction = 'x+')` | json, observed | camera with `focalPoint [2.25,0,0.7]`, `direction [1,0,0]`, `up [0,0,1]`, `scale` ≈ `1.2236`, `distance` ≈ `15.563493695182968`, `bounds` ≈ `[-1.17,5.67,-1.52,1.52,-0.364,1.764]` |

### 13.2 Further acceptance cases

Boxes and syntax:

- `model.inflate(-2).valid` is `false`; `model.inflate(-1)` is the point box
  `{min:[2.25,0,0.7], max:[2.25,0,0.7]}`.
- `subtract(model, ground)` is `model`. The two touch at `z = 0`, so `c` is the
  flat box `{min:[0,-1,0], max:[4.5,1,0]}`. The only candidate that exists is
  `z+` (`c.max.z = 0 < 1.4`), and it is `model` itself.
  `overlaps(subtract(model, ground), ground)` is `true`.
- `model.push('x+', 2` is `EXPR_SYNTAX` at position 18 (end of input); the
  expected tokens include `)` and `,`.
- With the quoted entry `😀` defined, `` `😀` + missing `` is
  `EXPR_UNKNOWN_NAME` with `position` 6, `length` 7 (code points).
- `fitCamera(bounds = box(0,0,0,0,0,0))` is `FUNCTION_FAILED`.
  `model.fitCamera(direction = 'x+')` is `EXPR_UNKNOWN_PROPERTY`.

Conditionals, comparisons and functions:

- `model.deltaX > model.deltaY ? 'x+' : 'y+'` is the string `'x+'`.
- `intersect(body, ground).valid ? intersect(body, ground).mid : model.mid`
  is `[2.25, 0, 0.7]`, with no fault.
- `if(t >= 0.5, model.max.z, model.min.z)` is visit phase: `0`, `1.4`, `1.4`.
- `model.valid && model.span > 5` is `true`.
- `model.min == vector(0, -1, 0)` is `true`; `1 == 1.0` is `true`.
- `true ? 1 : vector(0, 0, 0)` is `EXPR_TYPE`. `1 < 2 < 3` is `EXPR_SYNTAX`.
  `2 ^ 3` is `EXPR_SYNTAX` with `reserved: true`. `1 && true` is `EXPR_TYPE`.
- `if(false, 1 / 0, 42)` is `42`; `false && (1 / 0 > 0)` is `false`;
  `true || (1 / 0 > 0)` is `true`; `if(true, 1 / 0, 42)` is `EXPR_DOMAIN`.
- `if(false, missing, 42)` is `EXPR_UNKNOWN_NAME`; `if(false, 'a', 42)` is
  `EXPR_TYPE`; `false && sqrt(1, 2) > 0` is `EXPR_ARGUMENTS`.
- `acosh(0)`, `atanh(1)` and `lgamma(0)` are each `EXPR_DOMAIN`; `exp(1000)`
  is `EXPR_NONFINITE`; `exp(-1000)` is `0`.
- `min(1, 2)` is `1`; `pos(3)` is `1`; `min(1)` and `pos()` are each
  `EXPR_ARGUMENTS` with `reserved: true`; `grad(1)` is
  `EXPR_UNKNOWN_FUNCTION` with `reserved: true`.
- `7 % 3` is `1`; `-7 % 3` is `-1`; `pos(-2)` is `0`; `sign(0)` is `1`;
  `clamp(7, 0, 5)` is `5`.
- `atan2(1, 1)` is `45`; `sin(deg(pi / 2))` is ≈ `1`; `hypot(3, 4)` is `5`.
- `model.corner(0)` is `[0, -1, 0]`; `model.corner(2)` is `[4.5, 1, 0]`;
  `model.corner(6)` is `[4.5, 1, 1.4]`; `model.corner(8)` is `EXPR_ARGUMENTS`.

Names:

- With `settings.wheel-left = 1` and `definitions.wheel-left = 2`:
  `` `wheel-left` `` is `EXPR_AMBIGUOUS_NAME`;
  `` settings.`wheel-left` `` is `1`; `` definitions.`wheel-left` + 1 `` is `3`.
- With `settings.sweeps = 4`: `` settings.`sweeps` `` and `settings.sweeps` are `4`;
  bare `sweeps` alone is `EXPR_TYPE` (a reserved root is not a value).
- With an entry `definitions.t` added beside the sweep `t`, example 17 is
  `EXPR_AMBIGUOUS_NAME`, candidates `definitions.t`, `sweeps.t`;
  `lerp(model.min, model.max, sweeps.t)` is accepted.

Phases:

- `car.span` as a node constructor option is rejected at validation with
  `DYNAMIC_CONSTRUCTOR`, variable `car`, chain `car → extents(bodySurface)`.
- `t + extents(bodySurface).min.x` in a scene camera value is accepted
  (observed; values `0`, `0.5`, `1` over the three visits).
  `sweep(0, 1, 3)` in the same place is `SWEEP_PLACEMENT`.

Sweeps, in a varying vector option `origin` of node index 2:

- `vector(sweep(0, 1, 2), sweep(10, 20, 2), 0)` has sweeps
  `sweep:/nodes/2/options/origin/$expr#0` (fastest) and `…#1`, and four visits
  in this order: `[0,10,0]`, `[1,10,0]`, `[0,20,0]`, `[1,20,0]`.
- `vector(sweep(0, 1, 3, 's'), sweep(10, 30, 3, 's'), 0)` has the single sweep
  `sync:s` and three visits: `[0,10,0]`, `[0.5,20,0]`, `[1,30,0]`.
- With `definitions.y = {"$expr": "sweep(-1, 1, 3)"}`, `vector(y, 2 * y, 0)`
  has the single sweep `sweep:/definitions/y/$expr#0` and three visits:
  `[-1,-2,0]`, `[0,0,0]`, `[1,2,0]`.
- `sweep(0, 10, 1)` is `5` in its single visit.
- A `definitions` entry containing a sweep that no active node reads adds no
  visits.

Typing, with

```json
{
  "settings": {"options": {"gap": 0.25}},
  "definitions": {
    "v":   {"$calc": "multiply", "args": [[1, 2, 3], 2]},
    "x":   {"$sweep": "samples", "path": ["x"]},
    "obs": {"$observe": "bodySurface"}
  },
  "sweeps": [{"name": "samples", "values": [{"x": 1}, {"x": 2}]}]
}
```

- `v.x` is a scalar, `2`.
- `x + 1` is a scalar, visit phase: `2`, `3`.
- `settings.options.gap + 1` is a scalar, `1.25`.
- `fitCamera(bounds = model).focalPoint.x` is a scalar, `2.25`.
  `fitCamera(bounds = model).nothing` is `EXPR_UNKNOWN_PROPERTY` when checked.
- `obs.points * 2` is `EXPR_TYPE_UNKNOWN`. `scalar(obs.points) * 2` is a
  scalar, observed. `box(obs.bounds).mid` is a vector, `[2.25, 0, 0.8]`.

Extents:

- A data-loading node `reader` with port 0 `[0,1,0,1,0,1]` and port 1
  `[10,11,0,1,0,1]`: `extents(reader)` is `{min:[0,0,0], max:[1,1,1]}`,
  `extents(reader, 1)` is `{min:[10,0,0], max:[11,1,1]}`, `dataExtents` is
  `{min:[0,0,0], max:[11,1,1]}`. `extents(reader, 2)` is
  `INVALID_OUTPUT_PORT`.
- In a document of an adaptor without the extents capability, `dataExtents`
  and `extents(a)` are each `EXTENTS_UNSUPPORTED` at validation.
- `extents(table)` where the output is a table is `EXTENTS_UNAVAILABLE`.

## 14. Decisions

Decided by the approver on 10 November 2026:

1. The language has comparisons, logic and conditionals, and is to grow
   towards the capabilities of swak4Foam (appendix B).
2. `contains` and `overlaps` are false for invalid operands, while `union`
   treats an invalid operand as empty.
3. Shrinking past zero yields the invalid box rather than a fault.
4. `sweep` with `count = 1` gives the midpoint.
5. Trigonometric functions take and return degrees.
6. Box corners use the OpenFOAM hexahedron numbering.
7. Catalogue functions are callable with named arguments; a `loadsData`
   declaration flag; relaxed `bounds*` functions; ambiguous names are rejected
   rather than resolved by precedence.
8. A `$call` with only constant arguments is constant-phase (section 12).
9. Scene camera settings accept observed values (section 8.1).
10. Operators are C-style, with `if()` as an alternative to `? :`; `^` is
    left undefined; `sign(0)` is `1`.
11. The language is implemented as a standalone package that other engines
    can reuse (appendix C).

Not decided, and not needed for this work: nodes are reached from the string
form only through `extents`. Other metadata an adaptor reports about a node
(point and cell counts, field names and ranges) is read through an `$observe`
entry, selection and a cast. Appendix B plans direct forms.

## 15. Amendments

Approved on 12 November 2026 during the Studio integration review.

1. **Section 11.2, `upstream`.** `spatial.inputs.upstream` carries nothing.
   A value read from a verified producer is a literal of the effective
   document by the time the operation runs, the plan digest covers that
   document, and the transfer is recorded and verified as a handoff, so
   replay already has it. The key remains, as an empty list.
2. **Section 11.2, a missing record.** A receipt with neither `spatial` nor
   `spatialVersion` verifies only when the document has no scalar, vector or
   box entry. A receipt written before spatial records existed, for a
   document that has such entries, no longer verifies; the run is repeated.
3. **Section 11.2, `updated`.** `spatial.inputs.updated` is added, so that
   "not updated at this visit" and "not spatial" replay differently.
4. **Section 11.2, tolerance.** Recorded and recomputed numbers are compared
   to 1e-12 rather than for exact equality.
5. **Section 7.2, VTK bounds.** A note records that VTK and ParaView mark
   invalid bounds the same way (`min > max`) and that the ParaView provider
   reports them as empty. No behaviour changes.
6. **Sweeps, not axes.** The document key `axes` is `sweeps`, the marker
   `$axis` is `$sweep`, the reserved root `axes` is `sweeps`, the report
   fields `axes` and `axesFastestFirst` are `sweeps` and
   `sweepsFastestFirst`, the output name token `{axis:NAME}` is
   `{sweep:NAME}`, and the fault codes `INVALID_AXIS`, `UNKNOWN_AXIS`,
   `EMPTY_AXIS`, `DUPLICATE_AXIS` and `PRESENTATION_AXIS_UNAVAILABLE` end in
   `SWEEP`. The old names are not accepted. In this specification "axis"
   now means only a direction in space; a named list of values that a run
   steps through is a sweep, whether it is declared under `sweeps`, written
   as `sweep(…)` or generated by an `$analytic`.
7. **Section 6.9, one schedule for the whole run.** Approved in principle by
   David on 12 November 2026 (a `sync` string reaches across the operations
   of a workflow, also where a member waits for loaded data) and written into
   section 6.9 on 13 November 2026. Every sweep is stepped by one schedule;
   a pipeline in a study is given its position on each sweep and steps only
   its times; a `sync` string shared by two operations makes the workflow one
   schedule; a declared sweep steps faster than a `sync` group in every case.
   This replaces the earlier behaviour in which a pipeline stepped a sweep
   with late ends inside each visit of a study.

## Appendix A. Host actions

These four actions are the whole interface for Studio, the CLI and the
agent/MCP service. `schemaxis spatial list|eval|explain <input>` are the CLI
forms of `spatial_list` and `spatial_eval` (`explain` prints the transitive
`dependsOn` chain of each record). The actions are stateless: everything they
need is in the request.

Common request fields:

| Field | Meaning |
| --- | --- |
| `input` | The whole authored document or workflow, as it stands. It may be an incomplete draft: unfilled values and invalid parts outside what the action needs do not fail it. |
| `operation` | For a workflow: the operation ID whose document is the namespace. Omit for the envelope or a plain document. |
| `draft` | Optional opaque client value (Studio sends its document identity and revision). Returned unchanged. |

Common response fields: `inputDigest` (digest of `input`), `draft` (echoed),
`capabilities` (`{"extents": true|false}` for the adaptor of the selected
document).

**Stale results.** The host does not track drafts. Every response and every
resolved record carries the `inputDigest` it was computed from. A client that
receives a response for an input it has since edited shows the values as
belonging to that earlier revision, or discards them; it never presents them
as current.

### A.1 `spatial_check`

Checks one string without evaluating it.

Request adds `expression` (the text) and optional `destination`: the JSON
pointer, within the selected document, of the value the expression is for
(for example `/nodes/3/options/resolution`). The destination supplies the
expected type and the accepted dependencies from the adaptor's declarations;
without it only the expression itself is checked.

Response:

```json
{"ok": false, "type": "scalar", "phase": "observed",
 "dependsOn": {"entries": [{"scope": "document", "section": "definitions", "key": "car"}],
               "nodes": [{"node": "bodySurface", "port": 0}, {"node": "wheelSurface", "port": 0}],
               "sweeps": [], "awaits": []},
 "fault": {"code": "DYNAMIC_CONSTRUCTOR", "…": "…"}}
```

`car.span` therefore checks `ok: true` against an ordinary scalar option and
`ok: false` against a constructor option of the same operation. `type`,
`phase` and `dependsOn` are present whenever the text parses and its names
resolve.

### A.2 `spatial_list`

Lists the spatial entries of the selected document, or of every operation and
the envelope when `operation` is omitted for a workflow.

Response adds:

- `entries`: records (section 11.1), unevaluated except constants;
- `sweeps`: `[{"id", "kind": "declared"|"sweep"|"analytic", "count", "sync"?}]`,
  fastest first, and `states`, the number of visits;
- `functions`: `[{"name", "kind": "builtin"|"catalogue", "parameters",
  "result"}]`, for completion in the shared input.

### A.3 `spatial_eval`

Evaluates entries or one ad-hoc expression.

Request adds:

- `entries` (identities; default all) or `expression`, with optional
  `destination` as in A.1;
- `state`: `{"timeIndex": n, "indices": {"<sweep id>": i}}`; omitted
  coordinates are 0;
- `observations`: optional, the `observations` object returned by an earlier
  `spatial_load`, passed back unchanged.

Response adds `records`.

- Constant entries resolve, except those awaiting a verified upstream
  operation, which are `unresolved` with `awaits-producer`.
- Visit-phase entries resolve for the given `state`.
- Observed entries resolve only from `observations` whose `inputDigest`,
  `operation` and `state` all equal this request's (the digest being that of
  this request's `input`). Without observations they are `unresolved` with
  `needs-data`; with observations that do not match they are `unresolved`
  with `stale-data`. Observations are never applied to a different input,
  operation or state.
- A client that wants to keep showing values from before an edit keeps the
  earlier records itself and shows them as stale; the host does not produce
  them.

### A.4 `spatial_load`

Loads extents for an incomplete draft without running anything downstream.

Request adds `entries` (identities; default all spatial entries) and `state`
as in A.3. Alternatively, `expression` and optional `destination` request one
ad-hoc expression, with the same checking and record shape as `spatial_eval`.
When `expression` is supplied, it selects the dependencies instead of `entries`.
For example, `expression: "dataExtents"` loads reader bounds even when the draft
has no named spatial entries. It does not insert a definition into the draft.

Behaviour:

- The host takes the nodes those entries (or the ad-hoc expression) depend on and their upstream closure.
  Only those nodes and their options are validated and executed. Other nodes,
  scenes and publications are neither validated nor run, and nothing is
  published.
- It is a native operation and runs under the caller's existing job mechanism
  (in Studio, the same job, busy and cancellation rules as input inspection).
- Without the extents capability it fails with `EXTENTS_UNSUPPORTED` before
  starting anything; `capabilities.extents` lets a client hide the action.

Result:

```json
{
  "inputDigest": "…",
  "draft": {"…": "…"},
  "observations": {
    "inputDigest": "…",
    "operation": "render",
    "state": {"timeIndex": 0, "indices": {}},
    "extents": [
      {"node": "bodySurface", "port": 0, "status": "ok", "bounds": [0, 4.5, -0.9, 0.9, 0.2, 1.4]},
      {"node": "wheelSurface", "port": 0, "status": "fault", "fault": {"code": "…"}}
    ]
  },
  "records": []
}
```

- `observations.operation` is the request's `operation` (absent for a plain
  document). `status` is `ok`, `empty`, `notSpatial` or `fault`. `bounds` is
  present only for `ok`.
- A node that fails does not fail the action. Nodes that do not depend on it
  are still loaded; records depending on it have `state: "fault"` with that
  node's fault.
- `records` is what `spatial_eval` would return for the same entries, state
  and observations.

## Appendix B. Roadmap: the reach of swak4Foam

The aim is that this language can, over time, do what swak4Foam's expressions
do, and carry control logic of the programmable-controller kind, without being
source-compatible with either. This appendix is not part of the frozen grammar
except for section B.3. Each planned item arrives by amendment.

Two boundaries shape the plan:

- **Where it runs.** This specification covers expressions in Schemaxis
  documents, evaluated by the host between native operations. swak4Foam
  evaluates inside a running solver, on every cell, every time step. That
  needs a second evaluator embedded in the solver. It belongs in a separately
  maintained integration, not in the public core, and it must implement this
  same grammar. Sections 13.1 and 13.2 are the conformance cases for any
  second implementation. Inside an OpenFOAM-style dictionary an expression
  is written as a quoted string, because that stream format has no tokens
  for `^ < > ? ! % & |`.
- **What a value is.** swak4Foam's values are fields. Here a value is a single
  scalar, vector or box. Fields arrive as a new type whose data stays in the
  application that owns it; the language describes the calculation and a
  provider carries it out.

### B.1 Capability map

| swak4Foam capability | Form here | Status |
| --- | --- | --- |
| Arithmetic, `%`, comparisons, `&&` `\|\|` `!`, `? :` | Same operators (section 6.2, 6.2a) | In this specification |
| Scalar functions (`pow exp log sqrt sqr sin … tanh erf lgamma sign pos neg mag`) | Section 6.3; trigonometry in degrees, `deg`/`rad` to convert | In this specification |
| `pi`, `vector(…)`, `.x .y .z` | Same | In this specification |
| Inner and cross product (`&`, `^`) | `dot`, `cross` | In this specification |
| `variables` lists | Named entries in `definitions`; evaluated once per visit; cycle-checked | In this specification |
| Variables evaluated elsewhere (`name{patch'inlet}`) | `extents(node)` today; `field(node, 'p')` and reductions on another node later | Partly; rest planned |
| Bessel functions | `besselJ0 besselJ1 besselY0 besselY1` | Planned (the host runtime has no dependency that provides them) |
| Lookup tables (1D, 2D) | `lookup(table, x)` over a named table entry, with a stated out-of-range rule | Planned, next |
| Tensors (`tensor`, `symmTensor`, `.xx`, `tr dev symm skew det inv eigenValues`, transpose) | Types `tensor`, `symmTensor` with those functions | Planned |
| Fields and positions (`pos() vol() area() face() dist()`) | Type `field`: values over the points, cells or faces of a node's output | Planned |
| Accumulations (`min max sum average weightedAverage median quantile range integrate size`) | Reductions of a `field` to a scalar or vector; `min`/`max` gain a one-argument form | Planned |
| Sets, zones, patches, sampled surfaces and sets | Selections of part of a node's output as the domain of a field | Planned |
| `expressionField`, `manipulateField`, `funkySetFields` | An operation whose option is a field expression; evaluated by the adaptor | Planned, per adaptor |
| Differential operators (`grad div curl laplacian snGrad ddt interpolate reconstruct flux`) | Functions on fields; only meaningful where the owner has a mesh and schemes | Planned, solver integration |
| Stored and delayed variables, `oldTime` | `previous(x)`, `stored(name, initial)`, `delay(x, duration)`; need an ordered sequence of steps | Planned, with the step context |
| Global variables across function objects | Entries read across operations through verified results (section 11.2) | In this specification, between operations; in-solver planned |
| State machines (`isState changedTo timeSinceChange stepsSinceChange`) and controller logic (inputs, outputs, timers, algorithm switching) | A declared state block beside `definitions`, with transitions written as boolean expressions | Planned, with the step context |
| `executeIf…`, `writeAndEnd…` conditional function objects | A boolean expression enabling a node, publication or operation | Planned |
| Boundary conditions and sources (`groovyBC`, `swakExplicitSource`, fvOptions) | Field expressions consumed by the solver | Planned, solver integration |
| Lagrangian cloud and finite-area parsers | Fields over other entity kinds | Planned, solver integration |
| Random numbers (`rand randNormal randFixed`) | Seeded, reproducible forms only | Planned |
| Function plug-ins | The registered function catalogue (section 6.8) | In this specification |
| Embedded Python | — | Not planned: authored input never runs arbitrary code |
| Dimension checking (as in equationReader) | Units on entries, checked through expressions | Planned |

### B.2 What "the step context" means

Stored values, delays, timers and state machines need a notion of "the
previous step". Visits in a Schemaxis study are a product of sweeps and are not
necessarily ordered in time. The amendment that adds state will add one more
phase, later than `observed`, for values that depend on earlier steps of an
ordered sequence (a solver's time steps, or a study declared as sequential),
with its own placement rules. Nothing in sections 1 to 13 assumes there are
only three phases.

### B.3 Reserved now

So that later amendments only add, the following are reserved by this
specification:

- the characters `^ & | ~ @ # ; { }` (section 2);
- the type names `line`, `plane`, `tensor`, `symmTensor`, `list`, `field`;
- the function names in the planned rows above and their swak4Foam
  counterparts: `lookup`, `tensor`, `symmTensor`, `tr`, `dev`, `symm`, `skew`,
  `det`, `inv`, `transpose`, `eigenValues`, `eigenVectors`, `field`, `pos`
  with no argument, `vol`, `area`, `dist`, `sum`, `average`,
  `weightedAverage`, `median`, `quantile`, `range`, `integrate`, `size`,
  `grad`, `div`, `curl`, `laplacian`, `snGrad`, `ddt`, `interpolate`,
  `reconstruct`, `flux`, `previous`, `stored`, `delay`, `isState`,
  `changedTo`, `timeSinceChange`, `stepsSinceChange`, `rand`, `randNormal`,
  `besselJ0`, `besselJ1`, `besselY0`, `besselY1`;
- for functions that exist today and gain a form later, the future
  signatures only: `min` and `max` with one argument, `pos` with none. Their
  signatures in section 6.3 stay callable and keep their meaning.

A catalogue function may not be registered under a reserved name, nor under
the name of a built-in. Calling a reserved function is
`EXPR_UNKNOWN_FUNCTION` with `reserved: true`. Calling an existing function
with a reserved signature is `EXPR_ARGUMENTS` with `reserved: true`; both say
in the message that the form is planned and not yet available. User entries
may use these names freely; names and functions never collide (section 3).

## Appendix C. Reuse outside Schemaxis

The language is implemented as one package with no imports from the rest of
Schemaxis and no dependencies beyond the Python standard library, so another
engine (for example an in-solver evaluator) can use it as it stands instead
of writing a second parser. It has four parts:

| Part | Does | Knows about Schemaxis |
| --- | --- | --- |
| Lexer and parser | Text to a syntax tree with code-point positions; `EXPR_SYNTAX`, `EXPR_LIMIT` | No |
| Checker | Names, types, argument counts, dependencies, against an environment the caller supplies | No |
| Evaluator | Tree to value, with the short-circuit and fault rules of this document | No |
| Built-ins | The functions and properties of section 6 and the box algebra of section 7 | No |

The caller supplies the environment: how a name resolves, which extra
functions exist, and which types its values have. The Schemaxis binding
(entries in `dimensions`, `settings` and `definitions`, sweeps, phases, sweeps,
`extents`, the function catalogue, records and faults as document locations)
is a separate module that uses the package through that environment.

A second engine keeps the grammar, the operators, the built-ins and the
fault codes, and supplies its own names and value types. Types added by
amendment (`field`, `tensor`) are added to the package once and are then
available to every engine.
