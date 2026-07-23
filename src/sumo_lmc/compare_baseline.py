import pandas as pd
import numpy as np

print("Loading datasets...")
filtered_df = pd.read_csv("filtered_1hr_trips.csv")
# To speed up, we only load necessary columns from the huge CSV
cols = ['tpep_pickup_datetime', 'tpep_dropoff_datetime', 'pickup_longitude', 'pickup_latitude', 'trip_distance']
yellow_df = pd.read_csv("yellow_tripdata_2016-01.csv", usecols=cols)

print("Merging...")
# Merge on pickup_datetime and coordinates
merged_df = pd.merge(
    filtered_df, 
    yellow_df, 
    on=['tpep_pickup_datetime', 'pickup_longitude', 'pickup_latitude'], 
    how='inner'
)
# Drop duplicates in case of exact matching rides
merged_df = merged_df.drop_duplicates()

print(f"Matched {len(merged_df)} trips out of {len(filtered_df)}.")

# Calculate Travel Times
merged_df['tpep_pickup_datetime'] = pd.to_datetime(merged_df['tpep_pickup_datetime'])
merged_df['tpep_dropoff_datetime'] = pd.to_datetime(merged_df['tpep_dropoff_datetime'])
merged_df['travel_time_seconds'] = (merged_df['tpep_dropoff_datetime'] - merged_df['tpep_pickup_datetime']).dt.total_seconds()

# Clean outliers (e.g., negative times or extremely long times)
valid_trips = merged_df[(merged_df['travel_time_seconds'] > 0) & (merged_df['travel_time_seconds'] < 7200)]

avg_travel_time = valid_trips['travel_time_seconds'].mean()
median_travel_time = valid_trips['travel_time_seconds'].median()

# Trip Distance
# 1 mile = 1609.34 meters
valid_trips['trip_distance_meters'] = valid_trips['trip_distance'] * 1609.34
total_solo_vehicle_distance = valid_trips['trip_distance_meters'].sum()
avg_solo_trip_distance = valid_trips['trip_distance_meters'].mean()

print("\n--- BASELINE METRICS (SOLO TRIPS) ---")
print(f"Total Demand: {len(valid_trips)}")
print(f"Passenger Wait Time: N/A (Assumed 0 in dataset)")
print(f"Average In-Vehicle Travel Time: {avg_travel_time:.2f} seconds (Median: {median_travel_time:.2f} s)")
print(f"Total Fleet Travel Distance (Revenue Distance Only): {total_solo_vehicle_distance:,.2f} meters")
print(f"Average Trip Distance: {avg_solo_trip_distance:,.2f} meters")
print(f"Average Passenger Walk Distance: 0 meters (Door-to-door)")

