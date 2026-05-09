# -*- coding: utf-8 -*-
from scripting import *

import csv
import math
import os
import sys
import time

ce = CE()
start_time = time.time()

DEFAULT_FLOORS = 1.0
FLOOR_HEIGHT = 3.0

LOT_ID_FIELD = "lot_id"
BLOCK_ID_FIELD = "block_id"

OUT_LOT_ID_FIELD = "Lot_ID"
OUT_BLOCK_ID_FIELD = "Block_ID"
OUT_LOT_AREA_FIELD = "Lot_Area"
OUT_LOT_AREA_M2_FIELD = "Lot_Area_m2"
OUT_BLOCK_AREA_FIELD = "Block_Area"
OUT_TOTAL_GFA_FIELD = "Total_GFA"
OUT_TOTAL_GFA_M2_FIELD = "Total_GFA_m2"
OUT_ACTUAL_FAR_FIELD = "Actual_FAR"
OUT_FAR_FIELD = "FAR"
OUT_BUILDING_COUNT_FIELD = "Building_Count"
OUT_BUILDING_GFA_FIELD = "Building_GFA"
OUT_BUILDING_FLOORS_FIELD = "Detected_Floors"
OUT_BUILDING_USED_FLOORS_FIELD = "Used_Floors"
OUT_LOT_MATCH_STATUS_FIELD = "Lot_Match_Status"
OUT_BLOCK_MATCH_STATUS_FIELD = "Block_Match_Status"

BUILDING_PROGRESS_STEP = 100
REPORT_FILE_NAME = "Fast_FAR_Block_Report.csv"

LOT_GRID_CELL_SIZE = None
BLOCK_GRID_CELL_SIZE = None
MAX_INDEX_CELLS_PER_POLYGON = 400

BLOCK_ID_PREFIX = "block"
BLOCK_ID_PADDING = 2
OVERWRITE_BLOCK_IDS = True


def safe_print(message):
    print(message)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def safe_set_attribute(obj, attr_name, attr_value):
    try:
        ce.setAttribute(obj, attr_name, attr_value)
    except Exception:
        pass


def safe_get_attribute(obj, attr_name, default_value=None):
    try:
        value = ce.getAttribute(obj, attr_name)
        return default_value if value is None else value
    except Exception:
        return default_value


def safe_get_rule_attribute(obj, attr_name, default_value=None):
    try:
        value = ce.getRuleAttribute(obj, attr_name)
        return default_value if value is None else value
    except Exception:
        return default_value


def get_attribute_text(obj, attr_name, default_value):
    value = safe_get_attribute(obj, attr_name, None)
    if value is None:
        return default_value
    text = str(value).strip()
    return text if text else default_value


def to_float(value, default_value):
    if value is None:
        return default_value
    try:
        return float(value)
    except Exception:
        pass
    try:
        text = str(value).strip().replace(",", ".")
        cleaned = "".join(c for c in text if c.isdigit() or c in ".-")
        if cleaned in ("", ".", "-", "-."):
            return default_value
        return float(cleaned)
    except Exception:
        return default_value


def get_oid_text(obj, prefix):
    try:
        return prefix + "_" + str(ce.getOID(obj))
    except Exception:
        return prefix + "_" + str(int(time.time() * 1000))


def safe_get_name(obj):
    try:
        return ce.getName(obj)
    except Exception:
        return ""


def safe_set_name(obj, name):
    try:
        ce.setName(obj, name)
    except Exception:
        pass


def safe_get_vertices(obj):
    try:
        return ce.getVertices(obj)
    except Exception:
        return None


def get_building_floors(building):
    # IMPORTANT: This function MUST NOT write floor/level attributes back to the object.
    # It only reads candidates and returns a floor count used for GFA computation.
    candidates = [
        # Prefer explicit detected floors when present (user-provided / upstream).
        # Read both object attributes and rule attributes, and support common naming variants.
        to_float(safe_get_attribute(building, OUT_BUILDING_FLOORS_FIELD), 0.0),
        to_float(safe_get_rule_attribute(building, OUT_BUILDING_FLOORS_FIELD), 0.0),
        to_float(safe_get_attribute(building, "Detected_floor"), 0.0),
        to_float(safe_get_rule_attribute(building, "Detected_floor"), 0.0),
        to_float(safe_get_rule_attribute(building, "building__levels"), 0.0),
        to_float(safe_get_rule_attribute(building, "building_levels"), 0.0),
        to_float(safe_get_attribute(building, "building__levels"), 0.0),
        to_float(safe_get_attribute(building, "building_levels"), 0.0),
        to_float(safe_get_attribute(building, "building:levels"), 0.0),
        to_float(safe_get_attribute(building, "levels"), 0.0),
        to_float(safe_get_attribute(building, "floors"), 0.0),
        to_float(safe_get_rule_attribute(building, "floors"), 0.0),
        to_float(safe_get_attribute(building, "num_floors"), 0.0),
        to_float(safe_get_rule_attribute(building, "num_floors"), 0.0),
        to_float(safe_get_attribute(building, "BuildingColo.building__levels"), 0.0),
        to_float(safe_get_attribute(building, "BuildingColo.building_levels"), 0.0),
        to_float(safe_get_attribute(building, "BuildingColor.building__levels"), 0.0),
        to_float(safe_get_attribute(building, "BuildingColor.building_levels"), 0.0),
        to_float(safe_get_rule_attribute(building, "BuildingColo.building__levels"), 0.0),
        to_float(safe_get_rule_attribute(building, "BuildingColo.building_levels"), 0.0),
        to_float(safe_get_rule_attribute(building, "BuildingColor.building__levels"), 0.0),
        to_float(safe_get_rule_attribute(building, "BuildingColor.building_levels"), 0.0),
    ]

    height_value = max(
        to_float(safe_get_attribute(building, "height"), 0.0),
        to_float(safe_get_rule_attribute(building, "height"), 0.0),
    )
    total_height_value = max(
        to_float(safe_get_attribute(building, "total_height"), 0.0),
        to_float(safe_get_rule_attribute(building, "total_height"), 0.0),
    )

    if height_value > 0:
        candidates.append(height_value / FLOOR_HEIGHT)

    if total_height_value > 0:
        candidates.append(total_height_value / FLOOR_HEIGHT)

    valid = [f for f in candidates if f > 0]
    if not valid:
        return DEFAULT_FLOORS
    return max(DEFAULT_FLOORS, max(valid))


def vertices_to_xz(vertices):
    if not vertices:
        return []
    return [(vertices[i], vertices[i + 2]) for i in range(0, len(vertices) - 2, 3)]


def polygon_area_xz(poly):
    if not poly or len(poly) < 3:
        return 0.0
    area = 0.0
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        area += poly[i][0] * poly[j][1] - poly[j][0] * poly[i][1]
    return abs(area) / 2.0


def polygon_center_xz(poly):
    if not poly:
        return None
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def polygon_bbox(poly):
    if not poly:
        return None
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    return (min(xs), min(zs), max(xs), max(zs))


def bbox_contains_point(bbox, pt):
    x, z = pt
    return bbox[0] <= x <= bbox[2] and bbox[1] <= z <= bbox[3]


def point_on_segment(pt, a, b, tolerance=1e-6):
    x, z = pt
    x1, z1 = a
    x2, z2 = b
    cross = (x - x1) * (z2 - z1) - (z - z1) * (x2 - x1)
    if abs(cross) > tolerance:
        return False
    dot = (x - x1) * (x2 - x1) + (z - z1) * (z2 - z1)
    if dot < -tolerance:
        return False
    seg_len = (x2 - x1) * (x2 - x1) + (z2 - z1) * (z2 - z1)
    return dot <= seg_len + tolerance


def is_inside_fast(pt, poly):
    x, z = pt
    inside = False
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        if ((poly[i][1] > z) != (poly[j][1] > z)) and (
            x < (poly[j][0] - poly[i][0]) * (z - poly[i][1]) / (poly[j][1] - poly[i][1] + 1e-9) + poly[i][0]
        ):
            inside = not inside
    return inside


def is_inside_or_on_boundary(pt, poly):
    for i in range(len(poly)):
        if point_on_segment(pt, poly[i], poly[(i + 1) % len(poly)]):
            return True
    return is_inside_fast(pt, poly)


def median(values, default_value):
    values = sorted(v for v in values if v > 0)
    if not values:
        return default_value
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def auto_grid_cell_size(records, configured_value):
    if configured_value and configured_value > 0:
        return float(configured_value)
    sizes = []
    for record in records:
        bbox = record["bbox"]
        sizes.append(bbox[2] - bbox[0])
        sizes.append(bbox[3] - bbox[1])
    return max(1.0, median(sizes, 25.0))


class SpatialIndex(object):
    def __init__(self, records, configured_cell_size=None):
        self.records = records
        self.cell_size = auto_grid_cell_size(records, configured_cell_size)
        self.cells = {}
        self.overflow = []
        self.indexed_count = 0

        for record in records:
            if not record.get("bbox"):
                continue

            cr = self._bbox_cell_range(record["bbox"])
            cell_count = (cr[2] - cr[0] + 1) * (cr[3] - cr[1] + 1)

            if cell_count > MAX_INDEX_CELLS_PER_POLYGON:
                self.overflow.append(record)
                continue

            for cx in range(cr[0], cr[2] + 1):
                for cz in range(cr[1], cr[3] + 1):
                    self.cells.setdefault((cx, cz), []).append(record)

            self.indexed_count += 1

    def _cell_coord(self, value):
        return int(math.floor(value / self.cell_size))

    def _bbox_cell_range(self, bbox):
        return (
            self._cell_coord(bbox[0]),
            self._cell_coord(bbox[1]),
            self._cell_coord(bbox[2]),
            self._cell_coord(bbox[3]),
        )

    def candidates_for_point(self, pt):
        key = (self._cell_coord(pt[0]), self._cell_coord(pt[1]))
        return self.cells.get(key, []) + self.overflow


def find_containing_record(pt, spatial_index):
    if not spatial_index:
        return None
    for record in spatial_index.candidates_for_point(pt):
        if bbox_contains_point(record["bbox"], pt) and is_inside_or_on_boundary(pt, record["poly"]):
            return record
    return None


def make_block_id(number):
    return BLOCK_ID_PREFIX + "_" + str(number).zfill(BLOCK_ID_PADDING)


def get_buildings_lots_blocks():
    safe_print("Selection дотроос объектууд уншиж байна...")

    selected_shapes = ce.getObjectsFrom(ce.selection, ce.isShape)

    selected_blocks = []
    try:
        selected_blocks = ce.getObjectsFrom(ce.selection, ce.isBlock)
    except Exception:
        selected_blocks = []

    if not selected_blocks:
        try:
            selected_blocks = ce.getObjectsFrom(ce.scene, ce.isBlock)
        except Exception:
            selected_blocks = []

    buildings = []
    lots = []
    blocks = []

    safe_print("Сонгогдсон shape: " + str(len(selected_shapes)))
    safe_print("Олдсон Block object: " + str(len(selected_blocks)))

    for shape in selected_shapes:
        name = safe_get_name(shape).lower()
        building_value = get_attribute_text(shape, "building", "")
        lot_id_value = get_attribute_text(shape, LOT_ID_FIELD, "")
        block_id_value = get_attribute_text(shape, BLOCK_ID_FIELD, "")

        if name == "lot" or name.startswith("lot") or lot_id_value != "":
            lots.append(shape)
        elif name == "block" or name.startswith("block") or block_id_value != "":
            blocks.append(shape)
        elif building_value != "":
            buildings.append(shape)
        else:
            buildings.append(shape)

    for block in selected_blocks:
        if block not in blocks:
            blocks.append(block)

    safe_print(
        "Selection ангилалт:"
        + " Buildings: " + str(len(buildings))
        + " | Lots: " + str(len(lots))
        + " | Blocks: " + str(len(blocks))
    )

    return buildings, lots, blocks


def build_block_map(blocks):
    block_map = []
    fallback_block_id = ""

    safe_print("\nBlock ID үүсгэж байна...")

    valid_number = 0

    for block in blocks:
        valid_number += 1
        block_id = make_block_id(valid_number) if OVERWRITE_BLOCK_IDS else get_attribute_text(block, BLOCK_ID_FIELD, "")
        if not block_id:
            block_id = get_oid_text(block, "B")

        if not fallback_block_id:
            fallback_block_id = block_id

        safe_set_name(block, block_id)
        safe_set_attribute(block, BLOCK_ID_FIELD, block_id)
        safe_set_attribute(block, OUT_BLOCK_ID_FIELD, block_id)

        poly = vertices_to_xz(safe_get_vertices(block))
        if len(poly) < 3:
            safe_print("   Block geometry уншигдсангүй. Fallback ID ашиглана: " + block_id)
            continue

        area = polygon_area_xz(poly)
        bbox = polygon_bbox(poly)

        safe_set_attribute(block, OUT_BLOCK_AREA_FIELD, float(area))

        block_map.append({
            "obj": block,
            "id": str(block_id),
            "name": str(block_id),
            "poly": poly,
            "bbox": bbox,
            "area": area,
        })

    safe_print("Block map дууслаа: " + str(len(block_map)))
    if fallback_block_id:
        safe_print("Fallback Block_ID: " + fallback_block_id)

    return block_map, fallback_block_id


def build_lot_map(lots, block_index, fallback_block_id):
    lot_map = []
    matched = 0

    safe_print("Lot map бэлдэж байна...")

    for idx, lot in enumerate(lots):
        if idx > 0 and idx % 100 == 0:
            safe_print("   Lot processing... " + str(idx) + " / " + str(len(lots)))

        poly = vertices_to_xz(safe_get_vertices(lot))
        if len(poly) < 3:
            continue

        center = polygon_center_xz(poly)
        area = polygon_area_xz(poly)

        block_id = ""
        block_status = "UNMATCHED"

        block_record = find_containing_record(center, block_index) if center and block_index else None
        if block_record:
            block_id = block_record["id"]
            block_status = "MATCHED"
            matched += 1
        elif fallback_block_id:
            block_id = fallback_block_id
            block_status = "FALLBACK"
            matched += 1

        lot_id = get_attribute_text(lot, LOT_ID_FIELD, "") or get_oid_text(lot, "L")

        safe_set_attribute(lot, LOT_ID_FIELD, lot_id)
        safe_set_attribute(lot, BLOCK_ID_FIELD, block_id)
        safe_set_attribute(lot, OUT_LOT_ID_FIELD, lot_id)
        safe_set_attribute(lot, OUT_BLOCK_ID_FIELD, block_id)
        safe_set_attribute(lot, OUT_LOT_AREA_FIELD, float(area))
        safe_set_attribute(lot, OUT_LOT_AREA_M2_FIELD, float(area))
        safe_set_attribute(lot, OUT_BLOCK_MATCH_STATUS_FIELD, block_status)

        lot_map.append({
            "obj": lot,
            "id": str(lot_id),
            "block_id": str(block_id),
            "block_status": block_status,
            "poly": poly,
            "bbox": polygon_bbox(poly),
            "area": area,
            "gfa": 0.0,
            "b_count": 0,
        })

    safe_print("Lot map дууслаа: " + str(len(lot_map)) + " | block id орсон: " + str(matched))
    return lot_map, matched, len(lot_map) - matched


def process_buildings(buildings, lot_index, block_index, fallback_block_id):
    safe_print("\nБарилгуудыг Lot/Block-той spatial index ашиглан тулгаж байна...")

    stats = {"ml": 0, "ul": 0, "mb": 0, "ub": 0, "inv": 0}

    for idx, building in enumerate(buildings):
        if idx > 0 and idx % BUILDING_PROGRESS_STEP == 0:
            safe_print("   Building processing... " + str(idx) + " / " + str(len(buildings)))

        poly = vertices_to_xz(safe_get_vertices(building))
        if len(poly) < 3:
            stats["inv"] += 1
            continue

        center = polygon_center_xz(poly)
        if not center:
            stats["inv"] += 1
            continue

        floors = get_building_floors(building)
        b_area = polygon_area_xz(poly)
        # User requirement: scale total GFA by floor height as well.
        b_gfa = b_area * floors * FLOOR_HEIGHT

        safe_set_attribute(building, OUT_BUILDING_GFA_FIELD, float(b_gfa))
        safe_set_attribute(building, OUT_BUILDING_USED_FLOORS_FIELD, float(floors))

        matched_lot = find_containing_record(center, lot_index)
        if matched_lot:
            matched_lot["gfa"] += b_gfa
            matched_lot["b_count"] += 1
            safe_set_attribute(building, OUT_LOT_ID_FIELD, matched_lot["id"])
            safe_set_attribute(building, OUT_LOT_MATCH_STATUS_FIELD, "MATCHED")
            stats["ml"] += 1
        else:
            safe_set_attribute(building, OUT_LOT_MATCH_STATUS_FIELD, "UNMATCHED")
            stats["ul"] += 1

        matched_block = find_containing_record(center, block_index) if block_index else None
        if matched_block:
            safe_set_attribute(building, OUT_BLOCK_ID_FIELD, matched_block["id"])
            safe_set_attribute(building, OUT_BLOCK_MATCH_STATUS_FIELD, "MATCHED")
            stats["mb"] += 1
        elif fallback_block_id:
            safe_set_attribute(building, OUT_BLOCK_ID_FIELD, fallback_block_id)
            safe_set_attribute(building, OUT_BLOCK_MATCH_STATUS_FIELD, "FALLBACK")
            stats["mb"] += 1
        else:
            safe_set_attribute(building, OUT_BLOCK_MATCH_STATUS_FIELD, "UNMATCHED")
            stats["ub"] += 1

    safe_print("Барилгын тулгалт дууслаа.")
    return stats


def get_report_path():
    project_path = ce.toFSPath("/")
    if project_path:
        data_dir = os.path.join(project_path, "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return os.path.join(data_dir, REPORT_FILE_NAME)
    return os.path.join(os.path.expanduser("~"), REPORT_FILE_NAME)


def write_lot_results_and_report(lot_map):
    total_lots = len(lot_map)
    safe_print("\nLot дээр үр дүн бичиж, CSV үүсгэж байна...")
    safe_print("Нийт Lot: " + str(total_lots))

    report_path = get_report_path()
    safe_print("CSV файл: " + report_path)

    with open(report_path, "w") as report_file:
        writer = csv.writer(report_file)
        writer.writerow([
            "Block_ID",
            "Lot_ID",
            "Lot_Area_sqm",
            "Building_Count",
            "Total_GFA_sqm",
            "Actual_FAR",
            "FAR",
            "Block_Match_Status",
        ])

        for idx, lot in enumerate(lot_map):
            safe_print("   Lot " + str(idx + 1) + " / " + str(total_lots) + " бичиж байна...")

            far = lot["gfa"] / lot["area"] if lot["area"] > 0 else 0.0

            safe_set_attribute(lot["obj"], OUT_TOTAL_GFA_FIELD, float(lot["gfa"]))
            safe_set_attribute(lot["obj"], OUT_TOTAL_GFA_M2_FIELD, float(lot["gfa"]))
            safe_set_attribute(lot["obj"], OUT_ACTUAL_FAR_FIELD, float(far))
            safe_set_attribute(lot["obj"], OUT_FAR_FIELD, float(far))
            safe_set_attribute(lot["obj"], OUT_BUILDING_COUNT_FIELD, int(lot["b_count"]))

            writer.writerow([
                lot["block_id"],
                lot["id"],
                round(lot["area"], 2),
                lot["b_count"],
                round(lot["gfa"], 2),
                round(far, 6),
                round(far, 6),
                lot["block_status"],
            ])

    safe_print("[АМЖИЛТТАЙ] CSV тайлан: " + report_path)


def run_optimized_script():
    safe_print("\n=== FAST JOIN SCRIPT STARTED ===")

    buildings, lots, blocks = get_buildings_lots_blocks()

    safe_print("Buildings: " + str(len(buildings)) + " | Lots: " + str(len(lots)) + " | Blocks: " + str(len(blocks)))

    if not buildings:
        raise Exception("Барилга олдсонгүй!")
    if not lots:
        raise Exception("Lot олдсонгүй!")

    block_map, fallback_block_id = build_block_map(blocks)

    safe_print("Block spatial index үүсгэж байна...")
    block_index = SpatialIndex(block_map, BLOCK_GRID_CELL_SIZE) if block_map else None

    if block_index:
        safe_print(
            "Block index: "
            + str(len(block_index.cells))
            + " cells | "
            + str(block_index.indexed_count)
            + " indexed | "
            + str(len(block_index.overflow))
            + " overflow | cell size "
            + str(round(block_index.cell_size, 2))
        )

    lot_map, l_m, l_um = build_lot_map(lots, block_index, fallback_block_id)

    safe_print("Lot spatial index үүсгэж байна...")
    lot_index = SpatialIndex(lot_map, LOT_GRID_CELL_SIZE) if lot_map else None

    if lot_index:
        safe_print(
            "Lot index: "
            + str(len(lot_index.cells))
            + " cells | "
            + str(lot_index.indexed_count)
            + " indexed | "
            + str(len(lot_index.overflow))
            + " overflow | cell size "
            + str(round(lot_index.cell_size, 2))
        )

    res = process_buildings(buildings, lot_index, block_index, fallback_block_id)
    write_lot_results_and_report(lot_map)

    safe_print("\n=== SUCCESS | Time: " + str(round(time.time() - start_time, 2)) + "s ===")
    safe_print("Lot->Block matched: " + str(l_m) + " | unmatched: " + str(l_um))
    safe_print("Matched Lots: " + str(res["ml"]) + " | Unmatched: " + str(res["ul"]) + " | Invalid: " + str(res["inv"]))
    safe_print("Matched Blocks: " + str(res["mb"]) + " | Unmatched: " + str(res["ub"]))


if __name__ == "__main__":
    run_optimized_script()

