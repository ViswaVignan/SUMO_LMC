#!/usr/bin/env python3
"""
extract_24hr_trips.py — High-Performance 24-Hour Trip Extractor
=============================================================
Extracts 24 hours of real Manhattan taxi trips for:
  1. Tuesday, January 12, 2016 (Weekday Commuter Dynamics)
  2. Saturday, January 16, 2016 (Weekend Leisure / Nightlife Dynamics)

Uses strict Manhattan polygon boundaries, applies stratified temporal sampling
(10% calibrated rate for 1,400 vehicles) to maintain the exact empirical diurnal curve,
and unpacks multi-passenger trips with group_id tracking.

RAM safe: processes in streaming chunks (< 300 MB RAM).
"""

import os
import sys
import numpy as np
import pandas as pd
from matplotlib.path import Path

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../.."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../data"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

INPUT_CSV = os.path.join(DATA_DIR, "yellow_tripdata_2016-01.csv")

# Strict Manhattan Polygon
MANHATTAN_POLYGON = [
    (-74.0200, 40.7000), (-74.0200, 40.7100), (-74.0130, 40.7200),
    (-74.0100, 40.7400), (-74.0000, 40.7600), (-73.9850, 40.7800),
    (-73.9700, 40.8000), (-73.9450, 40.8400), (-73.9300, 40.8750),
    (-73.9100, 40.8780), (-73.9100, 40.8700), (-73.9200, 40.8500),
    (-73.9300, 40.8300), (-73.9350, 40.8000), (-73.9300, 40.7800),
    (-73.9500, 40.7600), (-73.9650, 40.7400), (-73.9700, 40.7200),
    (-73.9800, 40.7100), (-73.9950, 40.7050), (-74.0100, 40.7000),
    (-74.0200, 40.7000)
]
MANHATTAN_PATH = Path(MANHATTAN_POLYGON)

KEEP_COLS = [
    "tpep_pickup_datetime",
    "passenger_count",
    "pickup_longitude",
    "pickup_latitude",
    "dropoff_longitude",
    "dropoff_latitude",
]

TARGET_DATES = {
    "tuesday": ("2016-01-12 00:00:00", "2016-01-13 00:00:00"),
    "saturday": ("2016-01-16 00:00:00", "2016-01-17 00:00:00")
}

SAMPLE_RATE = 0.10  # 10% representative sample calibrated for 1,400 vehicle fleet
CHUNK_SIZE = 500_000

def within_manhattan(lons, lats):
    coords = np.column_stack((lons, lats))
    return MANHATTAN_PATH.contains_points(coords)

def expand_passengers(df):
    """Unpack multi-passenger taxi rows into 1 row per passenger with group_id."""
    df.sort_values("tpep_pickup_datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    df["passenger_count"] = (
        df["passenger_count"]
        .fillna(1)
        .astype(int)
        .clip(lower=1, upper=9)
    )
    
    expanded_rows = []
    for group_id, (_, row) in enumerate(df.iterrows()):
        n = int(row["passenger_count"])
        for _ in range(n):
            new_row = row.copy()
            new_row["group_id"] = group_id
            expanded_rows.append(new_row)
            
    expanded_df = pd.DataFrame(expanded_rows)
    expanded_df.reset_index(drop=True, inplace=True)
    return expanded_df

def extract_days():
    print("=" * 75)
    print(" 24-HOUR TRIP EXTRACTOR (TUESDAY & SATURDAY)")
    print("=" * 75)
    print(f"Reading: {INPUT_CSV}")
    print(f"Sample Rate: {SAMPLE_RATE*100:.1f}% stratified across 24 hours")
    
    tues_chunks = []
    sat_chunks = []
    
    reader = pd.read_csv(
        INPUT_CSV,
        usecols=KEEP_COLS,
        chunksize=CHUNK_SIZE
    )
    
    for i, chunk in enumerate(reader):
        chunk.dropna(subset=["pickup_longitude", "pickup_latitude",
                             "dropoff_longitude", "dropoff_latitude"], inplace=True)
        in_poly = (
            within_manhattan(chunk["pickup_longitude"].values, chunk["pickup_latitude"].values) &
            within_manhattan(chunk["dropoff_longitude"].values, chunk["dropoff_latitude"].values)
        )
        valid = chunk[in_poly].copy()
        if valid.empty:
            continue
            
        valid["tpep_pickup_datetime"] = pd.to_datetime(valid["tpep_pickup_datetime"])
        
        # Tuesday Jan 12 filter
        m_tues = (valid["tpep_pickup_datetime"] >= TARGET_DATES["tuesday"][0]) & \
                 (valid["tpep_pickup_datetime"] < TARGET_DATES["tuesday"][1])
        if m_tues.any():
            tues_chunks.append(valid[m_tues])
            
        # Saturday Jan 16 filter
        m_sat = (valid["tpep_pickup_datetime"] >= TARGET_DATES["saturday"][0]) & \
                (valid["tpep_pickup_datetime"] < TARGET_DATES["saturday"][1])
        if m_sat.any():
            sat_chunks.append(valid[m_sat])
            
        sys.stdout.write(f"\rProcessed chunk {i+1} | Tues valid: {sum(len(c) for c in tues_chunks):,} | Sat valid: {sum(len(c) for c in sat_chunks):,}")
        sys.stdout.flush()
        
    print("\n\nAll raw chunks processed. Applying stratified sampling & expanding passengers...")
    
    for day_name, raw_chunks in [("tuesday_2016-01-12", tues_chunks), ("saturday_2016-01-16", sat_chunks)]:
        day_df = pd.concat(raw_chunks, ignore_index=True)
        print(f"\n--- Processing {day_name} ---")
        print(f"  Total 100% Manhattan Taxi Trips: {len(day_df):,}")
        
        # Stratified sampling across 30-min windows
        day_df["time_bin"] = (day_df["tpep_pickup_datetime"].dt.hour * 2 + day_df["tpep_pickup_datetime"].dt.minute // 30)
        sampled_df = (
            day_df.groupby("time_bin", group_keys=False)
            .apply(lambda x: x.sample(frac=SAMPLE_RATE, random_state=42))
        )
        if "time_bin" in sampled_df.columns:
            sampled_df.drop(columns=["time_bin"], inplace=True)
        print(f"  Sampled Taxi Trips (10%): {len(sampled_df):,}")
        
        expanded_df = expand_passengers(sampled_df)
        print(f"  Expanded Passenger Requests: {len(expanded_df):,}")
        
        out_csv = os.path.join(OUTPUT_DIR, f"filtered_trips_{day_name}.csv")
        out_cols = KEEP_COLS + ["group_id"]
        expanded_df[out_cols].to_csv(out_csv, index=False)
        print(f"  Saved -> {out_csv}")
        
    print("\nExtraction complete!")

if __name__ == "__main__":
    extract_days()
