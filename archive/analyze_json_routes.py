import json
import os

def analyze_json():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(script_dir, "dynamic_soft_routes.json")
    
    print(f"Analyzing {json_path}...")
    print(f"File size: {os.path.getsize(json_path) / (1024*1024):.2f} MB\n")
    
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
            
        total_trunks = 0
        total_edges = 0
        bins_with_data = 0
        
        print(f"{'Time Bin':<15} | {'Corridors/Trunks Found':<25} | {'Avg Edges per Trunk':<20}")
        print("-" * 65)
        
        for bin_id in range(48):
            str_bin = str(bin_id)
            if str_bin in data:
                trunks = data[str_bin]
                num_trunks = len(trunks)
                if num_trunks > 0:
                    bins_with_data += 1
                    avg_edges = sum(len(t) for t in trunks) / num_trunks
                    print(f"Bin {bin_id:<11} | {num_trunks:<25} | {avg_edges:.1f}")
                    total_trunks += num_trunks
                    total_edges += sum(len(t) for t in trunks)
                else:
                    print(f"Bin {bin_id:<11} | {'0 (Skipped/Low Density)':<25} | N/A")
            else:
                print(f"Bin {bin_id:<11} | {'Missing from JSON':<25} | N/A")
                
        print("-" * 65)
        print(f"\nSummary:")
        print(f"- Bins populated: {bins_with_data} / 48")
        print(f"- Total dynamic corridors generated: {total_trunks}")
        if total_trunks > 0:
            print(f"- Average corridor length (edges): {total_edges / total_trunks:.1f}")
            
    except Exception as e:
        print(f"Error reading JSON: {e}")

if __name__ == "__main__":
    analyze_json()
