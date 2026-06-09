"""
file0.py — Monthly Data Extraction & Per-Day Splitting
=======================================================
Reads the raw 2016 NYC Yellow Taxi CSV in memory-safe chunks, applies
a Manhattan bounding-box filter (pickup AND dropoff must be inside),
then splits the data into one CSV per calendar day.

Output: day_data/day_01.csv, day_data/day_02.csv, …, day_data/day_31.csv
        Each file contains the full 24 hours of that day, sorted
        chronologically, with passengers expanded (one row per person).

Can also be imported and called for a specific day number:
    from file0 import generate_day_data
    generate_day_data(day=5)   # produces day_data/day_05.csv
"""

import os
import pandas as pd

# ── Configuration ────────────────────────────────────────────────────
INPUT_CSV      = "yellow_tripdata_2016-01.csv"   # path to the raw Kaggle file
OUTPUT_DIR     = "day_data"                       # per-day CSVs go here
CHUNK_SIZE     = 200_000                          # rows per chunk (RAM-safe)

# Manhattan 5 km x 5 km bounding box
LAT_MIN, LAT_MAX =  40.7000,  40.7550
LON_MIN, LON_MAX = -74.0200, -73.9700

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
    Returns a boolean mask: True when (lon, lat) lies inside the bounding box.
    Automatically drops NaN coordinates (treated as outside).
    """
    return (
        df[lon_col].between(LON_MIN, LON_MAX) &
        df[lat_col].between(LAT_MIN, LAT_MAX)
    )


def load_and_filter_spatial(csv_path):
    """
    Streams the raw CSV in chunks, keeps only rows where BOTH the pickup
    and dropoff coordinates are inside the bounding box, and returns a
    single concatenated DataFrame with just the relevant columns.
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


# ── Phase 2: Split by calendar day ───────────────────────────────────

def split_by_day(df):
    """
    Groups the spatially-filtered DataFrame by calendar date (day of month).
    Returns a dict  {day_number: DataFrame}  e.g. {1: df_jan1, 2: df_jan2, …}.
    """
    df["day"] = df["tpep_pickup_datetime"].dt.day
    day_groups = {}
    for day_num, group_df in df.groupby("day"):
        day_groups[int(day_num)] = group_df.drop(columns=["day"]).copy()
    return day_groups


# ── Phase 3: Expand & save one day ───────────────────────────────────

def save_day_csv(df, output_path):
    """
    Sorts chronologically, expands multi-passenger trips into one row per
    individual passenger, assigns a group_id to link passengers from the
    same original trip, then writes the CSV.
    """
    df = df.sort_values("tpep_pickup_datetime").reset_index(drop=True)

    # Sanitise passenger_count
    df["passenger_count"] = (
        df["passenger_count"]
        .fillna(1)
        .astype(int)
        .clip(lower=1, upper=9)
    )

    # Expand rows: one row per individual passenger
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
    print(f"    Original trips       : {original_trips:,}")
    print(f"    Multi-passenger trips: {multi:,}")
    print(f"    Total passengers     : {total_passengers:,}  "
          f"(expanded from {original_trips:,} trips)")
    print(f"    Saved -> {output_path}")
    return total_passengers


def generate_day_data(day, spatial_df=None):
    """
    Convenience function: generate a single day's CSV.
    If spatial_df is not provided, re-loads from the raw CSV (slower).
    Returns the output file path.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if spatial_df is None:
        print(f"=== Loading and filtering raw CSV for day {day} ===")
        spatial_df = load_and_filter_spatial(INPUT_CSV)
    day_groups = split_by_day(spatial_df)
    if day not in day_groups:
        raise ValueError(f"Day {day} not found in dataset. "
                         f"Available days: {sorted(day_groups.keys())}")
    out_path = os.path.join(OUTPUT_DIR, f"day_{day:02d}.csv")
    print(f"\n  Day {day:02d}:")
    save_day_csv(day_groups[day], out_path)
    return out_path


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 72)
    print("  file0.py — Monthly Data Extraction & Per-Day Splitting")
    print("=" * 72)

    print("\n=== Phase 1: Spatial filtering (chunk-by-chunk) ===")
    spatial_df = load_and_filter_spatial(INPUT_CSV)
    print(f"\nTotal rows after spatial filter: {len(spatial_df):,}")

    print("\n=== Phase 2: Splitting by calendar day ===")
    day_groups = split_by_day(spatial_df)
    print(f"Found {len(day_groups)} distinct days: {sorted(day_groups.keys())}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n=== Phase 3: Saving per-day CSVs ===")
    grand_total = 0
    for day_num in sorted(day_groups.keys()):
        out_path = os.path.join(OUTPUT_DIR, f"day_{day_num:02d}.csv")
        print(f"\n  Day {day_num:02d}:")
        count = save_day_csv(day_groups[day_num], out_path)
        grand_total += count

    print(f"\n{'=' * 72}")
    print(f"  ✓  {len(day_groups)} per-day CSVs written to '{OUTPUT_DIR}/'")
    print(f"     Grand total: {grand_total:,} individual passengers")
    print(f"{'=' * 72}")
