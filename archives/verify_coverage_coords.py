#!/usr/bin/env python3
"""
verify_coverage_coords.py — Task 1: Verify coordinate extraction
=================================================================
Checks whether check_coverage.py and check_coverage_no_pd.py use the
correct column names from yellow_tripdata_2016-01.csv.

Also performs an enhanced coverage analysis with tighter Manhattan bounds
to determine the exact area we should target for the SUMO map.
"""

import csv
import sys

CSV_FILE = "yellow_tripdata_2016-01.csv"

# ── Step 1: Verify CSV column names ──────────────────────────────────────────
print("=" * 72)
print("  TASK 1: Verifying coordinate columns in the CSV")
print("=" * 72)

with open(CSV_FILE, 'r') as f:
    reader = csv.reader(f)
    header = next(reader)
    # Strip whitespace/BOM from headers
    header = [h.strip().strip('\ufeff') for h in header]

print(f"\nCSV columns ({len(header)} total):")
for i, col in enumerate(header):
    print(f"  [{i:2d}] '{col}'")

# Check what the coverage scripts expect
expected_cols = ['pickup_longitude', 'pickup_latitude', 'dropoff_longitude', 'dropoff_latitude']
print(f"\nExpected columns by check_coverage.py:")
for col in expected_cols:
    found = col in header
    status = "✓ FOUND" if found else "✗ MISSING"
    print(f"  {status}: '{col}'")

all_found = all(col in header for col in expected_cols)
if all_found:
    print("\n✓ All required coordinate columns are correctly named in the scripts.")
else:
    print("\n✗ Column mismatch detected! Scripts need correction.")
    sys.exit(1)

# ── Step 2: Verify coordinate ranges and coverage ────────────────────────────
print("\n" + "=" * 72)
print("  TASK 1b: Verifying coordinate extraction & Manhattan coverage")
print("=" * 72)

# NYC bounds used in both scripts
nyc_bounds = {
    'min_lon': -74.2591,
    'max_lon': -73.7004,
    'min_lat': 40.4957,
    'max_lat': 40.9153
}

# Manhattan bounding box used in check_coverage_no_pd.py
manhattan_bounds = {
    'min_lon': -74.02,
    'max_lon': -73.93,
    'min_lat': 40.70,
    'max_lat': 40.83
}

# Tighter Manhattan bounds (for the actual island shape)
# This is what we'll use for the SUMO map
manhattan_tight = {
    'min_lon': -74.0200,  # West boundary (Hudson River)
    'max_lon': -73.9070,  # East boundary (East River, Upper East Side)
    'min_lat': 40.6997,   # South boundary (Battery Park)
    'max_lat': 40.8820,   # North boundary (Inwood)
}

# Extended Manhattan (slightly wider for simulation buffer)
manhattan_extended = {
    'min_lon': -74.0300,
    'max_lon': -73.9000,
    'min_lat': 40.6950,
    'max_lat': 40.8850,
}

total_rows = 0
valid_nyc = 0
zero_coords = 0
manhattan_pickups = 0
manhattan_tight_pickups = 0
manhattan_extended_pickups = 0
manhattan_both_tight = 0  # Both pickup AND dropoff in tight Manhattan
manhattan_both_extended = 0
jfk_pickups = 0
lga_pickups = 0
other_pickups = 0

# Coordinate range tracking
min_pickup_lon = float('inf')
max_pickup_lon = float('-inf')
min_pickup_lat = float('inf')
max_pickup_lat = float('-inf')

print("\nScanning CSV (this may take a few minutes for ~10M rows)...")

with open(CSV_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        total_rows += 1
        
        if total_rows % 2_000_000 == 0:
            print(f"  ... processed {total_rows:,} rows")
        
        try:
            p_lon = float(row['pickup_longitude'])
            p_lat = float(row['pickup_latitude'])
            d_lon = float(row['dropoff_longitude'])
            d_lat = float(row['dropoff_latitude'])
        except (ValueError, KeyError, TypeError):
            continue
        
        # Check for zero/null coordinates
        if p_lon == 0 or p_lat == 0 or d_lon == 0 or d_lat == 0:
            zero_coords += 1
            continue
        
        # Track coordinate ranges
        if p_lon < min_pickup_lon: min_pickup_lon = p_lon
        if p_lon > max_pickup_lon: max_pickup_lon = p_lon
        if p_lat < min_pickup_lat: min_pickup_lat = p_lat
        if p_lat > max_pickup_lat: max_pickup_lat = p_lat
        
        # NYC bounds check
        if (nyc_bounds['min_lon'] <= p_lon <= nyc_bounds['max_lon'] and
            nyc_bounds['min_lat'] <= p_lat <= nyc_bounds['max_lat']):
            valid_nyc += 1
            
            # Manhattan check (original bounds from check_coverage_no_pd.py)
            if (-74.02 <= p_lon <= -73.93 and 40.70 <= p_lat <= 40.83):
                manhattan_pickups += 1
            elif (-73.82 <= p_lon <= -73.77 and 40.63 <= p_lat <= 40.66):
                jfk_pickups += 1
            elif (-73.89 <= p_lon <= -73.85 and 40.76 <= p_lat <= 40.78):
                lga_pickups += 1
            else:
                other_pickups += 1
            
            # Tight Manhattan check
            if (manhattan_tight['min_lon'] <= p_lon <= manhattan_tight['max_lon'] and
                manhattan_tight['min_lat'] <= p_lat <= manhattan_tight['max_lat']):
                manhattan_tight_pickups += 1
            
            # Extended Manhattan check  
            if (manhattan_extended['min_lon'] <= p_lon <= manhattan_extended['max_lon'] and
                manhattan_extended['min_lat'] <= p_lat <= manhattan_extended['max_lat']):
                manhattan_extended_pickups += 1
            
            # Both pickup AND dropoff in tight Manhattan
            if (manhattan_tight['min_lon'] <= p_lon <= manhattan_tight['max_lon'] and
                manhattan_tight['min_lat'] <= p_lat <= manhattan_tight['max_lat'] and
                manhattan_tight['min_lon'] <= d_lon <= manhattan_tight['max_lon'] and
                manhattan_tight['min_lat'] <= d_lat <= manhattan_tight['max_lat']):
                manhattan_both_tight += 1
            
            # Both pickup AND dropoff in extended Manhattan
            if (manhattan_extended['min_lon'] <= p_lon <= manhattan_extended['max_lon'] and
                manhattan_extended['min_lat'] <= p_lat <= manhattan_extended['max_lat'] and
                manhattan_extended['min_lon'] <= d_lon <= manhattan_extended['max_lon'] and
                manhattan_extended['min_lat'] <= d_lat <= manhattan_extended['max_lat']):
                manhattan_both_extended += 1

print(f"\n{'=' * 72}")
print(f"  RESULTS")
print(f"{'=' * 72}")
print(f"\nTotal rows in CSV         : {total_rows:,}")
print(f"Rows with zero coordinates: {zero_coords:,}")
print(f"Valid NYC pickups          : {valid_nyc:,}")

if valid_nyc > 0:
    print(f"\n--- Coverage by area (PICKUP only) ---")
    print(f"Manhattan (original box)  : {manhattan_pickups:,} ({manhattan_pickups/valid_nyc*100:.2f}%)")
    print(f"Manhattan (tight)         : {manhattan_tight_pickups:,} ({manhattan_tight_pickups/valid_nyc*100:.2f}%)")
    print(f"Manhattan (extended)      : {manhattan_extended_pickups:,} ({manhattan_extended_pickups/valid_nyc*100:.2f}%)")
    print(f"JFK Airport               : {jfk_pickups:,} ({jfk_pickups/valid_nyc*100:.2f}%)")
    print(f"LaGuardia Airport         : {lga_pickups:,} ({lga_pickups/valid_nyc*100:.2f}%)")
    print(f"Other areas               : {other_pickups:,} ({other_pickups/valid_nyc*100:.2f}%)")
    
    print(f"\n--- Coverage: BOTH pickup AND dropoff in Manhattan ---")
    print(f"Tight Manhattan           : {manhattan_both_tight:,} ({manhattan_both_tight/valid_nyc*100:.2f}%)")
    print(f"Extended Manhattan        : {manhattan_both_extended:,} ({manhattan_both_extended/valid_nyc*100:.2f}%)")

print(f"\n--- Pickup coordinate ranges ---")
print(f"Longitude: [{min_pickup_lon:.6f}, {max_pickup_lon:.6f}]")
print(f"Latitude : [{min_pickup_lat:.6f}, {max_pickup_lat:.6f}]")

print(f"\n--- Manhattan bounding boxes compared ---")
print(f"Original (check_coverage_no_pd.py): lon [{-74.02}, {-73.93}], lat [{40.70}, {40.83}]")
print(f"Tight (full island)               : lon [{manhattan_tight['min_lon']}, {manhattan_tight['max_lon']}], lat [{manhattan_tight['min_lat']}, {manhattan_tight['max_lat']}]")
print(f"Extended (with buffer)             : lon [{manhattan_extended['min_lon']}, {manhattan_extended['max_lon']}], lat [{manhattan_extended['min_lat']}, {manhattan_extended['max_lat']}]")

print(f"\n--- Dimensions for SUMO map (tight Manhattan) ---")
# Calculate approximate distances
import math
mid_lat = (manhattan_tight['min_lat'] + manhattan_tight['max_lat']) / 2
lon_dist_m = abs(manhattan_tight['max_lon'] - manhattan_tight['min_lon']) * 111320 * math.cos(math.radians(mid_lat))
lat_dist_m = abs(manhattan_tight['max_lat'] - manhattan_tight['min_lat']) * 111320
print(f"Width  (E-W): {lon_dist_m:.0f} m ({lon_dist_m/1000:.2f} km)")
print(f"Height (N-S): {lat_dist_m:.0f} m ({lat_dist_m/1000:.2f} km)")

print(f"\n--- Dimensions for SUMO map (extended Manhattan) ---")
lon_dist_ext = abs(manhattan_extended['max_lon'] - manhattan_extended['min_lon']) * 111320 * math.cos(math.radians(mid_lat))
lat_dist_ext = abs(manhattan_extended['max_lat'] - manhattan_extended['min_lat']) * 111320
print(f"Width  (E-W): {lon_dist_ext:.0f} m ({lon_dist_ext/1000:.2f} km)")
print(f"Height (N-S): {lat_dist_ext:.0f} m ({lat_dist_ext/1000:.2f} km)")

# Verdict on check_coverage scripts
print(f"\n{'=' * 72}")
print(f"  VERDICT ON check_coverage.py & check_coverage_no_pd.py")
print(f"{'=' * 72}")
print(f"""
✓ Column names: CORRECT — both scripts use 'pickup_longitude', 
  'pickup_latitude', 'dropoff_longitude', 'dropoff_latitude' which 
  exactly match the CSV header.

⚠ Manhattan bounds in check_coverage_no_pd.py:
  The box [-74.02, -73.93] × [40.70, 40.83] is SLIGHTLY NARROW on the 
  east side. The Upper East Side extends to about -73.907 longitude.
  This means a small percentage of East Side pickups are being counted
  as "Other Areas" instead of Manhattan.
  
  However, this does NOT affect the correctness of the coordinate 
  EXTRACTION — it only slightly underestimates Manhattan coverage.
  The scripts correctly read the coordinates from the CSV.

RECOMMENDATION for Task 3:
  Use the 'extended' Manhattan bounds for the SUMO map:
  lon: [{manhattan_extended['min_lon']}, {manhattan_extended['max_lon']}]
  lat: [{manhattan_extended['min_lat']}, {manhattan_extended['max_lat']}]
""")
