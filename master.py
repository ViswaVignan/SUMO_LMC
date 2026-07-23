import os
import sys
import subprocess
from concurrent.futures import ProcessPoolExecutor
import glob

def run_file1(day_csv, out_json):
    print(f"Running file1.py for {day_csv} -> {out_json}")
    subprocess.run([sys.executable, "file1.py", day_csv, out_json], check=True)

def run_file2(state_json, trace_xml, summary_md):
    print(f"Running file2.py for {state_json} -> {summary_md}")
    subprocess.run([sys.executable, "file2.py", state_json, trace_xml, summary_md], check=True)

def main():
    print("=========================================================")
    print("  Master Orchestrator - Monthly Parallel Simulation")
    print("=========================================================")

    # 1. Run file0.py to split into days
    print("\n=== Step 1: Running file0.py to generate day data ===")
    subprocess.run([sys.executable, "file0.py"], check=True)
    
    # Get all the generated day CSVs
    day_csvs = sorted(glob.glob("day_data/day_*.csv"))
    if not day_csvs:
        print("Error: No day data generated!")
        return

    # 2. Run file1.py for each day to generate JSONs
    print("\n=== Step 2: Running file1.py to generate state JSONs ===")
    os.makedirs("state_data", exist_ok=True)
    state_jsons = []
    
    for csv_file in day_csvs:
        base_name = os.path.basename(csv_file).replace('.csv', '')
        out_json = f"state_data/sim_state_{base_name}.json"
        run_file1(csv_file, out_json)
        state_jsons.append(out_json)

    # 3. Run file2.py in parallel (batches of 5)
    print("\n=== Step 3: Running file2.py (Simulation) 5 days at a time ===")
    os.makedirs("results", exist_ok=True)
    
    # ProcessPoolExecutor with max_workers=5 ensures that exactly 5 days 
    # run concurrently in the background. As soon as one day finishes, 
    # the next day will start automatically.
    with ProcessPoolExecutor(max_workers=5) as executor:
        futures = []
        for state_json in state_jsons:
            base_name = os.path.basename(state_json).replace('sim_state_', '').replace('.json', '')
            trace_xml = f"results/trace_{base_name}.xml"
            summary_md = f"results/summary_{base_name}.md"
            futures.append(executor.submit(run_file2, state_json, trace_xml, summary_md))
        
        # Wait for all to complete and check for errors
        for i, future in enumerate(futures):
            try:
                future.result()
                print(f"[✓] Successfully finished simulation for Day {i+1} / {len(futures)}")
            except Exception as e:
                print(f"[✗] Error running simulation for Day {i+1}: {e}")

    print("\n=========================================================")
    print("  ALL DAYS COMPLETED SUCCESSFULLY!")
    print("  Check the 'results/' folder for your output files.")
    print("=========================================================")

if __name__ == "__main__":
    main()
