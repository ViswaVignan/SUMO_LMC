import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx
from shapely.geometry import Point

cols = ['pickup_longitude', 'pickup_latitude', 'dropoff_longitude', 'dropoff_latitude']

print("Loading data (this may take a few seconds)...")
df = pd.read_csv('yellow_tripdata_2016-01.csv', usecols=cols)

# Filter valid NYC coordinates to avoid outliers
nyc_bounds = {
    'min_lon': -74.2591,
    'max_lon': -73.7004,
    'min_lat': 40.4957,
    'max_lat': 40.9153
}

# Keep only rows where BOTH pickup and dropoff are valid
valid_trips = df[
    (df['pickup_longitude'] >= nyc_bounds['min_lon']) &
    (df['pickup_longitude'] <= nyc_bounds['max_lon']) &
    (df['pickup_latitude'] >= nyc_bounds['min_lat']) &
    (df['pickup_latitude'] <= nyc_bounds['max_lat']) &
    (df['dropoff_longitude'] >= nyc_bounds['min_lon']) &
    (df['dropoff_longitude'] <= nyc_bounds['max_lon']) &
    (df['dropoff_latitude'] >= nyc_bounds['min_lat']) &
    (df['dropoff_latitude'] <= nyc_bounds['max_lat'])
].copy()

print("Sampling data for plotting...")
# Plotting 10+ million points is too slow, so we take a representative random sample
sample_size = min(100000, len(valid_trips))
sample_df = valid_trips.sample(n=sample_size, random_state=42)

# Convert Pickups to GeoDataFrame
geometry_pickup = [Point(xy) for xy in zip(sample_df.pickup_longitude, sample_df.pickup_latitude)]
gdf_pickup = gpd.GeoDataFrame(sample_df, geometry=geometry_pickup, crs="EPSG:4326")
# Convert to Web Mercator (EPSG:3857) which is required for Contextily basemaps
gdf_pickup = gdf_pickup.to_crs(epsg=3857)

# Convert Dropoffs to GeoDataFrame
geometry_dropoff = [Point(xy) for xy in zip(sample_df.dropoff_longitude, sample_df.dropoff_latitude)]
gdf_dropoff = gpd.GeoDataFrame(sample_df, geometry=geometry_dropoff, crs="EPSG:4326")
gdf_dropoff = gdf_dropoff.to_crs(epsg=3857)

print("Generating plots...")
fig, axes = plt.subplots(2, 2, figsize=(20, 20))

# Subplot 0,0: Pickup Hexbin Density Plot
hb1 = axes[0, 0].hexbin(gdf_pickup.geometry.x, gdf_pickup.geometry.y, gridsize=100, cmap='inferno', bins='log', mincnt=1)
axes[0, 0].set_title('Taxi Pickup Density', fontsize=18)
axes[0, 0].axis('off')
fig.colorbar(hb1, ax=axes[0, 0], label='log10(N)')

# Subplot 0,1: Pickup Points overlaid on a real map
gdf_pickup.plot(ax=axes[0, 1], markersize=2, color='red', alpha=0.1)
try:
    ctx.add_basemap(axes[0, 1], source=ctx.providers.CartoDB.Positron)
except Exception as e:
    print(f"Could not load basemap: {e}")
axes[0, 1].set_title('Pickups Overlaid on NYC Map', fontsize=18)
axes[0, 1].axis('off')

# Subplot 1,0: Dropoff Hexbin Density Plot
hb2 = axes[1, 0].hexbin(gdf_dropoff.geometry.x, gdf_dropoff.geometry.y, gridsize=100, cmap='viridis', bins='log', mincnt=1)
axes[1, 0].set_title('Taxi Dropoff Density', fontsize=18)
axes[1, 0].axis('off')
fig.colorbar(hb2, ax=axes[1, 0], label='log10(N)')

# Subplot 1,1: Dropoff Points overlaid on a real map
gdf_dropoff.plot(ax=axes[1, 1], markersize=2, color='blue', alpha=0.1)
try:
    ctx.add_basemap(axes[1, 1], source=ctx.providers.CartoDB.Positron)
except Exception as e:
    print(f"Could not load basemap: {e}")
axes[1, 1].set_title('Dropoffs Overlaid on NYC Map', fontsize=18)
axes[1, 1].axis('off')

plt.tight_layout()
output_file = 'nyc_coverage_map.png'
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"Plot saved successfully to {output_file}")
