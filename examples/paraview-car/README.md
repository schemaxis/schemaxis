# Car: a model, a wake box and a line-source sweep from loaded extents

`input.json` is a ParaView document (`schemaxis/1`) in which no coordinate is
typed in. The size and position of the car are read from the loaded data, and
the zoom, the wake box, the cut plane, the seed line and every camera are
written as expressions over that one box. Bind another car case and the same
document frames and cuts it without edits to any number.

The [vehicle demonstration](../paraview-vehicle-demo/README.md) does comparable
work with the bounds of one particular case typed in by hand. Compare the two
to see what the expression language removes.

## What the document says

```json
"definitions": {
  "model": {"$expr": "union(extents(body), extents(wheels))"},
  "wake":  {"$expr": "model.push('x+', 2.5).pushAbs('x-', 0.25 * model.deltaX).inflateY(1).push('z+', 0.5)"},
  "seedX": {"$expr": "model.min.x - 0.1 * model.deltaX"},
  "seedY": {"$expr": "sweep(model.min.y, model.max.y, seedPositions)"}
}
```

| Entry | Meaning |
| --- | --- |
| `model` | The smallest box that holds the body and the wheels. `extents(body)` is the bounding box of the node `body` once ParaView has loaded it. |
| `wake` | `model` with its downstream face moved out by 2.5 car lengths, its upstream face moved out by a quarter of a length, its width doubled about the centre and its top raised by half the car's height. |
| `seedX` | A tenth of a car length upstream of the nose. |
| `seedY` | A sweep of `seedPositions` (5) evenly spaced positions from one side of the car to the other. |

They are used in the following places.

| Where | Expression |
| --- | --- |
| Cut plane `plane`, option `origin` | `model.mid` |
| Four `clip` nodes that crop the plane to the wake box | `wake.min`, `wake.max` |
| Seed line `seed`, options `start` and `end` | `vector(seedX, seedY, model.min.z)` and `vector(seedX, seedY, model.max.z)` |
| Streamline length | `wake.deltaX` |
| Tube radius | `0.002 * model.deltaX` |
| Camera of the image `zoom` | `fitCamera(bounds = model.inflate(zoom), direction = vector(-1, -2, 1), up = 'z+', aspect = aspect)` |
| Cameras of the images `top` and `side` | `fitCamera(bounds = wake, …)` |

`zoom`, `seedPositions` and `aspect` are plain entries of `settings`; an
expression reads them by name.

Schemaxis works out when each value can be known. `model` needs loaded data,
so everything that reads it is evaluated after `body` and `wheels` have been
updated and before the node that uses the value is configured. `seedY` is the
only sweep. The document runs in **one ParaView session**: the case is loaded
once, and the seed line is moved to each of its five positions.

## Outputs

| Scene | Output |
| --- | --- |
| `model` | One image of the body and wheels, framed by `model.inflate(zoom)`. |
| `wake` | One top view of the speed on the cut plane, cropped to and framed by `wake`. |
| `streamlines` | For each of the five seed positions, the tube geometry (`.vtp`) and one image. |

Twelve files in all, each with its metadata record.

## Check it without ParaView

These commands start no application.

```bash
PYTHONPATH=src python3 -m schemaxis spatial list examples/paraview-car/input.json
PYTHONPATH=src python3 -m schemaxis spatial explain examples/paraview-car/input.json --entry definitions.wake
```

`list` reports every entry with its type, when it becomes known and what it
depends on. `model`, `wake`, `seedX` and `seedY` are reported as `observed`
and unresolved for the reason `needs-data`, with the nodes `body` and `wheels`
as their dependencies. `explain` gives the chain that makes `wake` wait:
`wake → model → extents(body)`.

`schemaxis plan` stops with `TIME_INSPECTION_REQUIRED`: the document asks for
the latest time of the case, which only a run can read.

## Run it

The car case is not distributed with Schemaxis. The document names the
placeholder `cases/coupe/coupe_AMI.foam`, resolved from the directory where
Schemaxis is run. Put your case there or change `settings.case`. Then adapt
`settings.patches`: `body` and `tyres` list the boundary patches of your case
that make up the body and the wheels.

```bash
PYTHONPATH=src python3 -m schemaxis run examples/paraview-car/input.json \
  --output-directory /absolute/output/car \
  --paraview-root /absolute/ParaView
SCHEMAXIS_PARAVIEW_ROOTS=/absolute/ParaView \
  PYTHONPATH=src python3 -m schemaxis verify /absolute/output/car
```

`result.json` records, under `spatial`, the extents that were read from each
node and the value of every entry at every state, so the boxes that were
actually used can be read back. Verification recomputes them from the recorded
extents.

## Recorded native run

Run on 13 November 2026 with ParaView 5.13.3 (serial `pvbatch`) on a
decomposed OpenFOAM case of a coupe that is not distributed: twelve outputs,
verified. This is one run on one case and one ParaView release; it is not a
qualification of other releases, of MPI or of other cases.

| Entry | Value read back from `result.json` (rounded) |
| --- | --- |
| `extents(body)` | x −0.874 … 3.260, y −0.945 … 0.945, z −0.243 … 0.803 |
| `model` | x −0.874 … 3.260, y −0.951 … 0.947, z −0.332 … 0.803 |
| `wake` | x −1.908 … 13.598, y −1.900 … 1.896, z −0.332 … 1.371 |
| `seedX` | −1.288 |
| `seedY` | −0.951, −0.476, −0.002, 0.472, 0.947 |

The wheels reach lower and wider than the body, which is why `model` is the
union of the two and not the body alone.

## Limits

- The four `clip` nodes crop along the coordinate axes. A box-shaped crop in a
  single node is not offered by this example.
- The field range of the speed (0 to 50) and the patch names are choices for
  the recorded case. They are plain settings, not derived from data.
- The first time a new case is bound, read `result.json` to confirm that the
  patches named in `settings.patches` are the ones intended: a wrong patch
  name gives a wrong `model` without a fault, as long as the patch exists.
