# CITY_ENGINE_block_lot_building_ID

## Optimized CityEngine 2025 FAR script

Use `fast_far_block_report_optimized.py` in CityEngine 2025 to join OSM
buildings to Lot and Block shapes and write `Fast_FAR_Block_Report.csv`.

The optimized script is faster than the original nested-loop version because it
builds a lightweight spatial grid index for lots and blocks. Each building is
tested only against nearby polygons instead of every lot and every block.

### How to use

1. Open the CityEngine scene.
2. Select the Building, Lot, and Block shapes you want to process. If nothing is
   selected, the script falls back to scene/layer lookup.
3. Confirm these names/attributes match your scene:
   - Building layer: `OSM_Buildings`
   - Floors attribute: `building__levels`
   - Lot ID attribute: `lot_id`
   - Block ID attribute: `block_id`
4. Run `fast_far_block_report_optimized.py` from CityEngine's Python scripting
   environment.
5. Check the generated CSV in the project `data` folder:
   `Fast_FAR_Block_Report.csv`.

Blocks are renamed and assigned IDs as `block_01`, `block_02`, and so on by
default. Set `OVERWRITE_BLOCK_IDS = False` in the script if existing block IDs
should be preserved.

### Speed tuning

The script automatically chooses a grid cell size from lot/block sizes. If it is
still slow on a very large scene, set these near the average polygon width in
scene units:

```python
LOT_GRID_CELL_SIZE = None
BLOCK_GRID_CELL_SIZE = None
```

For example, try `LOT_GRID_CELL_SIZE = 25.0` or `50.0`. Smaller cells reduce
candidates per building but create more index cells; larger cells create fewer
cells but may test more candidates.
