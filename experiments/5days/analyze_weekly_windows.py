import os
import pandas as pd
import numpy as np
from matplotlib.path import Path
import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")

# ── Configuration ────────────────────────────────────────────────────
INPUT_CSV      = os.path.join(DATA_DIR, "yellow_tripdata_2016-01.csv")
OUTPUT_CSV     = os.path.join(os.path.dirname(__file__), "weekly_window_analysis.csv")
CHUNK_SIZE     = 500_000

# Manhattan Polygon (from file0.py)
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
    "pickup_longitude",
    "pickup_latitude",
    "dropoff_longitude",
    "dropoff_latitude",
]

def _within_box(df, lon_col, lat_col):
    coords = np.column_stack((df[lon_col].values, df[lat_col].values))
    mask = MANHATTAN_PATH.contains_points(coords)
    return pd.Series(mask, index=df.index)

def analyze_dataset():
    # Jan 4 (Mon) to Jan 10 (Sun), 2016 is the first full week
    start_date = pd.to_datetime("2016-01-04")
    end_date = pd.to_datetime("2016-01-11") # Exclusive end
    
    # Pre-generate the 47 windows (or 48 windows)
    # Windows are 1 hour long, sliding by 30 mins
    window_tuples = []
    for h in range(24):
        for m in [0, 30]:
            w_start = datetime.time(h, m)
            # end is 1 hour later
            if m == 0:
                w_end = datetime.time((h + 1) % 24, 0)
            else:
                w_end = datetime.time((h + 1) % 24, 30)
                
            window_tuples.append((w_start, w_end))

    # Initialize counts dict
    counts = {day: {w[0].strftime('%H:%M'): 0 for w in window_tuples} for day in range(7)}

    print(f"Reading {INPUT_CSV} in chunks of {CHUNK_SIZE}...")
    reader = pd.read_csv(
        INPUT_CSV,
        usecols=KEEP_COLS,
        parse_dates=["tpep_pickup_datetime"],
        chunksize=CHUNK_SIZE,
    )

    for i, chunk in enumerate(reader):
        chunk.dropna(subset=["pickup_longitude", "pickup_latitude", "dropoff_longitude", "dropoff_latitude"], inplace=True)
        
        # Filter dates first (much faster)
        mask_date = (chunk["tpep_pickup_datetime"] >= start_date) & (chunk["tpep_pickup_datetime"] < end_date)
        chunk = chunk[mask_date]
        if chunk.empty:
            continue
            
        # Spatial filter (Manhattan bounding box)
        in_box = (
            _within_box(chunk, "pickup_longitude",  "pickup_latitude")  &
            _within_box(chunk, "dropoff_longitude", "dropoff_latitude")
        )
        chunk = chunk[in_box].copy()
        if chunk.empty:
            continue
            
        # Add day of week and time
        chunk['day_of_week'] = chunk['tpep_pickup_datetime'].dt.dayofweek
        chunk['time'] = chunk['tpep_pickup_datetime'].dt.time
        
        # Count trips for each window
        for day in range(7):
            day_data = chunk[chunk['day_of_week'] == day]
            if day_data.empty: continue
            
            for w_start, w_end in window_tuples:
                w_start_str = w_start.strftime('%H:%M')
                if w_start < w_end:
                    mask = (day_data['time'] >= w_start) & (day_data['time'] < w_end)
                else:
                    # Wraps around midnight (e.g. 23:30 - 00:30)
                    mask = (day_data['time'] >= w_start) | (day_data['time'] < w_end)
                
                counts[day][w_start_str] += mask.sum()
                
        print(f"Processed chunk {i+1} - valid rows in this chunk: {len(chunk)}")

    # Convert counts to DataFrame
    records = []
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in range(7):
        for w_start, count in counts[day].items():
            records.append({
                "DayOfWeek": day,
                "DayName": day_names[day],
                "WindowStart": w_start,
                "TripCount": count
            })
            
    df_results = pd.DataFrame(records)
    df_results.to_csv(OUTPUT_CSV, index=False)
    
    # Identify Peak, Median, and Off-Peak for Weekdays (Mon-Fri) and Weekends (Sat-Sun)
    print("\n--- Summary ---")
    for day in range(7):
        day_df = df_results[df_results['DayOfWeek'] == day]
        peak = day_df.loc[day_df['TripCount'].idxmax()]
        median_val = day_df['TripCount'].median()
        # Find the window closest to median
        median_row = day_df.iloc[(day_df['TripCount'] - median_val).abs().argsort()[:1]]
        
        # Find a less demanding hour (let's say 25th percentile)
        q25_val = day_df['TripCount'].quantile(0.25)
        offpeak_row = day_df.iloc[(day_df['TripCount'] - q25_val).abs().argsort()[:1]]
        
        print(f"{day_names[day]}:")
        print(f"  Peak Hour:   {peak['WindowStart']} ({peak['TripCount']} trips)")
        print(f"  Median Hour: {median_row['WindowStart'].values[0]} ({median_row['TripCount'].values[0]} trips)")
        print(f"  Off-Peak:    {offpeak_row['WindowStart'].values[0]} ({offpeak_row['TripCount'].values[0]} trips)")

    print(f"\nAnalysis complete. Saved to {OUTPUT_CSV}")

if __name__ == "__main__":
    analyze_dataset()
