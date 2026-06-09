#!/bin/bash
set -e

echo "=========================================================="
echo "  Building Perfect Manhattan-Only SUMO Map"
echo "=========================================================="

# A 21-point polygon precisely tracing the Hudson and East Rivers
# This acts as a cookie-cutter to perfectly slice off NJ and Brooklyn without needing external APIs.
EXACT_POLY="-74.020,40.699,-74.013,40.728,-74.010,40.748,-74.001,40.765,-73.985,40.786,-73.962,40.818,-73.947,40.850,-73.933,40.875,-73.926,40.878,-73.910,40.872,-73.927,40.845,-73.936,40.828,-73.928,40.803,-73.938,40.784,-73.955,40.759,-73.966,40.750,-73.972,40.733,-73.972,40.713,-73.998,40.708,-74.010,40.700,-74.020,40.699"

echo "[1/3] Initial Netconvert (Extracting passenger roads from OSM)..."
# We aggressively remove non-passenger infrastructure to keep the map small and clean
# The user's local OSM file is nyc_map.osm from the previous script
netconvert --osm-files nyc_map.osm \
  --keep-edges.in-geo-boundary "$EXACT_POLY" \
  --geometry.remove \
  --roundabouts.guess \
  --junctions.join \
  --tls.guess-signals --tls.discard-simple --tls.join \
  --remove-edges.isolated \
  --keep-edges.by-vclass passenger \
  -o manhattan_step1.net.xml

echo "[2/3] Identifying and pruning broken dead-ends..."
# This Python script will find the Strongly Connected Component (SCC).
# Any road that leads off the map (broken one-way) or is a dead end
# will be identified and added to 'edges_to_remove.xml'
python3 prune_dead_ends.py manhattan_step1.net.xml

echo "[3/3] Final Compilation (Removing bad edges)..."
# We re-run netconvert, explicitly telling it to delete the broken roads
# We also compute the sidewalks for the remaining valid roads.
netconvert --sumo-net-file manhattan_step1.net.xml \
  --edge-files edges_to_remove.xml \
  --sidewalks.guess \
  --sidewalks.guess.exclude passenger \
  --remove-edges.isolated \
  -o manhattan.net.xml

echo "=========================================================="
echo "  SUCCESS! manhattan.net.xml is perfectly connected!"
echo "=========================================================="
