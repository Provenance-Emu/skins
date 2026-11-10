// Vendored from SkinKit/Sources/SkinKit2Core/Resources/parts/std.json.
import type { JSONValue } from "./json.js";

export const STD_PARTS: Record<string, JSONValue> = {
  "std.faceButton": {
    "params": {
      "input": {
        "type": "string"
      },
      "label": {
        "type": "string",
        "default": ""
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "glow": {
        "type": "color",
        "default": "#9E7AF2"
      },
      "labelColor": {
        "type": "color",
        "default": "#FFFFFFE6"
      },
      "shape": {
        "type": "shape",
        "default": {
          "kind": "ellipse"
        }
      }
    },
    "node": {
      "type": "control",
      "kind": "button",
      "input": "@input",
      "states": {
        "pressed": {
          "scale": 0.92,
          "patch": [
            {
              "target": "#body",
              "fills": [
                {
                  "type": "linear",
                  "start": [
                    0.5,
                    0
                  ],
                  "end": [
                    0.5,
                    1
                  ],
                  "stops": [
                    [
                      "@bottom",
                      0
                    ],
                    [
                      "@top",
                      1
                    ]
                  ]
                },
                {
                  "type": "linear",
                  "start": [
                    0.5,
                    0
                  ],
                  "end": [
                    0.5,
                    0.5
                  ],
                  "stops": [
                    [
                      "#FFFFFF57",
                      0
                    ],
                    [
                      "#FFFFFF00",
                      1
                    ]
                  ]
                }
              ]
            }
          ]
        }
      },
      "children": [
        {
          "type": "shape",
          "id": "body",
          "shape": "@shape",
          "fills": [
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                1
              ],
              "stops": [
                [
                  "@top",
                  0
                ],
                [
                  "@bottom",
                  1
                ]
              ]
            },
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                0.5
              ],
              "stops": [
                [
                  "#FFFFFF57",
                  0
                ],
                [
                  "#FFFFFF00",
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "#FFFFFF80",
              "width": 1,
              "align": "inner"
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#00000059",
              "radius": 3,
              "offset": [
                0,
                2
              ]
            },
            {
              "type": "shadow",
              "color": "@glow",
              "opacity": 0.35,
              "radius": 4,
              "offset": [
                0,
                0
              ]
            }
          ]
        },
        {
          "type": "text",
          "text": "@label",
          "font": {
            "size": 11,
            "weight": "bold"
          },
          "color": "@labelColor",
          "align": "center"
        }
      ]
    }
  },
  "std.kidneyButton": {
    "params": {
      "input": {
        "type": "string"
      },
      "label": {
        "type": "string",
        "default": ""
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "glow": {
        "type": "color",
        "default": "#9E7AF2"
      },
      "labelColor": {
        "type": "color",
        "default": "#FFFFFFE6"
      },
      "shape": {
        "type": "shape",
        "default": {
          "kind": "kidney"
        }
      }
    },
    "node": {
      "type": "control",
      "kind": "button",
      "input": "@input",
      "states": {
        "pressed": {
          "scale": 0.92,
          "patch": [
            {
              "target": "#body",
              "fills": [
                {
                  "type": "linear",
                  "start": [
                    0.5,
                    0
                  ],
                  "end": [
                    0.5,
                    1
                  ],
                  "stops": [
                    [
                      "@bottom",
                      0
                    ],
                    [
                      "@top",
                      1
                    ]
                  ]
                },
                {
                  "type": "linear",
                  "start": [
                    0.5,
                    0
                  ],
                  "end": [
                    0.5,
                    0.5
                  ],
                  "stops": [
                    [
                      "#FFFFFF57",
                      0
                    ],
                    [
                      "#FFFFFF00",
                      1
                    ]
                  ]
                }
              ]
            }
          ]
        }
      },
      "children": [
        {
          "type": "shape",
          "id": "body",
          "shape": "@shape",
          "fills": [
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                1
              ],
              "stops": [
                [
                  "@top",
                  0
                ],
                [
                  "@bottom",
                  1
                ]
              ]
            },
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                0.5
              ],
              "stops": [
                [
                  "#FFFFFF57",
                  0
                ],
                [
                  "#FFFFFF00",
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "#FFFFFF80",
              "width": 1,
              "align": "inner"
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#00000059",
              "radius": 3,
              "offset": [
                0,
                2
              ]
            },
            {
              "type": "shadow",
              "color": "@glow",
              "opacity": 0.35,
              "radius": 4,
              "offset": [
                0,
                0
              ]
            }
          ]
        },
        {
          "type": "text",
          "text": "@label",
          "font": {
            "size": 11,
            "weight": "bold"
          },
          "color": "@labelColor",
          "align": "center"
        }
      ]
    }
  },
  "std.pill": {
    "params": {
      "input": {
        "type": "string"
      },
      "label": {
        "type": "string",
        "default": ""
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "glow": {
        "type": "color",
        "default": "#9E7AF2"
      },
      "labelColor": {
        "type": "color",
        "default": "#FFFFFFE6"
      },
      "shape": {
        "type": "shape",
        "default": {
          "kind": "capsule"
        }
      }
    },
    "node": {
      "type": "control",
      "kind": "button",
      "input": "@input",
      "states": {
        "pressed": {
          "scale": 0.92,
          "patch": [
            {
              "target": "#body",
              "fills": [
                {
                  "type": "linear",
                  "start": [
                    0.5,
                    0
                  ],
                  "end": [
                    0.5,
                    1
                  ],
                  "stops": [
                    [
                      "@bottom",
                      0
                    ],
                    [
                      "@top",
                      1
                    ]
                  ]
                },
                {
                  "type": "linear",
                  "start": [
                    0.5,
                    0
                  ],
                  "end": [
                    0.5,
                    0.5
                  ],
                  "stops": [
                    [
                      "#FFFFFF57",
                      0
                    ],
                    [
                      "#FFFFFF00",
                      1
                    ]
                  ]
                }
              ]
            }
          ]
        }
      },
      "children": [
        {
          "type": "shape",
          "id": "body",
          "shape": "@shape",
          "fills": [
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                1
              ],
              "stops": [
                [
                  "@top",
                  0
                ],
                [
                  "@bottom",
                  1
                ]
              ]
            },
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                0.5
              ],
              "stops": [
                [
                  "#FFFFFF57",
                  0
                ],
                [
                  "#FFFFFF00",
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "#FFFFFF80",
              "width": 1,
              "align": "inner"
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#00000059",
              "radius": 3,
              "offset": [
                0,
                2
              ]
            },
            {
              "type": "shadow",
              "color": "@glow",
              "opacity": 0.35,
              "radius": 4,
              "offset": [
                0,
                0
              ]
            }
          ]
        },
        {
          "type": "text",
          "text": "@label",
          "font": {
            "size": 11,
            "weight": "bold"
          },
          "color": "@labelColor",
          "align": "center"
        }
      ]
    }
  },
  "std.triggerBar": {
    "params": {
      "input": {
        "type": "string"
      },
      "label": {
        "type": "string",
        "default": ""
      },
      "kind": {
        "type": "string",
        "default": "trigger"
      },
      "taper": {
        "type": "number",
        "default": 0.14
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "labelColor": {
        "type": "color",
        "default": "#FFFFFFE6"
      }
    },
    "node": {
      "type": "control",
      "kind": "@kind",
      "input": "@input",
      "states": {
        "pressed": {
          "scale": 0.92
        }
      },
      "children": [
        {
          "type": "shape",
          "shape": {
            "kind": "trapezoid",
            "taper": "@taper"
          },
          "fills": [
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                1
              ],
              "stops": [
                [
                  "@top",
                  0
                ],
                [
                  "@bottom",
                  1
                ]
              ]
            },
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                0.5
              ],
              "stops": [
                [
                  "#FFFFFF57",
                  0
                ],
                [
                  "#FFFFFF00",
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "#FFFFFF80",
              "width": 1,
              "align": "inner"
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#00000059",
              "radius": 3,
              "offset": [
                0,
                2
              ]
            }
          ]
        },
        {
          "type": "text",
          "text": "@label",
          "font": {
            "size": 11,
            "weight": "bold"
          },
          "color": "@labelColor",
          "align": "center"
        }
      ]
    }
  },
  "std.dpad": {
    "params": {
      "up": {
        "type": "string",
        "default": "up"
      },
      "down": {
        "type": "string",
        "default": "down"
      },
      "left": {
        "type": "string",
        "default": "left"
      },
      "right": {
        "type": "string",
        "default": "right"
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "glow": {
        "type": "color",
        "default": "#9E7AF2"
      },
      "arrowColor": {
        "type": "color",
        "default": "#FFFFFFD9"
      }
    },
    "node": {
      "type": "control",
      "kind": "dpad",
      "input": {
        "up": "@up",
        "down": "@down",
        "left": "@left",
        "right": "@right"
      },
      "effects": [
        {
          "type": "shadow",
          "color": "#00000066",
          "radius": 3,
          "offset": [
            0,
            2
          ]
        }
      ],
      "states": {
        "pressed.up": {
          "patch": [
            {
              "target": "#arrow[0]",
              "fills": [
                {
                  "type": "solid",
                  "color": "@glow"
                }
              ]
            }
          ]
        },
        "pressed.right": {
          "patch": [
            {
              "target": "#arrow[1]",
              "fills": [
                {
                  "type": "solid",
                  "color": "@glow"
                }
              ]
            }
          ]
        },
        "pressed.down": {
          "patch": [
            {
              "target": "#arrow[2]",
              "fills": [
                {
                  "type": "solid",
                  "color": "@glow"
                }
              ]
            }
          ]
        },
        "pressed.left": {
          "patch": [
            {
              "target": "#arrow[3]",
              "fills": [
                {
                  "type": "solid",
                  "color": "@glow"
                }
              ]
            }
          ]
        }
      },
      "children": [
        {
          "type": "shape",
          "shape": {
            "kind": "ellipse"
          },
          "fills": [
            {
              "type": "radial",
              "center": [
                0.4,
                0.34
              ],
              "radius": 0.7,
              "stops": [
                [
                  "@top",
                  0.9,
                  0
                ],
                [
                  "@bottom",
                  0.95,
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "@glow",
              "opacity": 0.55,
              "width": 2,
              "align": "inner"
            }
          ]
        },
        {
          "type": "shape",
          "id": "cross",
          "layout": {
            "inset": "14%"
          },
          "shape": {
            "kind": "cross",
            "armRatio": 0.34,
            "cornerRadius": 4
          },
          "fills": [
            {
              "type": "linear",
              "start": [
                0.5,
                0
              ],
              "end": [
                0.5,
                1
              ],
              "stops": [
                [
                  "@bottom",
                  0
                ],
                [
                  "@top",
                  1
                ]
              ]
            }
          ]
        },
        {
          "type": "shape",
          "id": "arrow",
          "shape": {
            "kind": "polygon",
            "sides": 3,
            "rotation": -90
          },
          "layout": {
            "size": {
              "width": "15.6%",
              "height": "15.6%"
            },
            "anchor": {
              "x": "center",
              "y": "center"
            },
            "offset": {
              "y": "-26.5%"
            }
          },
          "repeat": {
            "count": 4,
            "rotate": 90,
            "pivot": "parent"
          },
          "fills": [
            {
              "type": "solid",
              "color": "@arrowColor"
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#0000004D",
              "radius": 1,
              "offset": [
                0,
                1
              ]
            }
          ]
        }
      ]
    }
  },
  "std.stick": {
    "params": {
      "input": {
        "type": "string"
      },
      "knob": {
        "type": "length",
        "default": {
          "frac": 0.5
        }
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "glow": {
        "type": "color",
        "default": "#9E7AF2"
      }
    },
    "node": {
      "type": "control",
      "kind": "thumbstick",
      "input": "@input",
      "children": [
        {
          "type": "shape",
          "role": "base",
          "shape": {
            "kind": "ellipse"
          },
          "fills": [
            {
              "type": "radial",
              "center": [
                0.5,
                0.5
              ],
              "radius": 0.53,
              "stops": [
                [
                  "#00000059",
                  0
                ],
                [
                  "@glow",
                  0.28,
                  1
                ]
              ]
            }
          ]
        },
        {
          "type": "shape",
          "role": "base",
          "shape": {
            "kind": "polygon",
            "sides": 8,
            "rotation": -22.5
          },
          "layout": {
            "inset": 6
          },
          "strokes": [
            {
              "color": "@glow",
              "opacity": 0.6,
              "width": 2
            }
          ]
        },
        {
          "type": "shape",
          "role": "knob",
          "shape": {
            "kind": "ellipse"
          },
          "layout": {
            "size": {
              "width": "@knob",
              "height": "@knob"
            },
            "anchor": {
              "x": "center",
              "y": "center"
            }
          },
          "fills": [
            {
              "type": "radial",
              "center": [
                0.38,
                0.3
              ],
              "radius": 0.6,
              "stops": [
                [
                  "@top",
                  0
                ],
                [
                  "@bottom",
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "#00000040",
              "width": 1.5
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#00000080",
              "radius": 4,
              "offset": [
                0,
                2
              ]
            }
          ]
        }
      ]
    }
  },
  "std.stickWithClick": {
    "params": {
      "input": {
        "type": "string"
      },
      "click": {
        "type": "string"
      },
      "knob": {
        "type": "length",
        "default": {
          "frac": 0.5
        }
      },
      "top": {
        "type": "color",
        "default": "#755CA8"
      },
      "bottom": {
        "type": "color",
        "default": "#3D2B66"
      },
      "glow": {
        "type": "color",
        "default": "#9E7AF2"
      }
    },
    "node": {
      "type": "control",
      "kind": "thumbstick",
      "input": "@input",
      "click": "@click",
      "children": [
        {
          "type": "shape",
          "role": "base",
          "shape": {
            "kind": "ellipse"
          },
          "fills": [
            {
              "type": "radial",
              "center": [
                0.5,
                0.5
              ],
              "radius": 0.53,
              "stops": [
                [
                  "#00000059",
                  0
                ],
                [
                  "@glow",
                  0.28,
                  1
                ]
              ]
            }
          ]
        },
        {
          "type": "shape",
          "role": "base",
          "shape": {
            "kind": "polygon",
            "sides": 8,
            "rotation": -22.5
          },
          "layout": {
            "inset": 6
          },
          "strokes": [
            {
              "color": "@glow",
              "opacity": 0.6,
              "width": 2
            }
          ]
        },
        {
          "type": "shape",
          "role": "knob",
          "shape": {
            "kind": "ellipse"
          },
          "layout": {
            "size": {
              "width": "@knob",
              "height": "@knob"
            },
            "anchor": {
              "x": "center",
              "y": "center"
            }
          },
          "fills": [
            {
              "type": "radial",
              "center": [
                0.38,
                0.3
              ],
              "radius": 0.6,
              "stops": [
                [
                  "@top",
                  0
                ],
                [
                  "@bottom",
                  1
                ]
              ]
            }
          ],
          "strokes": [
            {
              "color": "#00000040",
              "width": 1.5
            }
          ],
          "effects": [
            {
              "type": "shadow",
              "color": "#00000080",
              "radius": 4,
              "offset": [
                0,
                2
              ]
            }
          ]
        }
      ]
    }
  },
  "std.keypadKey": {
    "params": {
      "input": {
        "type": "string"
      },
      "label": {
        "type": "string",
        "default": ""
      },
      "color": {
        "type": "color",
        "default": "#3D2B66"
      },
      "labelColor": {
        "type": "color",
        "default": "#FFFFFFE6"
      },
      "cornerRadius": {
        "type": "length",
        "default": {
          "pt": 6
        }
      }
    },
    "node": {
      "type": "control",
      "kind": "button",
      "input": "@input",
      "states": {
        "pressed": {
          "scale": 0.94,
          "patch": [
            {
              "target": "#body",
              "fills": [
                {
                  "type": "solid",
                  "color": "@color",
                  "opacity": 0.7
                }
              ]
            }
          ]
        }
      },
      "children": [
        {
          "type": "shape",
          "id": "body",
          "shape": {
            "kind": "rect",
            "cornerRadius": "@cornerRadius"
          },
          "fills": [
            {
              "type": "solid",
              "color": "@color"
            }
          ],
          "strokes": [
            {
              "color": "#FFFFFF80",
              "width": 1,
              "align": "inner"
            }
          ]
        },
        {
          "type": "text",
          "text": "@label",
          "font": {
            "size": 14,
            "weight": "semibold"
          },
          "color": "@labelColor",
          "align": "center"
        }
      ]
    }
  }
};
