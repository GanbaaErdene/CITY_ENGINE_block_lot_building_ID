# -*- coding: utf-8 -*-
"""
CityEngine Selected Objects FAR / GFA / Building Count Calculator

ЗӨВХӨН SELECT ХИЙСЭН OBJECT-УУДААС ТООЦНО.
OSM_Buildings layer-ээс автоматаар авахгүй.

ArcGIS CityEngine 2025: Jython (scripting) болон Python 3 (cityengine) хоёуланд ажиллана.

Сайжруулалт:
- Building_Count давхар тоологдохоос хамгаалсан; нэг барилга олон shape бол нэг key-р тоолно
- Давхар face-үүдэд GFA нэг удаа л нэмэгдэж, бусад дээр Lot/Block ID хуулна (DUPLICATE_FACE)
- getAttribute-ийн list утгыг (CE 2019.1+) зөв боловсруулна
- Барилгын ID: osm_id, OBJECTID, ref, building:part гэх мэт нэмэлт талбарууд
- Барилга боловсруулалтыг OID-оор тогтвортой эрэмбэлнэ
"""

from __future__ import print_function, division

import math
import sys
import time

try:
    from scripting import CE
except ImportError:
    from cityengine import CE

ce = CE()
start_time = time.time()

# =====================================================
# SETTINGS
# =====================================================

DEFAULT_FLOORS = 1.0
DEFAULT_FLOOR_HEIGHT = 3.0
GRID_CELL_SIZE = 200.0
PROGRESS_STEP = 100

LOT_ID = "Lot_ID"
BLOCK_ID = "Block_ID"
LOT_AREA = "Lot_Area"
BLOCK_AREA = "Block_Area"
TOTAL_GFA = "Total_GFA"
ACTUAL_FAR = "Actual_FAR"
FAR_COLOR = "FAR_Color"
FAR_INDICATOR = "FAR_Indicator"
FAR_LABEL = "FAR_Label"
BUILDING_COUNT = "Building_Count"

FOOTPRINT_AREA = "Footprint_Area"
DETECTED_FLOORS = "Detected_Floors"
BUILDING_GFA = "Building_GFA"
LOT_MATCH_STATUS = "Lot_Match_Status"
BLOCK_MATCH_STATUS = "Block_Match_Status"

FLOOR_ATTRS = [
    "Detected_Floors",
    "/ce/rule/Detected_Floors",
    "building__levels",
    "/ce/rule/building__levels",
    "building:levels",
    "/ce/rule/building:levels",
    "building_levels",
    "/ce/rule/building_levels",
    "floors",
    "/ce/rule/floors",
    "floorCount",
    "/ce/rule/floorCount",
    "Stories",
    "/ce/rule/Stories",
    "stories",
    "/ce/rule/stories",
]

HEIGHT_ATTRS = [
    "height",
    "/ce/rule/height",
    "total_height",
    "/ce/rule/total_height",
]

FOOTPRINT_AREA_ATTRS = [
    FOOTPRINT_AREA,
    "footprint_area_m2",
    "footprint_area",
    "FootprintArea",
    "footprintArea",
    "base_area",
    "BaseArea",
]

CLEAN_ATTRS_ALL = [
    "lot_id",
    "block_id",
    "Lot_Area_m2",
    "Block_Area_m2",
    "Total_GFA_m2",
    "FAR",
    "FAR_Class",
    "Floors",
    "BuildingCount",
    "building_count",
    "actual_far",
    "Actual FAR",
    "material.color.r",
    "material.color.g",
    "material.color.b",
    "material.color.rgb",
]

LOT_OUTPUT_ATTRS = [
    LOT_ID,
    BLOCK_ID,
    LOT_AREA,
    BLOCK_AREA,
    TOTAL_GFA,
    ACTUAL_FAR,
    FAR_COLOR,
    FAR_INDICATOR,
    FAR_LABEL,
    BUILDING_COUNT,
    BLOCK_MATCH_STATUS,
]

BUILDING_OUTPUT_ATTRS = [
    FOOTPRINT_AREA,
    DETECTED_FLOORS,
    BUILDING_GFA,
    LOT_ID,
    BLOCK_ID,
    LOT_MATCH_STATUS,
    BLOCK_MATCH_STATUS,
]

JUNK_ON_LOT_ATTRS = [
    "building",
    "amenity",
    "office",
    "shop",
    "tourism",
    "leisure",
    "building__levels",
    "building:levels",
    "building_levels",
    "height",
    "total_height",
]

attribute_error_count = 0
delete_error_count = 0


# =====================================================
# BASIC HELPERS
# =====================================================

def safe_print(message):
    print(message)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def get_selection():
    try:
        return list(ce.selection)
    except Exception:
        try:
            return list(ce.selection())
        except Exception:
            return []


def get_objects_from(source, predicate):
    try:
        return list(ce.getObjectsFrom(source, predicate))
    except Exception:
        return []


def get_oid(obj):
    try:
        return str(ce.getOID(obj))
    except Exception:
        return str(id(obj))


def get_name(obj):
    try:
        return str(ce.getName(obj))
    except Exception:
        return ""


def normalize_attr_value(value):
    """CityEngine 2019.1+: array attributes return list, not dict."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return None
        return value[0]
    return value


def get_attr(obj, attr_name, default_value=None):
    try:
        value = normalize_attr_value(ce.getAttribute(obj, attr_name))
        if value is not None and str(value) != "":
            return value
    except Exception:
        pass
    return default_value


def get_attr_text(obj, attr_name, default_value=""):
    try:
        raw = normalize_attr_value(ce.getAttribute(obj, attr_name))
        if raw is None:
            return default_value
        return str(raw)
    except Exception:
        return default_value


def set_attr(obj, attr_name, value):
    global attribute_error_count
    try:
        ce.setAttribute(obj, attr_name, value)
        return True
    except Exception as e:
        attribute_error_count += 1
        if attribute_error_count <= 20:
            safe_print("[ATTRIBUTE ERROR] " + attr_name + " = " + str(value) + " | " + str(e))
        return False


def delete_attr(objects, attr_name):
    global delete_error_count

    if objects is None or len(objects) == 0:
        return True

    try:
        ce.deleteAttribute(objects, attr_name)
        return True
    except Exception:
        pass

    ok = True
    for obj in objects:
        try:
            ce.deleteAttribute([obj], attr_name)
        except Exception:
            ok = False
            delete_error_count += 1

    return ok


def delete_attrs(objects, attrs):
    for attr in attrs:
        delete_attr(objects, attr)


def to_float(value, default_value=None):
    if value is None:
        return default_value

    try:
        return float(value)
    except Exception:
        pass

    try:
        text = str(value)
        number_text = ""
        started = False

        for ch in text:
            if ch.isdigit() or ch == "." or (ch == "-" and not started):
                number_text += ch
                started = True
            elif number_text != "":
                break

        if number_text not in ["", "-", "."]:
            return float(number_text)
    except Exception:
        pass

    return default_value


def is_finite(value):
    try:
        return not (math.isnan(value) or math.isinf(value))
    except Exception:
        return False


def unique_objects(objects):
    result = []
    seen = {}

    for obj in objects:
        oid = get_oid(obj)
        if oid not in seen:
            result.append(obj)
            seen[oid] = True

    return result


def append_unique(target, source):
    seen = {}
    for obj in target:
        seen[get_oid(obj)] = True

    for obj in source:
        oid = get_oid(obj)
        if oid not in seen:
            target.append(obj)
            seen[oid] = True


# =====================================================
# GEOMETRY
# =====================================================

def vertices_to_xz(vertices):
    points = []

    if vertices is None:
        return points

    if len(vertices) >= 6 and len(vertices) % 3 == 0:
        for i in range(0, len(vertices), 3):
            points.append((float(vertices[i]), float(vertices[i + 2])))

    elif len(vertices) >= 4 and len(vertices) % 2 == 0:
        for i in range(0, len(vertices), 2):
            points.append((float(vertices[i]), float(vertices[i + 1])))

    return points


def get_polygon(obj):
    try:
        return vertices_to_xz(ce.getVertices(obj))
    except Exception:
        return []


def polygon_area(points):
    if len(points) < 3:
        return 0.0

    area = 0.0
    j = len(points) - 1

    for i in range(len(points)):
        area += points[j][0] * points[i][1] - points[i][0] * points[j][1]
        j = i

    return abs(area) / 2.0


def polygon_center(points):
    if len(points) == 0:
        return None

    sx = 0.0
    sz = 0.0

    for point in points:
        sx += point[0]
        sz += point[1]

    return (sx / len(points), sz / len(points))


def bbox_from_points(points):
    if len(points) == 0:
        return None

    xs = [point[0] for point in points]
    zs = [point[1] for point in points]

    return (min(xs), min(zs), max(xs), max(zs))


def point_in_bbox(point, bbox):
    if point is None or bbox is None:
        return False

    x, z = point
    minx, minz, maxx, maxz = bbox

    return minx <= x <= maxx and minz <= z <= maxz


def point_in_polygon(point, polygon):
    if point is None or len(polygon) < 3:
        return False

    x, z = point
    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        xi, zi = polygon[i]
        xj, zj = polygon[j]

        if (zi > z) != (zj > z):
            intersect = (xj - xi) * (z - zi) / ((zj - zi) + 0.000000001) + xi
            if x < intersect:
                inside = not inside

        j = i

    return inside


def sample_points_from_polygon(points):
    samples = []

    center = polygon_center(points)
    if center is not None:
        samples.append(center)

    if center is None or len(points) == 0:
        return samples

    cx, cz = center

    for p in points:
        samples.append((cx * 0.4 + p[0] * 0.6, cz * 0.4 + p[1] * 0.6))

    for i in range(len(points)):
        p1 = points[i]
        p2 = points[(i + 1) % len(points)]
        mx = (p1[0] + p2[0]) / 2.0
        mz = (p1[1] + p2[1]) / 2.0
        samples.append((cx * 0.4 + mx * 0.6, cz * 0.4 + mz * 0.6))

    return samples


# =====================================================
# BUILDING UNIQUE KEY
# =====================================================

def _first_non_empty_text(building, names):
    for attr_name in names:
        text = get_attr_text(building, attr_name, "")
        if text != "":
            return attr_name, text
    return None, ""


def get_building_key(building):
    """
    Building_Count давхар тоологдохоос хамгаална.
    Нэг барилгын олон shape/face ижил name + ойролцоо center эсвэл ижил ID байвал нэг гэж үзнэ.
    """
    name = get_name(building)

    _, building_id = _first_non_empty_text(
        building,
        [
            "osm_id",
            "osm_way_id",
            "id",
            "OBJECTID",
            "objectid",
            "FID",
            "full_id",
            "gml_id",
            "building_id",
            "ref",
            "ref:building",
            "building:part",
        ],
    )
    if building_id != "":
        return "id_" + building_id

    poly = get_polygon(building)
    center = polygon_center(poly)

    if center is not None:
        x = round(center[0], 1)
        z = round(center[1], 1)
        return "geom_" + name + "_" + str(x) + "_" + str(z)

    return "oid_" + get_oid(building)


# =====================================================
# SPATIAL GRID
# =====================================================

class SpatialGrid:
    def __init__(self, cell_size):
        self.cell_size = cell_size
        self.grid = {}

    def cell(self, x, z):
        return (int(x // self.cell_size), int(z // self.cell_size))

    def insert(self, bbox, item):
        if bbox is None:
            return

        minx, minz, maxx, maxz = bbox
        c1 = self.cell(minx, minz)
        c2 = self.cell(maxx, maxz)

        for cx in range(c1[0], c2[0] + 1):
            for cz in range(c1[1], c2[1] + 1):
                key = (cx, cz)
                if key not in self.grid:
                    self.grid[key] = []
                self.grid[key].append(item)

    def candidates(self, point):
        if point is None:
            return []

        return self.grid.get(self.cell(point[0], point[1]), [])


def build_grid(items):
    grid = SpatialGrid(GRID_CELL_SIZE)

    for item in items:
        grid.insert(item["bbox"], item)

    return grid


def match_point(point, grid):
    for item in grid.candidates(point):
        if point_in_bbox(point, item["bbox"]) and point_in_polygon(point, item["polygon"]):
            return item

    return None


def match_polygon_best(poly, grid):
    samples = sample_points_from_polygon(poly)
    scores = {}

    for point in samples:
        item = match_point(point, grid)

        if item is not None:
            oid = get_oid(item["obj"])

            if oid not in scores:
                scores[oid] = {
                    "item": item,
                    "count": 0
                }

            scores[oid]["count"] += 1

    best_item = None
    best_count = 0

    for oid in scores:
        if scores[oid]["count"] > best_count:
            best_item = scores[oid]["item"]
            best_count = scores[oid]["count"]

    return best_item


# =====================================================
# CLASSIFICATION
# =====================================================

def is_lot_shape(obj):
    name = get_name(obj)
    shape_type = get_attr_text(obj, "shapeType", "")
    start_rule = get_attr_text(obj, "/ce/rule/startRule", "")

    if name == "Lot" or name.startswith("Lot"):
        return True
    if shape_type == "Lot":
        return True
    if start_rule == "Lot":
        return True

    return False


def is_block_shape(obj):
    name = get_name(obj)
    shape_type = get_attr_text(obj, "shapeType", "")

    if name == "Block" or name.startswith("Block"):
        return True
    if shape_type == "Block":
        return True

    return False


def is_building_shape(obj):
    name = get_name(obj)

    if name == "Building" or name.startswith("Building"):
        return True

    if get_attr_text(obj, "building", "") != "":
        return True
    if get_attr_text(obj, "building__levels", "") != "":
        return True
    if get_attr_text(obj, "building:levels", "") != "":
        return True
    if get_attr_text(obj, "building_levels", "") != "":
        return True
    if get_attr_text(obj, "amenity", "") != "":
        return True
    if get_attr_text(obj, "office", "") != "":
        return True
    if get_attr_text(obj, "shop", "") != "":
        return True
    if get_attr_text(obj, "tourism", "") != "":
        return True
    if get_attr_text(obj, "leisure", "") != "":
        return True

    return False


def classify_selection():
    selection = get_selection()

    if len(selection) == 0:
        raise Exception("No selection. Lot + Building object-уудаа хамтад нь select хийгээд Run хийнэ.")

    selected_shapes = get_objects_from(selection, ce.isShape)
    selected_blocks = get_objects_from(selection, ce.isBlock)
    selected_models = get_objects_from(selection, ce.isModel)

    lots = []
    blocks = []
    buildings = []
    ignored = []

    for shape in selected_shapes:
        if is_lot_shape(shape):
            lots.append(shape)
        elif is_block_shape(shape):
            blocks.append(shape)
        elif is_building_shape(shape):
            buildings.append(shape)
        else:
            ignored.append(shape)

    for block in selected_blocks:
        blocks.append(block)

        child_shapes = get_objects_from(block, ce.isShape)
        for shape in child_shapes:
            if is_lot_shape(shape):
                lots.append(shape)
            elif is_building_shape(shape):
                buildings.append(shape)

        child_models = get_objects_from(block, ce.isModel)
        for model in child_models:
            append_unique(buildings, get_objects_from(model, ce.isShape))

    for model in selected_models:
        child_shapes = get_objects_from(model, ce.isShape)
        for shape in child_shapes:
            if is_building_shape(shape):
                buildings.append(shape)

    return selection, selected_shapes, unique_objects(lots), unique_objects(blocks), unique_objects(buildings), unique_objects(ignored)


# =====================================================
# AREA / ATTRIBUTE
# =====================================================

def first_positive_float(obj, attrs):
    for attr_name in attrs:
        value = get_attr(obj, attr_name, None)
        number = to_float(value, None)

        if number is not None and number > 0:
            return number

    return None


def shape_area(obj):
    attr_area = first_positive_float(obj, [LOT_AREA, BLOCK_AREA, "area_m2", "area", "Area"])

    if attr_area is not None:
        return attr_area

    return polygon_area(get_polygon(obj))


def building_footprint_area(obj):
    attr_area = first_positive_float(obj, FOOTPRINT_AREA_ATTRS)

    if attr_area is not None:
        return attr_area

    return polygon_area(get_polygon(obj))


def building_floors(obj):
    floors = first_positive_float(obj, FLOOR_ATTRS)

    if floors is not None and floors > 0:
        return floors

    height = first_positive_float(obj, HEIGHT_ATTRS)

    if height is not None and height > 0:
        return max(1.0, round(height / DEFAULT_FLOOR_HEIGHT))

    return DEFAULT_FLOORS


def make_lot_item(obj, index):
    poly = get_polygon(obj)
    area = polygon_area(poly)

    if area <= 0:
        area = shape_area(obj)

    if area <= 0:
        return None

    lot_id = "lot_" + str(index + 1)

    return {
        "obj": obj,
        "id": lot_id,
        "polygon": poly,
        "bbox": bbox_from_points(poly),
        "center": polygon_center(poly),
        "area": area,
        "total_gfa": 0.0,
        "building_count": 0,
        "building_oids": {}
    }


def make_block_item(obj, index):
    poly = get_polygon(obj)
    area = polygon_area(poly)

    if area <= 0:
        area = shape_area(obj)

    if area <= 0:
        area = 0.0

    block_id = "block_" + str(index + 1)

    return {
        "obj": obj,
        "id": block_id,
        "polygon": poly,
        "bbox": bbox_from_points(poly),
        "center": polygon_center(poly),
        "area": area,
        "total_gfa": 0.0,
        "building_count": 0,
        "building_oids": {}
    }


def add_building_to_item(item, building_key, gfa):
    if building_key in item["building_oids"]:
        return False

    item["building_oids"][building_key] = True
    item["building_count"] += 1
    item["total_gfa"] += gfa

    return True


# =====================================================
# FAR STYLE
# =====================================================

def far_indicator(far):
    if far < 0.5:
        return "VERY_LOW"
    if far < 1.0:
        return "LOW"
    if far < 2.0:
        return "MEDIUM"
    if far < 3.0:
        return "HIGH"
    return "VERY_HIGH"


def far_color(far):
    if far < 0.5:
        return "#2ECC71"
    if far < 1.0:
        return "#F1C40F"
    if far < 2.0:
        return "#E67E22"
    if far < 3.0:
        return "#E74C3C"
    return "#8E0000"


# =====================================================
# MAIN
# =====================================================

def main():
    safe_print("")
    safe_print("===================================")
    safe_print(" SELECTED FAR / GFA STARTED")
    safe_print("===================================")

    selection, selected_shapes, lot_shapes, block_shapes, buildings, ignored = classify_selection()

    safe_print("Selected objects: " + str(len(selection)))
    safe_print("Selected shapes: " + str(len(selected_shapes)))
    safe_print("Lots found: " + str(len(lot_shapes)))
    safe_print("Blocks found: " + str(len(block_shapes)))
    safe_print("Buildings found: " + str(len(buildings)))
    safe_print("Ignored shapes: " + str(len(ignored)))

    if len(lot_shapes) == 0:
        raise Exception("Lot олдсонгүй. Lot object-уудаа select хийнэ.")

    if len(buildings) == 0:
        raise Exception("Building олдсонгүй. Building object-уудаа Lot-той хамт select хийнэ.")

    all_selected = unique_objects(selected_shapes + lot_shapes + block_shapes + buildings)

    delete_attrs(all_selected, CLEAN_ATTRS_ALL)
    delete_attrs(lot_shapes, BUILDING_OUTPUT_ATTRS + JUNK_ON_LOT_ATTRS)
    delete_attrs(buildings, LOT_OUTPUT_ATTRS)

    lot_items = []

    for i in range(len(lot_shapes)):
        item = make_lot_item(lot_shapes[i], i)

        if item is not None:
            lot_items.append(item)

            set_attr(item["obj"], LOT_ID, item["id"])
            set_attr(item["obj"], LOT_AREA, float(item["area"]))
            set_attr(item["obj"], TOTAL_GFA, 0.0)
            set_attr(item["obj"], ACTUAL_FAR, 0.0)
            set_attr(item["obj"], BUILDING_COUNT, 0)

    if len(lot_items) == 0:
        raise Exception("Lot polygon area олдсонгүй. Lot geometry шалгана уу.")

    lot_grid = build_grid(lot_items)

    block_items = []

    for i in range(len(block_shapes)):
        item = make_block_item(block_shapes[i], i)

        if item is not None:
            block_items.append(item)
            set_attr(item["obj"], BLOCK_ID, item["id"])
            set_attr(item["obj"], BLOCK_AREA, float(item["area"]))

    block_grid = build_grid([b for b in block_items if b["bbox"] is not None])

    for lot in lot_items:
        matched_block = None

        if len(block_items) > 0:
            matched_block = match_point(lot["center"], block_grid)

        if matched_block is not None:
            lot["block_id"] = matched_block["id"]
            set_attr(lot["obj"], BLOCK_ID, matched_block["id"])
            set_attr(lot["obj"], BLOCK_MATCH_STATUS, "MATCHED")
        else:
            lot["block_id"] = ""
            set_attr(lot["obj"], BLOCK_ID, "")
            set_attr(lot["obj"], BLOCK_MATCH_STATUS, "NO_BLOCK_SELECTED")

    processed_buildings = 0
    duplicate_faces = 0
    matched_lots = 0
    unmatched_lots = 0
    total_gfa = 0.0
    canonical_building = {}

    buildings_ordered = sorted(buildings, key=get_oid)

    for i in range(len(buildings_ordered)):
        building = buildings_ordered[i]
        poly = get_polygon(building)

        if len(poly) < 3:
            set_attr(building, LOT_MATCH_STATUS, "NO_POLYGON")
            continue

        footprint = building_footprint_area(building)
        floors = building_floors(building)

        if footprint <= 0:
            set_attr(building, LOT_MATCH_STATUS, "NO_FOOTPRINT_AREA")
            continue

        gfa = float(footprint) * float(floors)

        if not is_finite(gfa) or gfa <= 0:
            set_attr(building, LOT_MATCH_STATUS, "INVALID_GFA")
            continue

        building_key = get_building_key(building)

        if building_key in canonical_building:
            info = canonical_building[building_key]
            duplicate_faces += 1
            set_attr(building, FOOTPRINT_AREA, float(footprint))
            set_attr(building, DETECTED_FLOORS, float(floors))
            set_attr(building, BUILDING_GFA, 0.0)
            set_attr(building, LOT_ID, info["lot_id"])
            set_attr(building, BLOCK_ID, info["block_id"])
            set_attr(building, LOT_MATCH_STATUS, "DUPLICATE_FACE")
            set_attr(building, BLOCK_MATCH_STATUS, info["block_match_status"])
            continue

        processed_buildings += 1
        total_gfa += gfa

        set_attr(building, FOOTPRINT_AREA, float(footprint))
        set_attr(building, DETECTED_FLOORS, float(floors))
        set_attr(building, BUILDING_GFA, float(gfa))

        matched_lot = match_polygon_best(poly, lot_grid)

        lot_id_val = ""
        block_id_val = ""
        lot_match_status = "UNMATCHED"
        block_match_status = "UNMATCHED"

        if matched_lot is not None:
            if add_building_to_item(matched_lot, building_key, gfa):
                matched_lots += 1

            lot_id_val = matched_lot["id"]
            set_attr(building, LOT_ID, lot_id_val)
            set_attr(building, LOT_MATCH_STATUS, "MATCHED")
            lot_match_status = "MATCHED"

            if "block_id" in matched_lot:
                block_id_val = matched_lot["block_id"]
                set_attr(building, BLOCK_ID, block_id_val)
                if matched_lot["block_id"] != "":
                    set_attr(building, BLOCK_MATCH_STATUS, "MATCHED")
                    block_match_status = "MATCHED"
                else:
                    set_attr(building, BLOCK_MATCH_STATUS, "NO_BLOCK_SELECTED")
                    block_match_status = "NO_BLOCK_SELECTED"
        else:
            unmatched_lots += 1
            set_attr(building, LOT_ID, "")
            set_attr(building, BLOCK_ID, "")
            set_attr(building, LOT_MATCH_STATUS, "UNMATCHED")
            set_attr(building, BLOCK_MATCH_STATUS, "UNMATCHED")

        canonical_building[building_key] = {
            "lot_id": lot_id_val,
            "block_id": block_id_val,
            "block_match_status": block_match_status,
        }

        if (i + 1) % PROGRESS_STEP == 0 or (i + 1) == len(buildings_ordered):
            safe_print("Processing buildings: " + str(i + 1) + "/" + str(len(buildings_ordered)))

    for lot in lot_items:
        far = 0.0

        if lot["area"] > 0:
            far = lot["total_gfa"] / lot["area"]

        indicator = far_indicator(far)
        color = far_color(far)

        set_attr(lot["obj"], LOT_ID, lot["id"])
        set_attr(lot["obj"], LOT_AREA, float(lot["area"]))
        set_attr(lot["obj"], TOTAL_GFA, float(lot["total_gfa"]))
        set_attr(lot["obj"], ACTUAL_FAR, float(far))
        set_attr(lot["obj"], FAR_COLOR, color)
        set_attr(lot["obj"], FAR_INDICATOR, indicator)
        set_attr(lot["obj"], FAR_LABEL, indicator + " FAR " + str(round(far, 3)))
        set_attr(lot["obj"], BUILDING_COUNT, int(lot["building_count"]))

    for block in block_items:
        block_total_gfa = 0.0
        block_area_sum = 0.0
        block_count = 0
        block_building_oids = {}

        for lot in lot_items:
            if "block_id" in lot and lot["block_id"] == block["id"]:
                block_total_gfa += lot["total_gfa"]
                block_area_sum += lot["area"]

                for key in lot["building_oids"]:
                    if key not in block_building_oids:
                        block_building_oids[key] = True
                        block_count += 1

        area = block_area_sum
        if area <= 0:
            area = block["area"]

        far = 0.0
        if area > 0:
            far = block_total_gfa / area

        set_attr(block["obj"], BLOCK_ID, block["id"])
        set_attr(block["obj"], BLOCK_AREA, float(area))
        set_attr(block["obj"], TOTAL_GFA, float(block_total_gfa))
        set_attr(block["obj"], ACTUAL_FAR, float(far))
        set_attr(block["obj"], BUILDING_COUNT, int(block_count))
        set_attr(block["obj"], FAR_COLOR, far_color(far))
        set_attr(block["obj"], FAR_INDICATOR, far_indicator(far))
        set_attr(block["obj"], FAR_LABEL, far_indicator(far) + " FAR " + str(round(far, 3)))

    safe_print("")
    safe_print("===================================")
    safe_print(" SUCCESS")
    safe_print("===================================")
    safe_print("Lots calculated: " + str(len(lot_items)))
    safe_print("Blocks calculated: " + str(len(block_items)))
    safe_print("Buildings processed unique: " + str(processed_buildings))
    safe_print("Duplicate faces (same building key): " + str(duplicate_faces))
    safe_print("Buildings matched to Lots: " + str(matched_lots))
    safe_print("Buildings unmatched to Lots: " + str(unmatched_lots))
    safe_print("Total selected building GFA: " + str(round(total_gfa, 3)) + " m2")
    safe_print("Attribute write errors: " + str(attribute_error_count))
    safe_print("Attribute delete errors: " + str(delete_error_count))
    safe_print("Time: " + str(round(time.time() - start_time, 2)) + "s")
    safe_print("===================================")


try:
    main()

except Exception as e:
    safe_print("")
    safe_print("===================================")
    safe_print(" ERROR")
    safe_print("===================================")
    safe_print("Error: " + str(e))
    safe_print("Time: " + str(round(time.time() - start_time, 2)) + "s")
    safe_print("Attribute write errors: " + str(attribute_error_count))
    safe_print("Attribute delete errors: " + str(delete_error_count))
    safe_print("===================================")
