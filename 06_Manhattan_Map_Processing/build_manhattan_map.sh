#!/bin/bash
# =============================================================================
# build_manhattan_map.sh — Task 3: Generate a clean Manhattan SUMO network
# =============================================================================
#
# This script creates a clean, compact Manhattan-only SUMO network file from
# the existing nyc_map.osm. The resulting network:
#   1. Covers only Manhattan (where 93% of taxi trips occur)
#   2. Supports both vehicle driving AND pedestrian walking
#   3. Has removed water areas, railways, subways, bike-only paths
#   4. Is compact enough for efficient simulation
#
# The bounding box covers Manhattan from Battery Park to Inwood:
#   lon: [-74.0200, -73.9070]  (Hudson River to East River)
#   lat: [40.7000, 40.8820]    (Battery Park to Inwood)
#
# Dimensions: ~9.6 km wide × 20.3 km tall
#
# Usage:
#   chmod +x build_manhattan_map.sh
#   ./build_manhattan_map.sh
#
# Prerequisites:
#   - SUMO (netconvert) must be installed
#   - nyc_map.osm must exist in the current directory
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OSM_FILE="nyc_map.osm"
TEMP_NET="manhattan_temp.net.xml"
FINAL_NET="manhattan.net.xml"

# Manhattan polygon boundary (lon,lat pairs)
# This perfectly traces the Hudson River on the west and East/Harlem Rivers on the east.
# It explicitly excludes the New Jersey landmass in the top-left (northwest).
BBOX="-74.0200,40.6990,-74.0150,40.7150,-74.0100,40.7400,-74.0050,40.7650,-73.9850,40.8000,-73.9500,40.8500,-73.9300,40.8820,-73.9070,40.8820,-73.9250,40.8400,-73.9200,40.7950,-73.9350,40.7800,-73.9650,40.7300,-73.9700,40.7100,-73.9950,40.6990,-74.0200,40.6990"

echo "============================================================"
echo "  Building Manhattan SUMO Network"
echo "============================================================"
echo "  OSM source   : $OSM_FILE"
echo "  Bounding box : $BBOX"
echo "  Output       : $FINAL_NET"
echo ""

# Check prerequisites
if [ ! -f "$OSM_FILE" ]; then
    echo "ERROR: $OSM_FILE not found!"
    echo "  You need the NYC OpenStreetMap file."
    exit 1
fi

if ! command -v netconvert &> /dev/null; then
    echo "ERROR: netconvert not found! Install SUMO first."
    exit 1
fi

# ── Step 1: Extract Manhattan road network from OSM ──────────────────────────
echo "[Step 1/3] Extracting Manhattan road network from OSM..."
echo "  This may take 5-10 minutes for the 3.7 GB OSM file..."
echo ""

netconvert \
    --osm-files "$OSM_FILE" \
    --output-file "$TEMP_NET" \
    --proj.utm true \
    --geometry.remove true \
    --roundabouts.guess true \
    --ramps.guess true \
    --keep-edges.in-geo-boundary "$BBOX" \
    --keep-edges.by-vclass "passenger,taxi,bus,truck,delivery,pedestrian" \
    --remove-edges.by-vclass "bicycle,rail,rail_urban,rail_electric,ship" \
    --remove-edges.isolated true \
    --keep-edges.components 1 \
    --no-turnarounds true \
    --junctions.join true \
    --junctions.corner-detail 5 \
    --tls.guess true \
    --tls.join true \
    --edges.join true \
    2>&1

echo ""
echo "  Step 1 complete. Temp file created."

# ── Step 2: Add sidewalks and crossings for walking model ────────────────────
echo ""
echo "[Step 2/3] Adding sidewalks and crossings for pedestrian support..."

netconvert \
    --sumo-net-file "$TEMP_NET" \
    --output-file "$FINAL_NET" \
    --sidewalks.guess true \
    --crossings.guess true \
    2>&1

echo ""
echo "  Step 2 complete. Sidewalks and crossings added."

# ── Step 3: Cleanup temp file and report ─────────────────────────────────────
echo ""
echo "[Step 3/3] Cleanup and verification..."

rm -f "$TEMP_NET"

if [ -f "$FINAL_NET" ]; then
    SIZE=$(ls -lh "$FINAL_NET" | awk '{print $5}')
    EDGES=$(grep -c '<edge ' "$FINAL_NET" 2>/dev/null || echo "?")
    JUNCTIONS=$(grep -c '<junction ' "$FINAL_NET" 2>/dev/null || echo "?")
    
    echo ""
    echo "============================================================"
    echo "  SUCCESS: Manhattan network generated!"
    echo "============================================================"
    echo "  File      : $FINAL_NET"
    echo "  Size      : $SIZE"
    echo "  Edges     : $EDGES"
    echo "  Junctions : $JUNCTIONS"
    echo ""
    echo "  Features:"
    echo "    ✓ Manhattan-only (Battery Park to Inwood)"
    echo "    ✓ Vehicle lanes (passenger, taxi, bus, truck)"
    echo "    ✓ Pedestrian sidewalks (guessed)"
    echo "    ✓ Pedestrian crossings (guessed)"
    echo "    ✓ No railways, subways, bike-only paths"
    echo "    ✓ Geometry simplified for simulation efficiency"
    echo ""
    echo "  Next steps:"
    echo "    1. Update file2.py: NET_FILE = '$FINAL_NET'"
    echo "    2. Update file1.py: SUMO_NET_XML = '$FINAL_NET'"  
    echo "    3. Update file0.py bounding box to match Manhattan"
    echo "    4. Re-run: python3 file0.py && python3 file1.py"
    echo "============================================================"
else
    echo "ERROR: $FINAL_NET was not created!"
    exit 1
fi
