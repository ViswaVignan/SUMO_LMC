"""
file0_5days.py — Data Extraction & 5-Day Daily Filtering (07:00–22:00)
======================================================================
Reads the raw 2016 NYC Yellow Taxi CSV in memory-safe chunks, applies
a Manhattan bounding-box filter (pickup AND dropoff must be inside),
and extracts trips from 07:00 to 22:00 for each day from Monday (Jan 4)
to Friday (Jan 8), 2016.

Output: 5 daily intermediate CSV files in data/
  - filtered_trips_2016-01-04_monday.csv
  - filtered_trips_2016-01-05_tuesday.csv
  - filtered_trips_2016-01-06_wednesday.csv
  - filtered_trips_2016-01-07_thursday.csv
  - filtered_trips_2016-01-08_friday.csv
"""

import os
import numpy as np
import pandas as pd
from matplotlib.path import Path

# ── Dynamic Repository Path Resolution ────────────────────────────────────────
REPO_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR       = os.path.join(REPO_ROOT, "data")
TRIPS_DATA_DIR = os.path.join(DATA_DIR, "Trips_data")
os.makedirs(TRIPS_DATA_DIR, exist_ok=True)

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_CSV  = os.path.join(DATA_DIR, "yellow_tripdata_2016-01.csv")
CHUNK_SIZE = 500_000    # memory-safe chunk size for streaming 1.7 GB CSV

# Date range for Monday Jan 4, 2016 to Friday Jan 8, 2016
DAYS_CONFIG = [
    {
        "date": "2016-01-04",
        "name": "Monday",
        "output_csv": os.path.join(TRIPS_DATA_DIR, "filtered_trips_2016-01-04_monday.csv")
    },
    {
        "date": "2016-01-05",
        "name": "Tuesday",
        "output_csv": os.path.join(TRIPS_DATA_DIR, "filtered_trips_2016-01-05_tuesday.csv")
    },
    {
        "date": "2016-01-06",
        "name": "Wednesday",
        "output_csv": os.path.join(TRIPS_DATA_DIR, "filtered_trips_2016-01-06_wednesday.csv")
    },
    {
        "date": "2016-01-07",
        "name": "Thursday",
        "output_csv": os.path.join(TRIPS_DATA_DIR, "filtered_trips_2016-01-07_thursday.csv")
    },
    {
        "date": "2016-01-08",
        "name": "Friday",
        "output_csv": os.path.join(TRIPS_DATA_DIR, "filtered_trips_2016-01-08_friday.csv")
    },
]

# Manhattan Polygon — tightly traces the Hudson, Harlem, and East Rivers
# to perfectly exclude New Jersey, The Bronx, Queens, and Brooklyn.
MANHATTAN_POLYGON = [
    (-74.0200, 40.7000), # Battery Park West
    (-74.0200, 40.7100),
    (-74.0130, 40.7200),
    (-74.0100, 40.7400),
    (-74.0000, 40.7600),
    (-73.9850, 40.7800),
    (-73.9700, 40.8000),
    (-73.9450, 40.8400),
    (-73.9300, 40.8750), # Inwood West
    (-73.9100, 40.8780), # Inwood North tip
    (-73.9100, 40.8700), # Harlem River (separating Bronx)
    (-73.9200, 40.8500),
    (-73.9300, 40.8300),
    (-73.9350, 40.8000), # Harlem River end
    (-73.9300, 40.7800), # East River (separating Queens/Brooklyn)
    (-73.9500, 40.7600),
    (-73.9650, 40.7400),
    (-73.9700, 40.7200),
    (-73.9800, 40.7100), # Corlears Hook
    (-73.9950, 40.7050), # Brooklyn Bridge
    (-74.0100, 40.7000), # Staten Island Ferry
    (-74.0200, 40.7000)  # Close polygon
]
MANHATTAN_PATH = Path(MANHATTAN_POLYGON)

# Columns we care about
KEEP_COLS = [
    "tpep_pickup_datetime",
    "passenger_count",
    "pickup_longitude",
    "pickup_latitude",
    "dropoff_longitude",
    "dropoff_latitude",
]


# ── Phase 1: Chunk-based date & spatial filtering ─────────────────────────────

def _within_box(df, lon_col, lat_col):
    """
    Returns a boolean mask (pandas Series): True when (lon, lat) lies inside the strict Manhattan polygon.
    Automatically drops NaN coordinates (treated as outside).
    """
    coords = np.column_stack((df[lon_col].values, df[lat_col].values))
    mask = MANHATTAN_PATH.contains_points(coords)
    return pd.Series(mask, index=df.index)


def load_and_filter_spatial_5days(csv_path):
    """
    Streams the raw CSV in chunks, filters first by date range (2016-01-04 to 2016-01-08 inclusive),
    and then keeps only rows where BOTH pickup and dropoff coordinates are inside the Manhattan
    bounding box. Returns a single concatenated DataFrame with valid Manhattan trips.
    """
    filtered_chunks = []
    
    start_date = pd.to_datetime("2016-01-04 00:00:00")
    end_date   = pd.to_datetime("2016-01-09 00:00:00")  # exclusive bound for Jan 8 23:59:59

    print(f"Reading '{csv_path}' in chunks of {CHUNK_SIZE:,} rows...")
    reader = pd.read_csv(
        csv_path,
        usecols=KEEP_COLS,                     # skip irrelevant columns early
        parse_dates=["tpep_pickup_datetime"],  # parse datetime in one pass
        chunksize=CHUNK_SIZE,
    )

    for i, chunk in enumerate(reader):
        # Drop rows with any missing coordinate value
        chunk.dropna(
            subset=["pickup_longitude", "pickup_latitude",
                    "dropoff_longitude", "dropoff_latitude"],
            inplace=True,
        )

        # Fast date range pre-filtering (Jan 4 to Jan 8, 2016)
        mask_date = (
            (chunk["tpep_pickup_datetime"] >= start_date) &
            (chunk["tpep_pickup_datetime"] < end_date)
        )
        chunk = chunk[mask_date]
        if chunk.empty:
            continue

        # Soft-route constraint: BOTH pickup AND dropoff inside the box
        in_box = (
            _within_box(chunk, "pickup_longitude",  "pickup_latitude")  &
            _within_box(chunk, "dropoff_longitude", "dropoff_latitude")
        )
        valid = chunk[in_box]

        if not valid.empty:
            filtered_chunks.append(valid)

        print(f"  chunk {i+1:>4}: {len(chunk):>7} date-valid rows read, "
              f"{in_box.sum():>6} inside bounding box")

    if not filtered_chunks:
        raise ValueError("No rows passed the spatial and date filter. "
                         "Check bounding-box coordinates or the input file.")

    return pd.concat(filtered_chunks, ignore_index=True)


# ── Phase 2: Daily window extraction (07:00 to 22:00) ─────────────────────────

def extract_day_window(df, date_str):
    """
    Extracts trips for a specific day from 07:00:00 to 22:00:00 (15 hours).
    Interval is [07:00:00, 22:00:00) (inclusive start, exclusive end).
    """
    window_start = pd.to_datetime(f"{date_str} 07:00:00")
    window_end   = pd.to_datetime(f"{date_str} 22:00:00")

    mask = df["tpep_pickup_datetime"].between(
        window_start, window_end, inclusive="left"
    )
    windowed_df = df[mask].copy()
    
    print(f"\n[{date_str}] Time window      : {window_start}  ->  {window_end}")
    print(f"[{date_str}] Trips in window  : {len(windowed_df):,}")
    return windowed_df


# ── Phase 3: Sort and save ────────────────────────────────────────────────────

def save_output(df, output_path, day_name):
    """
    Sorts chronologically, expands multi-passenger trips into one row per
    individual passenger, assigns a group_id to link passengers from the
    same original trip, then writes the final CSV.
    
    Uses vectorized repeating (df.index.repeat) for high performance on
    large daily trip datasets.
    """
    if df.empty:
        print(f"[{day_name}] WARNING: No trips found for this day window. Skipping save.")
        return 0, 0

    df = df.copy()
    df.sort_values("tpep_pickup_datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── Sanitise passenger_count ──────────────────────────────────────────────
    # Fill NaN / zero / negative with 1; cap absurd values at 9.
    df["passenger_count"] = (
        df["passenger_count"]
        .fillna(1)
        .astype(int)
        .clip(lower=1, upper=9)
    )

    # ── Assign group_id to link passengers from the same original trip ────────
    df["group_id"] = df.index

    # ── Expand rows: one row per individual passenger ─────────────────────────
    # Vectorized row repetition for high speed on 15-hour windows
    expanded_df = df.loc[df.index.repeat(df["passenger_count"])].copy()
    expanded_df.reset_index(drop=True, inplace=True)

    out_cols = KEEP_COLS + ["group_id"]
    expanded_df[out_cols].to_csv(output_path, index=False)

    original_trips = len(df)
    total_passengers = len(expanded_df)
    multi = (df["passenger_count"] > 1).sum()
    print(f"[{day_name}] Original trips       : {original_trips:,}")
    print(f"[{day_name}] Multi-passenger trips: {multi:,}")
    print(f"[{day_name}] Total passengers     : {total_passengers:,}  "
          f"(expanded from {original_trips:,} trips)")
    print(f"[{day_name}] Saved -> {output_path}")
    return original_trips, total_passengers


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("  file0_5days.py — 5-Day Data Extraction & Filtering (07:00–22:00)")
    print("  (Monday Jan 4 to Friday Jan 8, 2016)")
    print("=" * 70)

    print("\n=== Phase 1: Date & Spatial filtering (chunk-by-chunk) ===")
    spatial_df = load_and_filter_spatial_5days(INPUT_CSV)
    print(f"\nTotal Manhattan trips (Jan 4–8 full days): {len(spatial_df):,}")

    summary_records = []

    print("\n=== Phase 2 & 3: Extracting 07:00–22:00 windows and saving ===")
    for day_cfg in DAYS_CONFIG:
        day_date = day_cfg["date"]
        day_name = day_cfg["name"]
        out_path = day_cfg["output_csv"]

        print(f"\n--- {day_name} ({day_date}) ---")
        day_df = extract_day_window(spatial_df, day_date)
        orig_trips, tot_pass = save_output(day_df, out_path, day_name)

        summary_records.append({
            "Day": f"{day_name} ({day_date})",
            "Original Trips": orig_trips,
            "Total Passengers": tot_pass,
            "Output File": os.path.basename(out_path)
        })

    print("\n" + "=" * 70)
    print("  5-Day Extraction Summary (07:00 to 22:00 each day)")
    print("=" * 70)
    summary_df = pd.DataFrame(summary_records)
    print(summary_df.to_string(index=False))
    print("=" * 70)
    print("✓ All 5 daily intermediate CSV files have been successfully generated.")
