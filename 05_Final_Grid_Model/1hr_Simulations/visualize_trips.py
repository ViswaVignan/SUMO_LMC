import pandas as pd
import matplotlib.pyplot as plt

# 1. Load the data from the CSV file
df = pd.read_csv('filtered_2hr_trips.csv')

# 2. Set up the plot size
plt.figure(figsize=(10, 8))

# 3. Plot pickup locations (Blue dots)
plt.scatter(df['pickup_longitude'], df['pickup_latitude'], 
            color='blue', s=2, alpha=0.5, label='Pickups')

# 4. Plot dropoff locations (Red dots)
plt.scatter(df['dropoff_longitude'], df['dropoff_latitude'], 
            color='red', s=2, alpha=0.5, label='Dropoffs')

# 5. Add titles and labels for clarity
plt.title('Taxi Pickups and Dropoffs')
plt.xlabel('Longitude')
plt.ylabel('Latitude')
plt.legend()
plt.grid(True)

# 6. Save the plot as a PNG file
plt.savefig('nyc_taxi_trips.png', dpi=300, bbox_inches='tight')

print("Plot successfully saved as nyc_taxi_trips.png!")
