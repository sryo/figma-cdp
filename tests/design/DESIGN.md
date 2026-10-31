---
version: alpha
name: Lede
# The first theme is the base; a token key ending in -<theme> overrides it there.
themes: [light, dark]
colors:
  primary: "#2F5BEA"
  canvas: "#FAF9F6"
  ink: "#1A1D2E"
  on-primary: "{colors.canvas}"
  canvas-dark: "#0E0F13"
  ink-dark: "#EDEEF3"
typography:
  fs-s:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 500
rounded:
  r-tile: 20px
spacing:
  gap: 1rem
components:
  button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
---

## Overview

A fixture for figma_source.py's DESIGN.md reader.

## Colors

- **Primary (#2F5BEA):** links and the one button.
