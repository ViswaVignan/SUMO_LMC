"""
file0.py — Data Extraction & Filtering for Last Mile Assignment Model
======================================================================
Reads the raw 2016 NYC Yellow Taxi CSV in memory-safe chunks, applies
a Manhattan bounding-box filter (pickup AND dropoff must be inside),
then extracts a clean 1-hour window centred on the median pickup time.

Calculates the peak concurrent fleet size and prints it to the terminal.
Output: filtered_2hr_trips.csv  (5 columns, sorted chronologically)
"""

import pandas as pd

# ── Configuration ────────────────────────────────────────────────────
INPUT_CSV      = "yellow_tripdata_2016-01.csv"   # path to the raw Kaggle file
OUTPUT_CSV     = "filtered_2hr_trips.csv"        # Kept original name so downstream scripts don't break
CHUNK_SIZE     = 200_000                          # rows per chunk (RAM-safe)

# Manhattan 5 km x 5 km bounding box
LAT_MIN, LAT_MAX =  40.7000,  40.7550
LON_MIN, LON_MAX = -74.0200, -73.9700

# Columns needed for memory (includes dropoff time for fleet calculation)
LOAD_COLS = [
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "pickup_longitude",
    "pickup_latitude",
    "dropoff_longitude",
    "dropoff_latitude",
]

# Columns needed for the final saved file (keeps your output format unchanged)
SAVE_COLS = [
    "tpep_pickup_datetime",
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
    and dropoff coordinates are inside the bounding box.
    """
    filtered_chunks = []

    reader = pd.read_csv(
        csv_path,
        usecols=LOAD_COLS,
        parse_dates=["tpep_pickup_datetime", "tpep_dropoff_datetime"], 
        chunksize=CHUNK_SIZE,
    )

    for i, chunk in enumerate(reader):
        chunk.dropna(
            subset=["pickup_longitude", "pickup_latitude",
                    "dropoff_longitude", "dropoff_latitude"],
            inplace=True,
        )

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
    Finds the median pickup time, then returns a strictly 1-hour 
    window -> [median - 30 mins, median + 30 mins).
    """
    median_time = df["tpep_pickup_datetime"].median()
    window_start = median_time - pd.Timedelta(minutes=30)
    window_end   = median_time + pd.Timedelta(minutes=30)

    print(f"\nMedian pickup time : {median_time}")
    print(f"1-hour window      : {window_start}  ->  {window_end}")

    mask = df["tpep_pickup_datetime"].between(window_start, window_end,
                                              inclusive="left")
    return df[mask].copy()


# ── Phase 3: Baseline Fleet Calculation ──────────────────────────────

def calculate_baseline_fleet(df):
    """Calculates the maximum number of concurrent taxis needed."""
    print("\n=== Calculating Baseline Fleet Size ===")
    
    # Every pickup means 1 taxi is busy
    pickups = pd.DataFrame({'time': df['tpep_pickup_datetime'], 'change': 1})
    # Every dropoff means 1 taxi is free
    dropoffs = pd.DataFrame({'time': df['tpep_dropoff_datetime'], 'change': -1})
    
    # Combine, sort chronologically, and calculate running total
    events = pd.concat([pickups, dropoffs]).sort_values('time')
    events['active_taxis'] = events['change'].cumsum()
    
    baseline_fleet = events['active_taxis'].max()
    
    print(f"Peak concurrent trips (Baseline Fleet Size 'X'): {baseline_fleet}")
    return baseline_fleet


# ── Phase 4: Sort and save ────────────────────────────────────────────

def save_output(df, output_path):
    """Sorts chronologically and writes the final CSV with original columns."""
    df.sort_values("tpep_pickup_datetime", inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # Only save the 5 original columns so the output file format doesn't change
    df[SAVE_COLS].to_csv(output_path, index=False)
    print(f"\nSaved {len(df):,} trips  ->  {output_path}")


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Phase 1: Spatial filtering (chunk-by-chunk) ===")
    spatial_df = load_and_filter_spatial(INPUT_CSV)
    print(f"\nTotal rows after spatial filter: {len(spatial_df):,}")

    print("\n=== Phase 2: Extracting 1-hour window ===")
    windowed_df = extract_one_hour_window(spatial_df)
    print(f"Rows in 1-hour window          : {len(windowed_df):,}")
    
    # Calculate exactly how many vehicles are needed for Scenario 1 & 2
    baseline_vehicles = calculate_baseline_fleet(windowed_df)

    print("\n=== Phase 3: Saving output ===")
    save_output(windowed_df, OUTPUT_CSV)
