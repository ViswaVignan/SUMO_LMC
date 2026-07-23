import csv

valid_pickups = 0
manhattan_pickups = 0
jfk_pickups = 0
lga_pickups = 0
other_pickups = 0
total_rows = 0

nyc_bounds = {
    'min_lon': -74.2591,
    'max_lon': -73.7004,
    'min_lat': 40.4957,
    'max_lat': 40.9153
}

print("Reading CSV...")
with open('yellow_tripdata_2016-01.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        total_rows += 1
        try:
            lon = float(row['pickup_longitude'])
            lat = float(row['pickup_latitude'])
            
            if (nyc_bounds['min_lon'] <= lon <= nyc_bounds['max_lon'] and 
                nyc_bounds['min_lat'] <= lat <= nyc_bounds['max_lat']):
                valid_pickups += 1
                
                # Check Manhattan
                if -74.02 <= lon <= -73.93 and 40.70 <= lat <= 40.83:
                    manhattan_pickups += 1
                # Check JFK
                elif -73.82 <= lon <= -73.77 and 40.63 <= lat <= 40.66:
                    jfk_pickups += 1
                # Check LGA
                elif -73.89 <= lon <= -73.85 and 40.76 <= lat <= 40.78:
                    lga_pickups += 1
                else:
                    other_pickups += 1
        except (ValueError, KeyError, TypeError):
            continue
            
print(f"Total rows: {total_rows}")
print(f"Valid NYC pickups: {valid_pickups}")
if valid_pickups > 0:
    print(f"Manhattan: {manhattan_pickups} ({manhattan_pickups/valid_pickups*100:.2f}%)")
    print(f"JFK Airport: {jfk_pickups} ({jfk_pickups/valid_pickups*100:.2f}%)")
    print(f"LaGuardia Airport: {lga_pickups} ({lga_pickups/valid_pickups*100:.2f}%)")
    print(f"Other Areas (Brooklyn, Queens, Bronx, Staten Island): {other_pickups} ({other_pickups/valid_pickups*100:.2f}%)")
