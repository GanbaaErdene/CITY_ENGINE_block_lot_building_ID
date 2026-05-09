"""
CityEngine 2025 Python script
----------------------------
From the current selection:
  - Assign sequential IDs to Blocks and Lots (block_01, lot_01, ...)
  - Compute Building GFA from footprint area * floors
  - Aggregate GFA to Lots and Blocks and compute FAR = GFA / SiteArea

Usage (CityEngine):
  - Open the script in the CityEngine Python console/editor and run it
  - Select at least one Block, or select Lots/Buildings directly

Notes:
  - Area is computed from shape vertices (projected to XZ plane).
  - If your buildings store floors/area in custom attributes, configure the
    attribute name candidates below.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import scripting

ce = scripting.getCityEngine()


# -----------------------------
# Configuration
# -----------------------------

# ID attribute names to write onto objects
BLOCK_ID_ATTR = "block_id"
LOT_ID_ATTR = "lot_id"

# Optional: also rename objects in the scene (setName) to match IDs
RENAME_OBJECTS = False

# Prefix/format for IDs
BLOCK_PREFIX = "block_"
LOT_PREFIX = "lot_"
ID_PAD = 2  # block_01, lot_01

# Building inputs (the script tries these in order)
FLOOR_ATTR_CANDIDATES = [
    "floors",
    "numFloors",
    "floorCount",
    "FloorCount",
    "stories",
    "Stories",
]

# If you already have footprint area as an attribute on buildings, add it here.
# Otherwise the script will compute from shape vertices when possible.
FOOTPRINT_AREA_ATTR_CANDIDATES = [
    "footprint_area",
    "FootprintArea",
    "footprintArea",
    "base_area",
    "BaseArea",
]

# Output attribute names
BUILDING_FOOTPRINT_AREA_ATTR = "footprint_area_m2"
BUILDING_GFA_ATTR = "gfa_m2"

LOT_SITE_AREA_ATTR = "site_area_m2"
LOT_GFA_ATTR = "gfa_total_m2"
LOT_FAR_ATTR = "far"

BLOCK_SITE_AREA_ATTR = "site_area_m2"
BLOCK_GFA_ATTR = "gfa_total_m2"
BLOCK_FAR_ATTR = "far"


# -----------------------------
# Helpers
# -----------------------------

def _get_selection() -> List[Any]:
    """
    CityEngine API has historically exposed selection as ce.selection().
    Some docs show ce.selection (property). Support both.
    """
    sel = None
    try:
        sel = ce.selection()
    except Exception:
        pass
    if sel is None:
        try:
            sel = ce.selection
        except Exception:
            sel = []
    if sel is None:
        sel = []
    return list(sel)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def _first_attr(obj: Any, names: Sequence[str]) -> Tuple[Optional[str], Any]:
    for n in names:
        try:
            v = ce.getAttribute(obj, n)
        except Exception:
            v = None
        if v is not None:
            return n, v
    return None, None


def _format_id(prefix: str, i: int) -> str:
    return f"{prefix}{i:0{ID_PAD}d}"


def _vertices_to_xz(vertices: Sequence[float]) -> List[Tuple[float, float]]:
    # vertices may be [x,y,z,x,y,z,...] or [x,z,x,z,...]
    if len(vertices) >= 6 and len(vertices) % 3 == 0:
        pts = []
        for i in range(0, len(vertices), 3):
            pts.append((float(vertices[i]), float(vertices[i + 2])))
        return pts
    if len(vertices) >= 4 and len(vertices) % 2 == 0:
        pts = []
        for i in range(0, len(vertices), 2):
            pts.append((float(vertices[i]), float(vertices[i + 1])))
        return pts
    return []


def _polygon_area_xz(points: Sequence[Tuple[float, float]]) -> float:
    # Shoelace formula; assumes simple polygon, returns absolute area.
    if len(points) < 3:
        return 0.0
    area2 = 0.0
    for i in range(len(points)):
        x1, z1 = points[i]
        x2, z2 = points[(i + 1) % len(points)]
        area2 += x1 * z2 - x2 * z1
    return abs(area2) * 0.5


def _shape_area_m2(shape: Any) -> Optional[float]:
    # Prefer explicit attrs if present (common in workflows)
    for n in ("area_m2", "area", "Area", LOT_SITE_AREA_ATTR, BLOCK_SITE_AREA_ATTR):
        try:
            v = ce.getAttribute(shape, n)
        except Exception:
            v = None
        fv = _safe_float(v)
        if fv is not None and fv > 0:
            return fv

    # Compute from vertices
    try:
        verts = ce.getVertices(shape)
    except Exception:
        verts = None
    if not verts:
        return None
    pts = _vertices_to_xz(verts)
    if not pts:
        return None
    a = _polygon_area_xz(pts)
    return a if a > 0 else None


def _get_building_footprint_area_m2(building_shape: Any) -> Optional[float]:
    _, v = _first_attr(building_shape, FOOTPRINT_AREA_ATTR_CANDIDATES)
    fv = _safe_float(v)
    if fv is not None and fv > 0:
        return fv
    return _shape_area_m2(building_shape)


def _get_building_floors(building_shape: Any) -> Optional[int]:
    _, v = _first_attr(building_shape, FLOOR_ATTR_CANDIDATES)
    iv = _safe_int(v)
    if iv is not None and iv > 0:
        return iv
    return None


def _set_attr(obj: Any, name: str, value: Any) -> None:
    try:
        ce.setAttribute(obj, name, value)
    except Exception:
        # Fail softly: CityEngine can have non-writable attrs in some contexts.
        pass


# -----------------------------
# Main logic
# -----------------------------

selected = _get_selection()
if not selected:
    raise RuntimeError("No selection. Select Blocks and/or Lot/Building shapes and run again.")

# Expand selection into blocks/shapes/models
blocks = ce.getObjectsFrom(selected, ce.isBlock)
selected_shapes = ce.getObjectsFrom(selected, ce.isShape)
selected_models = ce.getObjectsFrom(selected, ce.isModel)

# If blocks are selected, gather lots (shapes adjacent to blocks)
lots_from_blocks: List[Any] = []
buildings_from_blocks: List[Any] = []
for b in blocks:
    # CityEngine convention: lot shapes are shapes adjacent to a block
    lots_from_blocks.extend(ce.getObjectsFrom(b, ce.isShape))
    # and any models associated with those shapes are "buildings" in many setups
    models = ce.getObjectsFrom(b, ce.isModel)
    for m in models:
        buildings_from_blocks.extend(ce.getObjectsFrom(m, ce.isShape))

# Candidate lots: explicit selected shapes + derived from blocks
all_lots: List[Any] = []
all_lots.extend(selected_shapes)
all_lots.extend(lots_from_blocks)

# De-dup while preserving order
_seen = set()
dedup_lots: List[Any] = []
for s in all_lots:
    oid = None
    try:
        oid = ce.getOID(s)
    except Exception:
        oid = id(s)
    if oid in _seen:
        continue
    _seen.add(oid)
    dedup_lots.append(s)
all_lots = dedup_lots

# Candidate buildings: shapes from selected models, plus shapes directly selected, plus from blocks
buildings: List[Any] = []
for m in selected_models:
    buildings.extend(ce.getObjectsFrom(m, ce.isShape))
buildings.extend(selected_shapes)  # if user selected buildings directly
buildings.extend(buildings_from_blocks)

# De-dup buildings
_seen = set()
dedup_buildings: List[Any] = []
for s in buildings:
    oid = None
    try:
        oid = ce.getOID(s)
    except Exception:
        oid = id(s)
    if oid in _seen:
        continue
    _seen.add(oid)
    dedup_buildings.append(s)
buildings = dedup_buildings

# Assign block IDs
for i, b in enumerate(blocks, start=1):
    bid = _format_id(BLOCK_PREFIX, i)
    _set_attr(b, BLOCK_ID_ATTR, bid)
    if RENAME_OBJECTS:
        try:
            ce.setName(b, bid)
        except Exception:
            pass

# Assign lot IDs (only if lots are present)
for i, lot in enumerate(all_lots, start=1):
    lid = _format_id(LOT_PREFIX, i)
    _set_attr(lot, LOT_ID_ATTR, lid)
    if RENAME_OBJECTS:
        try:
            ce.setName(lot, lid)
        except Exception:
            pass

# Compute building GFA and write attrs
building_gfa_by_lot: Dict[str, float] = {}
building_gfa_by_block: Dict[str, float] = {}
total_building_gfa = 0.0

for b in buildings:
    floors = _get_building_floors(b)
    footprint = _get_building_footprint_area_m2(b)
    if floors is None or footprint is None:
        continue

    gfa = float(floors) * float(footprint)
    if not math.isfinite(gfa) or gfa <= 0:
        continue

    _set_attr(b, BUILDING_FOOTPRINT_AREA_ATTR, float(footprint))
    _set_attr(b, BUILDING_GFA_ATTR, float(gfa))

    total_building_gfa += gfa

    # Aggregate by lot_id/block_id if present
    lot_id = None
    block_id = None
    try:
        lot_id = ce.getAttribute(b, LOT_ID_ATTR)
    except Exception:
        lot_id = None
    try:
        block_id = ce.getAttribute(b, BLOCK_ID_ATTR)
    except Exception:
        block_id = None

    if isinstance(lot_id, str) and lot_id:
        building_gfa_by_lot[lot_id] = building_gfa_by_lot.get(lot_id, 0.0) + gfa
    if isinstance(block_id, str) and block_id:
        building_gfa_by_block[block_id] = building_gfa_by_block.get(block_id, 0.0) + gfa

# Write lot totals and FAR
for lot in all_lots:
    lid = None
    try:
        lid = ce.getAttribute(lot, LOT_ID_ATTR)
    except Exception:
        lid = None
    if not isinstance(lid, str) or not lid:
        continue

    site_area = _shape_area_m2(lot)
    if site_area is None or site_area <= 0:
        continue

    lot_gfa = building_gfa_by_lot.get(lid, 0.0)
    far = (lot_gfa / site_area) if site_area > 0 else None

    _set_attr(lot, LOT_SITE_AREA_ATTR, float(site_area))
    _set_attr(lot, LOT_GFA_ATTR, float(lot_gfa))
    if far is not None and math.isfinite(far):
        _set_attr(lot, LOT_FAR_ATTR, float(far))

# Write block totals and FAR
for block in blocks:
    bid = None
    try:
        bid = ce.getAttribute(block, BLOCK_ID_ATTR)
    except Exception:
        bid = None
    if not isinstance(bid, str) or not bid:
        continue

    # Site area for block: sum of adjacent lot areas if possible, else skip.
    block_lots = ce.getObjectsFrom(block, ce.isShape)
    site_area = 0.0
    any_area = False
    for lot in block_lots:
        a = _shape_area_m2(lot)
        if a is None:
            continue
        any_area = True
        site_area += float(a)
    if not any_area or site_area <= 0:
        continue

    block_gfa = building_gfa_by_block.get(bid, 0.0)
    far = (block_gfa / site_area) if site_area > 0 else None

    _set_attr(block, BLOCK_SITE_AREA_ATTR, float(site_area))
    _set_attr(block, BLOCK_GFA_ATTR, float(block_gfa))
    if far is not None and math.isfinite(far):
        _set_attr(block, BLOCK_FAR_ATTR, float(far))

print(
    "Done. Blocks:", len(blocks),
    "Lots:", len(all_lots),
    "Buildings processed:", len(buildings),
    "Total building GFA:", round(total_building_gfa, 3), "m2"
)

