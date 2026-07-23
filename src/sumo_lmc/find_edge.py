import json

def find_edge():
    with open("simulation_state.json", "r") as f:
        data = json.load(f)
        
    for p in data.get("passengers", []):
        for k, v in p.items():
            if "1532218058" in str(v):
                print(f"Found in passenger {p['id']}, field {k}: {v}")
                
if __name__ == "__main__":
    find_edge()
