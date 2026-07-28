"""
file0.py — Data Extraction & Filtering for Last Mile Assignment Model
======================================================================
Reads the raw 2016 NYC Yellow Taxi CSV in memory-safe chunks, applies
a Manhattan bounding-box filter (pickup AND dropoff must be inside),
then extracts a clean 1-hour window centred on the median pickup time.

Output: filtered_1hr_trips.csv  (5 columns, sorted chronologically)
"""

import os
import pandas as pd

# ── Dynamic Repository Path Resolution ────────────────────────────────────────
REPO_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR       = os.path.join(REPO_ROOT, "data")

# ── Configuration ────────────────────────────────────────────────────
INPUT_CSV      = os.path.join(DATA_DIR, "yellow_tripdata_2016-01.csv")   # path to the raw Kaggle file
OUTPUT_CSV     = os.path.join(DATA_DIR, "filtered_1hr_trips.csv")
CHUNK_SIZE     = 200_000                          # rows per chunk (RAM-safe)

import numpy as np
from matplotlib.path import Path

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

# ── Phase 1: Chunk-based spatial filtering ───────────────────────────

def _within_box(df, lon_col, lat_col):
    """
    Returns a boolean mask (pandas Series): True when (lon, lat) lies inside the strict Manhattan polygon.
    Automatically drops NaN coordinates (treated as outside).
    """
    coords = np.column_stack((df[lon_col].values, df[lat_col].values))
    mask = MANHATTAN_PATH.contains_points(coords)
    return pd.Series(mask, index=df.index)


def load_and_filter_spatial(csv_path):
    """
    Streams the raw CSV in chunks, keeps only rows where BOTH the pickup
    and dropoff coordinates are inside the bounding box, and returns a
    single concatenated DataFrame with just the 5 relevant columns.
    """
    filtered_chunks = []

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

        # Soft-route constraint: BOTH pickup AND dropoff inside the box
        in_box = (
            _within_box(chunk, "pickup_longitude",  "pickup_latitude")  &
            _within_box(chunk, "dropoff_longitude", "dropoff_latitude")
        )
        valid = chunk[in_box]

        if not valid.empty:
            filtered_chunks.append(valid)

        print(f"  chunk {i+1:>4}: {len(chunk):>7} rows read, "
              f"{in_box.sum():>5} inside bounding box")

    if not filtered_chunks:
        raise ValueError("No rows passed the spatial filter. "
                         "Check bounding-box coordinates or the input file.")

    return pd.concat(filtered_chunks, ignore_index=True)


# ── Phase 2: 1-hour window centred on median pickup time ─────────────

def extract_one_hour_window(df):
    """
    Finds the median tpep_pickup_datetime of the spatially filtered dataset,
    then returns every trip whose pickup falls within the symmetric 1-hour
    window on either side  ->  [median - 0.5 h, median + 0.5 h).
    """
    median_time = df["tpep_pickup_datetime"].median()
    window_start = median_time - pd.Timedelta(hours=0.5)
    window_end   = median_time + pd.Timedelta(hours=0.5)

    print(f"\nMedian pickup time : {median_time}")
    print(f"1-hour window      : {window_start}  ->  {window_end}")

    mask = df["tpep_pickup_datetime"].between(window_start, window_end,
                                              inclusive="left")
    return df[mask].copy()


# ── Phase 3: Sort and save ────────────────────────────────────────────

def save_output(df, output_path):
    """
    Sorts chronologically, expands multi-passenger trips into one row per
    individual passenger, assigns a group_id to link passengers from the
    same original trip, then writes the final CSV.
    """
    df.sort_values("tpep_pickup_datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── Sanitise passenger_count ──────────────────────────────────────────
    # Fill NaN / zero / negative with 1; cap absurd values at 9.
    df["passenger_count"] = (
        df["passenger_count"]
        .fillna(1)
        .astype(int)
        .clip(lower=1, upper=9)
    )

    # ── Expand rows: one row per individual passenger ─────────────────────
    # group_id identifies passengers that share the same original trip.
    expanded_rows = []
    for group_id, (_, row) in enumerate(df.iterrows()):
        n = int(row["passenger_count"])
        for sub in range(n):
            new_row = row.copy()
            new_row["group_id"] = group_id
            expanded_rows.append(new_row)

    expanded_df = pd.DataFrame(expanded_rows)
    expanded_df.reset_index(drop=True, inplace=True)

    out_cols = KEEP_COLS + ["group_id"]
    expanded_df[out_cols].to_csv(output_path, index=False)

    original_trips = len(df)
    total_passengers = len(expanded_df)
    multi = (df["passenger_count"] > 1).sum()
    print(f"\nOriginal trips       : {original_trips:,}")
    print(f"Multi-passenger trips: {multi:,}")
    print(f"Total passengers     : {total_passengers:,}  "
          f"(expanded from {original_trips:,} trips)")
    print(f"Saved -> {output_path}")


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Phase 1: Spatial filtering (chunk-by-chunk) ===")
    spatial_df = load_and_filter_spatial(INPUT_CSV)
    print(f"\nTotal rows after spatial filter: {len(spatial_df):,}")

    print("\n=== Phase 2: Extracting 1-hour window ===")
    windowed_df = extract_one_hour_window(spatial_df)
    print(f"Rows in 1-hour window          : {len(windowed_df):,}")

    print("\n=== Phase 3: Saving output ===")
    save_output(windowed_df, OUTPUT_CSV)
