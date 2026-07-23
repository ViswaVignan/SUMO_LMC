import urllib.request
import json

url = "https://nominatim.openstreetmap.org/search.php?q=Manhattan,+New+York&polygon_geojson=1&format=json"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())

for result in data:
    if result['osm_type'] == 'relation':
        geojson = result['geojson']
        if geojson['type'] == 'Polygon':
            coords = geojson['coordinates'][0]
        elif geojson['type'] == 'MultiPolygon':
            # Usually the largest polygon is the main island
            largest = max(geojson['coordinates'], key=lambda poly: len(poly[0]))
            coords = largest[0]
            
        poly_str = ",".join([f"{lon},{lat}" for lon, lat in coords])
        with open('manhattan_poly.txt', 'w') as f:
            f.write(poly_str)
        print("Successfully fetched Manhattan polygon!")
        break
