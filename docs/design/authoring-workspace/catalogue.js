// Design fixture generated from the registered adaptors and the pipe example.
window.SCHEMAXIS_DESIGN = {
  "adaptors": [
    {
      "id": "aseprite",
      "version": "schemaxis.aseprite/1",
      "keywords": [
        "pixel art",
        "sprites",
        "layers",
        "animation"
      ],
      "execution": "batch sprite authoring and native reopening; editable sprites and sprite sheets",
      "live": false
    },
    {
      "id": "blender",
      "version": "schemaxis.blender/1",
      "keywords": [
        "meshes",
        "materials",
        "modifiers",
        "rendering",
        "glTF"
      ],
      "execution": "background Blender; prepare-only scenes and saved-scene render groups",
      "live": true
    },
    {
      "id": "calc",
      "version": "schemaxis.calc/1",
      "keywords": [
        "spreadsheet",
        "Excel interchange",
        "ODS",
        "XLSX",
        "statistics",
        "CSV"
      ],
      "execution": "Isolated headless Calc with recalculated ODS and XLSX round-trips and independent formula/data verification",
      "live": false
    },
    {
      "id": "ffmpeg",
      "version": "schemaxis.ffmpeg/1",
      "keywords": [
        "video",
        "animation",
        "PNG",
        "sprite sheet",
        "presentation"
      ],
      "execution": "PNG sequences and sprite sheets to H.264/FFV1 video with native decode verification",
      "live": false
    },
    {
      "id": "freecad",
      "version": "schemaxis.freecad/1",
      "keywords": [
        "CAD",
        "parametric solids",
        "STEP",
        "boolean",
        "meshes"
      ],
      "execution": "isolated CAD processes; verified FCStd, STEP and tessellated STL in mm",
      "live": true
    },
    {
      "id": "godot",
      "version": "schemaxis.godot/1",
      "keywords": [
        "interactive 3D",
        "scenes",
        "game engine",
        "glTF"
      ],
      "execution": "headless native scene construction and fresh-process reopening; editable project and scene",
      "live": false
    },
    {
      "id": "octave",
      "version": "schemaxis.octave/1",
      "keywords": [
        "data analysis",
        "statistics",
        "signals",
        "1D",
        "CSV",
        "FFT",
        "regression"
      ],
      "execution": "Bounded real-valued 1D analysis; isolated GNU Octave, numeric CSV and independent result verification",
      "live": false
    },
    {
      "id": "paraview",
      "version": "schemaxis/1",
      "keywords": [
        "OpenFOAM",
        "CFD",
        "slices",
        "contours",
        "scientific visualisation"
      ],
      "execution": "serial and MPI pvbatch; native distributed CFD outputs; decomposed-case reading",
      "live": true
    },
    {
      "id": "qgis",
      "version": "schemaxis.qgis/1",
      "keywords": [
        "GIS",
        "geospatial",
        "maps",
        "infrastructure",
        "GeoPackage",
        "GeoJSON"
      ],
      "execution": "Isolated QGIS Python: bounded 2D vector import, reprojection, metric buffering and rectangular clipping",
      "live": false
    }
  ],
  "freecad": {
    "box": {
      "native": "Part::Box",
      "kinds": [
        "solid"
      ],
      "options": {
        "length": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "width": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "height": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        }
      },
      "inputs": {}
    },
    "cylinder": {
      "native": "Part::Cylinder",
      "kinds": [
        "solid"
      ],
      "options": {
        "radius": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 5
          }
        },
        "height": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        },
        "axis": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              1
            ]
          }
        }
      },
      "inputs": {}
    },
    "cut": {
      "native": "Part::Cut",
      "kinds": [
        "solid"
      ],
      "options": {},
      "inputs": {
        "base": {
          "required": true,
          "kind": "solid"
        },
        "tool": {
          "required": true,
          "kind": "solid"
        }
      }
    },
    "fuse": {
      "native": "Part::Fuse",
      "kinds": [
        "solid"
      ],
      "options": {},
      "inputs": {
        "base": {
          "required": true,
          "kind": "solid"
        },
        "tool": {
          "required": true,
          "kind": "solid"
        }
      }
    },
    "sphere": {
      "native": "Part::Sphere",
      "kinds": [
        "solid"
      ],
      "options": {
        "radius": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        }
      },
      "inputs": {}
    },
    "cone": {
      "native": "Part::Cone",
      "kinds": [
        "solid"
      ],
      "options": {
        "radius1": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "radius2": {
          "value": {
            "type": "number",
            "minimum": 0,
            "maximum": 100000,
            "default": 5
          }
        },
        "height": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 20
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        },
        "axis": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              1
            ]
          }
        }
      },
      "inputs": {}
    },
    "torus": {
      "native": "Part::Torus",
      "kinds": [
        "solid"
      ],
      "options": {
        "majorRadius": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 20
          }
        },
        "minorRadius": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 5
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        },
        "axis": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              1
            ]
          }
        }
      },
      "inputs": {}
    },
    "common": {
      "native": "Part::Common",
      "kinds": [
        "solid"
      ],
      "options": {},
      "inputs": {
        "base": {
          "required": true,
          "kind": "solid"
        },
        "tool": {
          "required": true,
          "kind": "solid"
        }
      }
    },
    "polygon": {
      "native": "Sketcher::SketchObject",
      "kinds": [
        "profile"
      ],
      "options": {
        "points": {
          "value": {
            "type": "array",
            "items": {
              "type": "array",
              "items": {
                "type": "number"
              },
              "minItems": 2,
              "maxItems": 2
            },
            "minItems": 3,
            "maxItems": 100,
            "required": true
          }
        },
        "plane": {
          "value": {
            "type": "enum",
            "values": [
              "XY",
              "XZ",
              "YZ"
            ],
            "default": "XY"
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        }
      },
      "inputs": {}
    },
    "rectangle": {
      "native": "Sketcher::SketchObject",
      "kinds": [
        "profile"
      ],
      "options": {
        "width": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 80
          }
        },
        "height": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 50
          }
        },
        "plane": {
          "value": {
            "type": "enum",
            "values": [
              "XY",
              "XZ",
              "YZ"
            ],
            "default": "XY"
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        }
      },
      "inputs": {}
    },
    "circle": {
      "native": "Sketcher::SketchObject",
      "kinds": [
        "profile"
      ],
      "options": {
        "radius": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 5
          }
        },
        "plane": {
          "value": {
            "type": "enum",
            "values": [
              "XY",
              "XZ",
              "YZ"
            ],
            "default": "XY"
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        }
      },
      "inputs": {}
    },
    "extrude": {
      "native": "Part::Extrusion",
      "kinds": [
        "solid"
      ],
      "options": {
        "length": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 10
          }
        },
        "direction": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              1
            ]
          }
        }
      },
      "inputs": {
        "profile": {
          "required": true,
          "kind": "profile"
        }
      }
    },
    "revolve": {
      "native": "Part::Revolution",
      "kinds": [
        "solid"
      ],
      "options": {
        "angle": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 360,
            "default": 360
          }
        },
        "origin": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              0
            ]
          }
        },
        "axis": {
          "value": {
            "type": "array",
            "items": {
              "type": "number"
            },
            "minItems": 3,
            "maxItems": 3,
            "default": [
              0,
              0,
              1
            ]
          }
        }
      },
      "inputs": {
        "profile": {
          "required": true,
          "kind": "profile"
        }
      }
    },
    "fillet": {
      "native": "Part::Fillet",
      "kinds": [
        "solid"
      ],
      "options": {
        "radius": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 1
          }
        },
        "edges": {
          "value": {
            "type": "array",
            "items": {
              "type": "integer",
              "minimum": 1
            },
            "minItems": 1,
            "maxItems": 1000,
            "uniqueItems": true,
            "default": [
              1
            ]
          }
        }
      },
      "inputs": {
        "base": {
          "required": true,
          "kind": "solid"
        }
      }
    },
    "chamfer": {
      "native": "Part::Chamfer",
      "kinds": [
        "solid"
      ],
      "options": {
        "distance": {
          "value": {
            "type": "number",
            "minimum": 0,
            "exclusiveMinimum": true,
            "maximum": 100000,
            "default": 1
          }
        },
        "edges": {
          "value": {
            "type": "array",
            "items": {
              "type": "integer",
              "minimum": 1
            },
            "minItems": 1,
            "maxItems": 1000,
            "uniqueItems": true,
            "default": [
              1
            ]
          }
        }
      },
      "inputs": {
        "base": {
          "required": true,
          "kind": "solid"
        }
      }
    },
    "readSTEP": {
      "native": "Part::Feature",
      "kinds": [
        "solid"
      ],
      "options": {
        "file": {
          "value": {
            "type": "string",
            "minLength": 1,
            "required": true
          }
        }
      },
      "inputs": {}
    },
    "loft": {
      "native": "Part::Loft",
      "kinds": [
        "solid"
      ],
      "options": {
        "ruled": {
          "value": {
            "type": "boolean",
            "default": false
          }
        }
      },
      "inputs": {
        "sections": {
          "required": true,
          "kind": "profile",
          "multiple": true,
          "minItems": 2,
          "maxItems": 32
        }
      }
    },
    "multiFuse": {
      "native": "Part::MultiFuse",
      "kinds": [
        "solid"
      ],
      "options": {
        "refine": {
          "value": {
            "type": "boolean",
            "default": true
          }
        }
      },
      "inputs": {
        "shapes": {
          "required": true,
          "kind": "solid",
          "multiple": true,
          "minItems": 2,
          "maxItems": 32
        }
      }
    }
  },
  "elbow": {
    "version": "schemaxis.freecad/1",
    "units": "mm",
    "dimensions": {
      "bendRadius": 60,
      "outerRadius": 18,
      "innerRadius": 14,
      "bendAngle": 90,
      "meshDeflection": 0.05
    },
    "linearDeflection": {
      "$document": "/dimensions/meshDeflection"
    },
    "nodes": [
      {
        "id": "outerProfile",
        "filter": "circle",
        "options": {
          "radius": {
            "$document": "/dimensions/outerRadius"
          },
          "plane": "XZ",
          "origin": [
            {
              "$document": "/dimensions/bendRadius"
            },
            0,
            0
          ]
        }
      },
      {
        "id": "outerBend",
        "filter": "revolve",
        "options": {
          "angle": {
            "$document": "/dimensions/bendAngle"
          },
          "axis": [
            0,
            0,
            1
          ],
          "origin": [
            0,
            0,
            0
          ]
        },
        "inputs": {
          "profile": "outerProfile"
        }
      },
      {
        "id": "innerProfile",
        "filter": "circle",
        "options": {
          "radius": {
            "$document": "/dimensions/innerRadius"
          },
          "plane": "XZ",
          "origin": [
            {
              "$document": "/dimensions/bendRadius"
            },
            0,
            0
          ]
        }
      },
      {
        "id": "innerBend",
        "filter": "revolve",
        "options": {
          "angle": {
            "$document": "/dimensions/bendAngle"
          },
          "axis": [
            0,
            0,
            1
          ],
          "origin": [
            0,
            0,
            0
          ]
        },
        "inputs": {
          "profile": "innerProfile"
        }
      },
      {
        "id": "pipe",
        "filter": "cut",
        "options": {},
        "inputs": {
          "base": "outerBend",
          "tool": "innerBend"
        }
      }
    ],
    "output": "pipe"
  }
};
