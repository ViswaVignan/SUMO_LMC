#!/bin/bash
# =============================================================================
# build_perfect_manhattan.sh
# Creates a 100% Connected Manhattan + Airports map using Regional Highway Filtering
# to keep file size < 50MB.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OSM_FILE="nyc_map.osm"
if [ ! -f "$OSM_FILE" ]; then
    echo "Error: nyc_map.osm not found."
    exit 1
fi

MASTER_NET="master_temp.net.xml"
FILTERED_NET="filtered_temp.net.xml"
REGIONAL_EDGES="regional_keep_edges.txt"
KEEP_EDGES="keep_edges.txt"
REVERSE_EDGES="reverse_edges.edg.xml"
FINAL_NET="manhattan.net.xml"

# Massive BBOX covering Manhattan + LGA + JFK as a polygon
LARGE_BBOX="-74.05,40.60,-73.70,40.60,-73.70,40.90,-74.05,40.90"

echo "============================================================"
echo "  Building Connected Manhattan + Airports SUMO Network"
echo "============================================================"

# Step 1: Extract Master OSM Region (No sidewalks yet)
echo ""
echo "[Step 1/5] Extracting Massive Master OSM Region..."
netconvert \
    --osm-files "$OSM_FILE" \
    --output-file "$MASTER_NET" \
    --proj.utm true \
    --geometry.remove true \
    --roundabouts.guess true \
    --ramps.guess true \
    --keep-edges.in-geo-boundary "$LARGE_BBOX" \
    --remove-edges.by-type "highway.footway,highway.path,highway.steps,highway.pedestrian,highway.cycleway,highway.service,railway.rail,railway.tram,railway.subway,railway.light_rail,railway.preserved" \
    --remove-edges.by-vclass "bicycle,rail,rail_urban,rail_electric,rail_fast,tram,ship,bus,truck,delivery,coach,trailer,motorcycle,moped" \
    --junctions.join true \
    --junctions.corner-detail 5 \
    --edges.join true \
    2>&1 | grep -v "Warning:" | tail -n 10

# Step 2: Regional Filtering via Python
echo ""
echo "[Step 2/5] Filtering Local Roads (keeping only Manhattan & Airports) vs Regional Highways..."
python3 filter_regions.py "$MASTER_NET" "$REGIONAL_EDGES"

# Step 3: Apply Regional Filter
echo ""
echo "[Step 3/5] Applying Regional Filter to significantly reduce file size..."
netconvert \
    --sumo-net-file "$MASTER_NET" \
    --keep-edges.input-file "$REGIONAL_EDGES" \
    --output-file "$FILTERED_NET" \
    2>&1 | grep -v "Warning:" | tail -n 10

# Step 4: WCC + SCC Analysis
echo ""
echo "[Step 4/5] Trimming isolated islands and generating reverse lanes for connectivity..."
python3 make_fully_connected.py "$FILTERED_NET" "$KEEP_EDGES" "$REVERSE_EDGES"

# Step 5: Final Re-build
echo ""
echo "[Step 5/5] Injecting reverse lanes, enabling U-turns, and generating sidewalks/crossings/lights..."
netconvert \
    --sumo-net-file "$FILTERED_NET" \
    --keep-edges.input-file "$KEEP_EDGES" \
    --edge-files "$REVERSE_EDGES" \
    --tls.discard-loaded true \
    --tls.guess true \
    --tls.join true \
    --sidewalks.guess true \
    --crossings.guess true \
    --walkingareas true \
    --output-file "$FINAL_NET" \
    2>&1 | grep -v "Warning:" | tail -n 10

echo ""
echo "Cleaning up temp files..."
rm -f "$MASTER_NET" "$FILTERED_NET" "$REGIONAL_EDGES" "$KEEP_EDGES" "$REVERSE_EDGES"

echo "Done! The new manhattan.net.xml successfully connects JFK and LGA while remaining lightweight!"
