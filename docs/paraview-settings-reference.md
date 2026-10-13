# Shared function and ParaView settings signatures

[Guide](paraview-guide.md) · [Dollar syntax](dollar-reference.md)

All type constraints below are taken directly from declarations. `required`, defaults, enum values and array lengths are authoritative; cross-field rules still require the planner. Examples are type templates, requiring semantically suitable values.

## Appearance

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `colour` | `{"type":"union","options":[{"type":"string"},{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":4}]}` | `[0.7,0.7,0.7]` |
| `field` | `{"type":"array","items":{"type":"string"},"minItems":2,"maxItems":2}` | omitted |
| `component` | `{"type":"integer","minimum":-1}` | `-1` |
| `opacity` | `{"type":"number","minimum":0,"maximum":1}` | `1` |
| `representation` | `{"type":"enum","values":["Surface","Surface With Edges","Wireframe","Points","Outline"]}` | `"Surface"` |
| `range` | `{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}` | omitted |
| `legend` | `{"type":"boolean"}` | `false` |
| `legendTitle` | `{"type":"string"}` | omitted |
| `preset` | `{"type":"string"}` | omitted |
| `logScale` | `{"type":"boolean"}` | `false` |

## Camera

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `direction` | `{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `[1,0,0]` |
| `up` | `{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `[0,0,1]` |
| `focalPoint` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | omitted |
| `parallel` | `{"type":"boolean"}` | `true` |
| `scale` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | omitted |
| `distance` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | omitted |
| `bounds` | `{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6}` | omitted |
| `padding` | `{"type":"number","minimum":0}` | `0.1` |

## Registered value functions

## boundsCentre

Centre of six-component VTK bounds.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6}` | required |

Result contract: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

```json
{
  "$value": "boundsCentre",
  "args": {
    "bounds": [
      1,
      1,
      1,
      1,
      1,
      1
    ]
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## boundsCentre3D

Centre of min/max bounds.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |

Result contract: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

```json
{
  "$value": "boundsCentre3D",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    }
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## boundsExtend

Extend min/max bounds by before/after vectors.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |
| `before` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |
| `after` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |

Result contract: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

```json
{
  "$value": "boundsExtend",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    }
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## boundsFrame

Frame bounds with margins, a floor and an aspect ratio.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |
| `before` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |
| `after` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |
| `floor` | `{"type":"number"}` | required |
| `aspect` | `{"type":"array","items":{"type":"number","minimum":0,"exclusiveMinimum":true},"minItems":2,"maxItems":2}` | `[16,9]` |

Result contract: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

```json
{
  "$value": "boundsFrame",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    },
    "floor": 1
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## boundsSize

Axis extents of min/max bounds.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |

Result contract: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

```json
{
  "$value": "boundsSize",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    }
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## boundsUnion

Union of a nonempty list of min/max bounds.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"array","items":{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}},"minItems":1}` | required |

Result contract: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

```json
{
  "$value": "boundsUnion",
  "args": {
    "bounds": [
      {
        "min": [
          1,
          1,
          1
        ],
        "max": [
          1,
          1,
          1
        ]
      }
    ]
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## directionVector

Resolve a direction declaration to an XYZ vector.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `direction` | `{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | required |
| `length` | `{"type":"number","minimum":0}` | `1` |

Result contract: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

```json
{
  "$value": "directionVector",
  "args": {
    "direction": "REPLACE_WITH_VALUE"
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## fitCamera

Fit a camera to bounds.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |
| `aspect` | `{"type":"array","items":{"type":"number","minimum":0,"exclusiveMinimum":true},"minItems":2,"maxItems":2}` | `[16,9]` |
| `padding` | `{"type":"number","minimum":0}` | `0.15` |
| `parallel` | `{"type":"boolean"}` | `true` |
| `distanceScale` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | `2` |
| `direction` | `{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `"x+"` |
| `up` | `{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `"z+"` |

Result contract: `{"type":"object","properties":{"direction":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[1,0,0]},"up":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[0,0,1]},"focalPoint":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3},"parallel":{"type":"boolean","default":true},"scale":{"type":"number","minimum":0,"exclusiveMinimum":true},"distance":{"type":"number","minimum":0,"exclusiveMinimum":true},"bounds":{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6},"padding":{"type":"number","minimum":0,"default":0.1}}}`.

```json
{
  "$value": "fitCamera",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    }
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## foamRegions

Convert tyres/body //patch selectors to internalMesh and patch/name reader regions.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `groups` | `{"type":"object","properties":{"tyres":{"type":"array","items":{"type":"string","minLength":3},"minItems":1,"required":true},"body":{"type":"array","items":{"type":"string","minLength":3},"minItems":1,"required":true}}}` | required |

Result contract: `{"type":"array","items":{"type":"string"}}`.

```json
{
  "$value": "foamRegions",
  "args": {
    "groups": {
      "tyres": [
        "REPLACE_WITH_VALUE"
      ],
      "body": [
        "REPLACE_WITH_VALUE"
      ]
    }
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## orbitCameras

Produce camera declarations around bounds.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |
| `aspect` | `{"type":"array","items":{"type":"number","minimum":0,"exclusiveMinimum":true},"minItems":2,"maxItems":2}` | `[16,9]` |
| `padding` | `{"type":"number","minimum":0}` | `0.15` |
| `parallel` | `{"type":"boolean"}` | `true` |
| `distanceScale` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | `2` |
| `count` | `{"type":"integer","minimum":1,"maximum":10000}` | `12` |
| `elevation` | `{"type":"number","minimum":-89,"maximum":89}` | `25` |

Result contract: `{"type":"array","items":{"type":"object","properties":{"direction":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[1,0,0]},"up":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[0,0,1]},"focalPoint":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3},"parallel":{"type":"boolean","default":true},"scale":{"type":"number","minimum":0,"exclusiveMinimum":true},"distance":{"type":"number","minimum":0,"exclusiveMinimum":true},"bounds":{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6},"padding":{"type":"number","minimum":0,"default":0.1}}}}`.

```json
{
  "$value": "orbitCameras",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    }
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## rangeCentre

Midpoint of a two-number range.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `range` | `{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}` | required |

Result contract: `{"type":"number"}`.

```json
{
  "$value": "rangeCentre",
  "args": {
    "range": [
      1,
      1
    ]
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## sinDegrees

Sine of an angle in degrees.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `angle` | `{"type":"number"}` | required |

Result contract: `{"type":"number"}`.

```json
{
  "$value": "sinDegrees",
  "args": {
    "angle": 1
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## slicePositions

Produce scalar slice positions along one bounds axis.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | required |
| `axis` | `{"type":"enum","values":["x","y","z"]}` | required |
| `count` | `{"type":"integer","minimum":1,"maximum":10000}` | `9` |

Result contract: `{"type":"array","items":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}}`.

```json
{
  "$value": "slicePositions",
  "args": {
    "bounds": {
      "min": [
        1,
        1,
        1
      ],
      "max": [
        1,
        1,
        1
      ]
    },
    "axis": "x"
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.

## vectorLength

Euclidean length of an XYZ vector.

| Key | Syntax / constraints | Default / requirement |
| --- | --- | --- |
| `vector` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | required |

Result contract: `{"type":"number"}`.

```json
{
  "$value": "vectorLength",
  "args": {
    "vector": [
      1,
      1,
      1
    ]
  }
}
```
Use `$call` instead of `$value` when arguments contain graph runtime expressions.
