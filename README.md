# CITY_ENGINE_block_lot_building_ID

CityEngine 2025 дээр ажиллуулах Python скрипт.

## Скрипт

- `cityengine/block_lot_id_gfa_far.py`
  - Сонгосон `Block` / `Lot` / `Building` (shape/model)-ууд дээр:
    - Блок болон лотод дараалсан ID өгнө: `block_01`, `lot_01`, …
    - Барилгын **GFA**: \(GFA = footprint\_area \times floors\)
    - Лот/блок дээр **FAR**: \(FAR = GFA / site\_area\)

## Ашиглах (CityEngine)

1. Scene дээр `Block` (эсвэл lot/building shape)-уудаа сонгоно.
2. Python Editor/Console дээр `cityengine/block_lot_id_gfa_far.py`-г ажиллуулна.
3. Inspector дээр дараах аттрибутууд нэмэгдсэн байна:
   - Block: `block_id`, `site_area_m2`, `gfa_total_m2`, `far`
   - Lot: `lot_id`, `site_area_m2`, `gfa_total_m2`, `far`
   - Building shape: `footprint_area_m2`, `gfa_m2`

## Тохиргоо

Хэрэв танай төслийн давхар/талбайн аттрибутын нэр өөр бол `block_lot_id_gfa_far.py` доторх:

- `FLOOR_ATTR_CANDIDATES`
- `FOOTPRINT_AREA_ATTR_CANDIDATES`

гэдгийг өөрчилж тааруулна.
