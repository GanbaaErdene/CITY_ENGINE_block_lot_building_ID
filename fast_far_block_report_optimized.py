# -*- coding: utf-8 -*-
"""
Optimized CityEngine 2025 script for joining OSM buildings to lots and blocks.

This version builds a lightweight grid spatial index and includes progress
messages so you can see exactly where the script is working.
"""
from scripting import *

import csv
import math
import os
import sys
import time


ce = CE()
start_time = time.time()

# ==================================================
# SETTINGS
# ==================================================
BUILDING_LAYER_NAME = "OSM_Buildings"
FLOORS_FIELD = "building__levels"
DEFAULT_FLOORS = 1.0

LOT_ID_FIELD = "lot_id"
BLOCK_ID_FIELD = "block_id"

OUT_LOT_ID_FIELD = "Lot_ID"
OUT_BLOCK_ID_FIELD = "Block_ID"
OUT_LOT_AREA_FIELD = "Lot_Area"
OUT_BLOCK_AREA_FIELD = "Block_Area"
OUT_TOTAL_GFA_FIELD = "Total_GFA"
OUT_ACTUAL_FAR_FIELD = "Actual_FAR"
OUT_BUILDING_COUNT_FIELD = "Building_Count"
OUT_BUILDING_GFA_FIELD = "Building_GFA"
OUT_BUILDING_FLOORS_FIELD = "Detected_Floors"
OUT_LOT_MATCH_STATUS_FIELD = "Lot_Match_Status"
OUT_BLOCK_MATCH_STATUS_FIELD = "Block_Match_Status"

BUILDING_PROGRESS_STEP = 100
REPORT_FILE_NAME = "Fast_FAR_Block_Report.csv"

# Leave these as None for automatic sizing. If matching is still slow, set
# LOT_GRID_CELL_SIZE near the average lot width in scene units.
LOT_GRID_CELL_SIZE = None
BLOCK_GRID_CELL_SIZE = None
MAX_INDEX_CELLS_PER_POLYGON = 400

BLOCK_ID_PREFIX = "block"
BLOCK_ID_PADDING = 2
OVERWRITE_BLOCK_IDS = True
USE_NEAREST_BLOCK_FALLBACK = True


# ==================================================
# BASIC FUNCTIONS
# ==================================================
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


def get_layer_by_name(layer_name):
    layers = ce.getObjectsFrom(ce.scene, ce.isLayer, ce.withName("'" + layer_name + "'"))
    if not layers:
        raise Exception("Layer not found: " + layer_name)
    return layers[0]


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


# ==================================================
# GEOMETRY FUNCTIONS
# ==================================================
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


def bbox_center(bbox):
    if not bbox:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def bbox_contains_point(bbox, pt):
    x, z = pt
    return bbox[0] <= x <= bbox[2] and bbox[1] <= z <= bbox[3]


def bbox_intersects(a, b):
    if not a or not b:
        return False
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def squared_distance(a, b):
    return (a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1])


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

    widths = []
    heights = []
    for record in records:
        bbox = record["bbox"]
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])

    typical_size = median(widths + heights, 25.0)
    return max(1.0, typical_size)


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
            cell_range = self._bbox_cell_range(record["bbox"])
            cell_count = (cell_range[2] - cell_range[0] + 1) * (cell_range[3] - cell_range[1] + 1)

            # Very large polygons, usually blocks, can cover too many cells.
            # Keep them in a small fallback list instead of bloating the index.
            if cell_count > MAX_INDEX_CELLS_PER_POLYGON:
                self.overflow.append(record)
                continue

            for cx in range(cell_range[0], cell_range[2] + 1):
                for cz in range(cell_range[1], cell_range[3] + 1):
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
        if self.overflow:
            return self.cells.get(key, []) + self.overflow
        return self.cells.get(key, [])


def find_containing_record(pt, spatial_index):
    for record in spatial_index.candidates_for_point(pt):
        if bbox_contains_point(record["bbox"], pt) and is_inside_fast(pt, record["poly"]):
            return record
    return None


def lot_sample_points(poly, bbox):
    points = []
    center = polygon_center_xz(poly)
    box_center = bbox_center(bbox)

    if center:
        points.append(center)
    if box_center and box_center != center:
        points.append(box_center)

    if poly:
        step = max(1, len(poly) // 8)
        for idx in range(0, len(poly), step):
            points.append(poly[idx])
            if len(points) >= 12:
                break

    return points


def find_best_block_for_lot(poly, bbox, block_index):
    if not block_index:
        return None, "UNMATCHED"

    points = lot_sample_points(poly, bbox)
    votes = {}

    for pt in points:
        record = find_containing_record(pt, block_index)
        if record:
            record_id = record["id"]
            votes[record_id] = votes.get(record_id, 0) + 1

    if votes:
        best_id = max(votes, key=votes.get)
        for record in block_index.records:
            if record["id"] == best_id:
                return record, "MATCHED"

    # If the lot center is outside because of geometry shape, try all overlapping
    # block bounding boxes and score them by sampled lot points.
    best_record = None
    best_score = 0
    for record in block_index.records:
        if not bbox_intersects(bbox, record["bbox"]):
            continue
        score = 0
        for pt in points:
            if bbox_contains_point(record["bbox"], pt) and is_inside_fast(pt, record["poly"]):
                score += 1
        if score > best_score:
            best_score = score
            best_record = record

    if best_record:
        return best_record, "MATCHED"

    if USE_NEAREST_BLOCK_FALLBACK:
        lot_center = bbox_center(bbox) or polygon_center_xz(poly)
        if lot_center:
            nearest_record = None
            nearest_distance = None
            for record in block_index.records:
                block_center = bbox_center(record["bbox"])
                if not block_center:
                    continue
                dist = squared_distance(lot_center, block_center)
                if nearest_distance is None or dist < nearest_distance:
                    nearest_distance = dist
                    nearest_record = record
            if nearest_record:
                return nearest_record, "NEAREST"

    return None, "UNMATCHED"


def make_block_id(number):
    return BLOCK_ID_PREFIX + "_" + str(number).zfill(BLOCK_ID_PADDING)


def name_startswith(obj, prefix):
    return safe_get_name(obj).lower().startswith(prefix.lower())


# ==================================================
# DATA COLLECTION
# ==================================================
def get_buildings_lots_blocks():
    safe_print("Selection дотроос объектууд уншиж байна...")

    selected_shapes = ce.getObjectsFrom(ce.selection, ce.isShape)
    selected_blocks_by_name = ce.getObjectsFrom(ce.selection, ce.withName("'Block'"))

    if selected_shapes or selected_blocks_by_name:
        buildings = []
        lots = []
        blocks = []

        safe_print("Сонгогдсон shape: " + str(len(selected_shapes)))
        safe_print("Сонгогдсон Block нэртэй объект: " + str(len(selected_blocks_by_name)))

        for shape in selected_shapes:
            name = safe_get_name(shape)
            building_value = get_attribute_text(shape, "building", "")
            lot_id_value = get_attribute_text(shape, LOT_ID_FIELD, "")
            block_id_value = get_attribute_text(shape, BLOCK_ID_FIELD, "")

            if name.lower() == "lot" or name.lower().startswith("lot") or lot_id_value != "":
                lots.append(shape)
            elif name.lower() == "block" or name.lower().startswith("block") or block_id_value != "":
                blocks.append(shape)
            elif building_value != "":
                buildings.append(shape)
            else:
                buildings.append(shape)

        for block in selected_blocks_by_name:
            if block not in blocks:
                blocks.append(block)

        safe_print(
            "Selection ангилалт:"
            + " Buildings: " + str(len(buildings))
            + " | Lots: " + str(len(lots))
            + " | Blocks: " + str(len(blocks))
        )
        return buildings, lots, blocks

    safe_print("Selection хоосон байна. Scene/layer дотроос хайж байна...")

    building_layer = get_layer_by_name(BUILDING_LAYER_NAME)
    buildings = ce.getObjectsFrom(building_layer, ce.isShape)

    lots = ce.getObjectsFrom(ce.scene, ce.isShape, ce.withName("'Lot'"))
    if not lots:
        lots = ce.getObjectsFrom(ce.scene, ce.withName("'Lot'"))

    blocks = ce.getObjectsFrom(ce.scene, ce.isShape, ce.withName("'Block'"))
    if not blocks:
        blocks = ce.getObjectsFrom(ce.scene, ce.withName("'Block'"))

    if not blocks:
        blocks = [s for s in ce.getObjectsFrom(ce.scene, ce.isShape) if name_startswith(s, "block")]
    if not lots:
        lots = [s for s in ce.getObjectsFrom(ce.scene, ce.isShape) if name_startswith(s, "lot")]

    return buildings, lots, blocks


def build_block_map(blocks):
    block_map = []
    safe_print("\nBlock ID үүсгэж байна...")

    valid_block_number = 0
    for idx, block in enumerate(blocks):
        if idx > 0 and idx % 100 == 0:
            safe_print("   Block processing... " + str(idx) + " / " + str(len(blocks)))

        poly = vertices_to_xz(safe_get_vertices(block))
        if len(poly) < 3:
            continue

        valid_block_number += 1
        if OVERWRITE_BLOCK_IDS:
            block_id = make_block_id(valid_block_number)
        else:
            block_id = get_attribute_text(block, BLOCK_ID_FIELD, "")
        if not block_id:
            block_id = get_oid_text(block, "B")

        area = polygon_area_xz(poly)
        bbox = polygon_bbox(poly)
        safe_set_name(block, block_id)
        safe_set_attribute(block, BLOCK_ID_FIELD, block_id)
        safe_set_attribute(block, OUT_BLOCK_ID_FIELD, block_id)
        safe_set_attribute(block, OUT_BLOCK_AREA_FIELD, float(area))

        block_map.append({"obj": block, "id": str(block_id), "poly": poly, "bbox": bbox, "area": area})

    safe_print("Block map дууслаа: " + str(len(block_map)))
    return block_map


def build_lot_map(lots, block_index):
    lot_map = []
    lot_block_matched = 0
    lot_block_nearest = 0
    safe_print("Lot map бэлдэж байна...")

    for idx, lot in enumerate(lots):
        if idx > 0 and idx % 100 == 0:
            safe_print("   Lot processing... " + str(idx) + " / " + str(len(lots)))

        poly = vertices_to_xz(safe_get_vertices(lot))
        if len(poly) < 3:
            continue

        bbox = polygon_bbox(poly)

        block_id = ""
        block_status = "UNMATCHED"
        block_record, block_status = find_best_block_for_lot(poly, bbox, block_index)
        if block_record:
            block_id = block_record["id"]
            lot_block_matched += 1
            if block_status == "NEAREST":
                lot_block_nearest += 1

        lot_id = get_attribute_text(lot, LOT_ID_FIELD, "") or get_oid_text(lot, "L")
        area = polygon_area_xz(poly)

        safe_set_attribute(lot, LOT_ID_FIELD, lot_id)
        safe_set_attribute(lot, BLOCK_ID_FIELD, block_id)
        safe_set_attribute(lot, OUT_LOT_ID_FIELD, lot_id)
        safe_set_attribute(lot, OUT_BLOCK_ID_FIELD, block_id)
        safe_set_attribute(lot, OUT_LOT_AREA_FIELD, float(area))
        safe_set_attribute(lot, OUT_BLOCK_MATCH_STATUS_FIELD, block_status)

        lot_map.append(
            {
                "obj": lot,
                "id": str(lot_id),
                "block_id": str(block_id),
                "block_status": block_status,
                "poly": poly,
                "bbox": bbox,
                "area": area,
                "gfa": 0.0,
                "b_count": 0,
            }
        )

    safe_print(
        "Lot map дууслаа: "
        + str(len(lot_map))
        + " | block id орсон: "
        + str(lot_block_matched)
        + " | nearest fallback: "
        + str(lot_block_nearest)
    )
    return lot_map, lot_block_matched, len(lot_map) - lot_block_matched


# ==================================================
# BUILDING MATCH
# ==================================================
def process_buildings(buildings, lot_index, block_index):
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

        floors = max(1.0, to_float(safe_get_attribute(building, FLOORS_FIELD), DEFAULT_FLOORS))
        b_area = polygon_area_xz(poly)
        b_gfa = b_area * floors

        safe_set_attribute(building, OUT_BUILDING_GFA_FIELD, float(b_gfa))
        safe_set_attribute(building, OUT_BUILDING_FLOORS_FIELD, float(floors))

        matched_lot = find_containing_record(center, lot_index) if lot_index else None
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
        else:
            safe_set_attribute(building, OUT_BLOCK_MATCH_STATUS_FIELD, "UNMATCHED")
            stats["ub"] += 1

    safe_print("Барилгын тулгалт дууслаа.")
    return stats


# ==================================================
# REPORT & MAIN
# ==================================================
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
    safe_print("CSV файл нээж байна...")

    # CityEngine Python environments can be picky about newline/encoding kwargs.
    # Plain open() keeps this compatible and lets progress messages reach the console.
    with open(report_path, "w") as report_file:
        safe_print("CSV файл нээгдлээ. Lot үр дүн бичиж эхэллээ...")
        writer = csv.writer(report_file)
        writer.writerow(
            [
                "Block_ID",
                "Lot_ID",
                "Lot_Area_sqm",
                "Building_Count",
                "Total_GFA_sqm",
                "Actual_FAR",
                "Block_Match_Status",
            ]
        )

        for idx, lot in enumerate(lot_map):
            lot_number = idx + 1
            safe_print("   Lot " + str(lot_number) + " / " + str(total_lots) + " бичиж байна...")

            far = lot["gfa"] / lot["area"] if lot["area"] > 0 else 0.0

            safe_set_attribute(lot["obj"], OUT_TOTAL_GFA_FIELD, float(lot["gfa"]))
            safe_set_attribute(lot["obj"], OUT_ACTUAL_FAR_FIELD, float(far))
            safe_set_attribute(lot["obj"], OUT_BUILDING_COUNT_FIELD, int(lot["b_count"]))

            writer.writerow(
                [
                    lot["block_id"],
                    lot["id"],
                    round(lot["area"], 2),
                    lot["b_count"],
                    round(lot["gfa"], 2),
                    round(far, 3),
                    lot["block_status"],
                ]
            )

    safe_print("Report writing дууслаа: " + str(total_lots) + " lot бичигдлээ.")
    safe_print("[АМЖИЛТТАЙ] CSV тайлан: " + report_path)


def run_optimized_script():
    safe_print("\n=== FAST JOIN SCRIPT STARTED ===")
    buildings, lots, blocks = get_buildings_lots_blocks()
    safe_print("Buildings: " + str(len(buildings)) + " | Lots: " + str(len(lots)) + " | Blocks: " + str(len(blocks)))

    if not buildings:
        raise Exception("OSM_Buildings давхаргаас барилга олдсонгүй!")
    if not lots:
        raise Exception("Lot олдсонгүй!")

    block_map = build_block_map(blocks)

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

    lot_map, l_m, l_um = build_lot_map(lots, block_index)

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

    res = process_buildings(buildings, lot_index, block_index)
    write_lot_results_and_report(lot_map)

    safe_print("\n=== SUCCESS | Time: " + str(round(time.time() - start_time, 2)) + "s ===")
    safe_print("Lot->Block matched: " + str(l_m) + " | unmatched: " + str(l_um))
    safe_print("Matched Lots: " + str(res["ml"]) + " | Unmatched: " + str(res["ul"]) + " | Invalid: " + str(res["inv"]))
    safe_print("Matched Blocks: " + str(res["mb"]) + " | Unmatched: " + str(res["ub"]))


if __name__ == "__main__":
    run_optimized_script()
