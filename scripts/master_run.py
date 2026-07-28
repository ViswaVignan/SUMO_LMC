#!/usr/bin/env python3
"""
master_run.py — Master Execution Pipeline for Multi-Day Simulation
==================================================================
This master script orchestrates the entire simulation pipeline across all files
in `data/Trips_data` or a custom selection without requiring ANY modifications
to file1.py or file2.py.

Architecture & Modes:
  1. Auto-Scan Mode (`USE_CUSTOM_CONFIG = False`):
     - Automatically scans `data/Trips_data` and runs EVERY .csv file found there.
     - Generates a corresponding simulation_state.json for each file in
       `data/Simulation_state` sequentially (once per day) to prevent cumulative RAM buildup.
     - Once the JSON states are created, runs file2.py instances in parallel with RAM Guard.
  2. Custom Config Mode (`USE_CUSTOM_CONFIG = True`):
     - Runs ONLY the specific files listed in `CUSTOM_SIMULATION_RUNS` where
       `"include": True`.
  3. Zero Modifications to file1.py & file2.py:
     - Dynamically overrides file1.INPUT_CSV, file1.OUTPUT_JSON, and
       file2.STATE_FILE in process memory. The script files on disk remain
       100% unchanged.
"""

import os
import sys
import time
import importlib
import multiprocessing as mp
from datetime import datetime
from typing import List, Dict, Any, Tuple

# ── Dynamic Repository Path Resolution ────────────────────────────────────────
REPO_ROOT       = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRIPS_DATA_DIR  = os.path.join(REPO_ROOT, "data", "Trips_data")
STATES_DATA_DIR = os.path.join(REPO_ROOT, "data", "Simulation_state")

os.makedirs(STATES_DATA_DIR, exist_ok=True)

# Add scripts directory to Python path so file1 and file2 can be imported cleanly
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ==============================================================================
# §0  RUN CONFIGURATION & MODE SELECTION
# ==============================================================================
# USE_CUSTOM_CONFIG:
#   • If False -> Automatically scans data/Trips_data and runs EVERY .csv file
#                 found there, generating JSONs in data/Simulation_state and
#                 running file2.py for each scenario.
#   • If True  -> Runs ONLY the files listed in CUSTOM_SIMULATION_RUNS where
#                 "include" is set to True.
# ==============================================================================

USE_CUSTOM_CONFIG = False

CUSTOM_SIMULATION_RUNS: List[Dict[str, Any]] = [
    {
        "name":       "Tuesday_Jan05",
        "trip_csv":   "filtered_trips_2016-01-05_tuesday.csv",
        "state_json": "simulation_state_2016-01-05_tuesday.json",
        "include":    True,
    },
]

# Maximum CPU cores allowed for parallel simulation_state.json generation
MAX_CORES_FOR_JSON_GEN = 10

# ── Memory Safety Thresholds & Concurrency Tuning ─────────────────────────────
# Prevents RAM exhaustion and OOM eviction on machines with limited RAM
MIN_FREE_RAM_GB       = 3.0   # Minimum free RAM (in GB) required before pausing
MIN_FREE_RAM_PERCENT  = 15.0  # Minimum free RAM percentage required
RAM_CHECK_INTERVAL    = 5.0   # Seconds to wait between RAM checks while paused
EST_RAM_PER_WORKER_GB = 2.5   # Estimated RAM consumed per file1.py worker process


# ==============================================================================
# §0.5  RAM MONITORING & PROCESS GUARD UTILITIES
# ==============================================================================

def get_ram_status() -> Tuple[float, float]:
    """
    Returns (available_gb, available_percent) using /proc/meminfo or psutil.
    Zero external dependencies required on Linux.
    """
    try:
        import psutil
        mem = psutil.virtual_memory()
        return mem.available / (1024**3), (mem.available / mem.total) * 100.0
    except ImportError:
        pass

    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = int(parts[1].split()[0])
        total_kb = meminfo.get("MemTotal", 1)
        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        avail_gb = avail_kb / (1024**2)
        avail_pct = (avail_kb / total_kb) * 100.0
        return avail_gb, avail_pct
    except Exception:
        # Fallback if OS inspection fails
        return 99.0, 99.0


def is_ram_safe(min_gb: float = MIN_FREE_RAM_GB, min_pct: float = MIN_FREE_RAM_PERCENT) -> bool:
    """Checks whether available RAM meets both GB and percentage safety thresholds."""
    avail_gb, avail_pct = get_ram_status()
    return avail_gb >= min_gb and avail_pct >= min_pct


def wait_for_safe_ram(context: str = "Pipeline") -> None:
    """
    Blocks and safely pauses execution if available RAM drops below critical thresholds.
    Resumes automatically once RAM becomes available.
    """
    avail_gb, avail_pct = get_ram_status()
    if avail_gb < MIN_FREE_RAM_GB or avail_pct < MIN_FREE_RAM_PERCENT:
        print(f"\n[RAM GUARD] ⚠️  Low RAM detected ({avail_gb:.2f} GB / {avail_pct:.1f}% available) at [{context}].")
        print(f"[RAM GUARD]     Pausing current process safely until available RAM >= {MIN_FREE_RAM_GB} GB ({MIN_FREE_RAM_PERCENT}%)...")
        while True:
            time.sleep(RAM_CHECK_INTERVAL)
            avail_gb, avail_pct = get_ram_status()
            if avail_gb >= MIN_FREE_RAM_GB and avail_pct >= MIN_FREE_RAM_PERCENT:
                print(f"[RAM GUARD] ✓ RAM recovered ({avail_gb:.2f} GB / {avail_pct:.1f}% available). Resuming [{context}]...")
                break


def run_process_with_ram_guard(target_fn, args: Tuple, task_name: str) -> int:
    """
    Launches a target function in a child process and monitors system RAM while it runs.
    If RAM drops below critical thresholds, it safely suspends the child process (SIGSTOP)
    and automatically resumes it (SIGCONT) when sufficient RAM is available.
    Returns the process exitcode.
    """
    import signal
    proc = mp.Process(target=target_fn, args=args)
    proc.start()

    is_suspended = False
    while proc.is_alive():
        avail_gb, avail_pct = get_ram_status()

        if not is_suspended:
            if avail_gb < MIN_FREE_RAM_GB or avail_pct < MIN_FREE_RAM_PERCENT:
                print(f"\n[RAM GUARD] ⚠️  CRITICAL RAM PRESSURE ({avail_gb:.2f} GB / {avail_pct:.1f}% available).")
                print(f"[RAM GUARD]     Suspending PID {proc.pid} ({task_name}) safely via SIGSTOP...")
                try:
                    os.kill(proc.pid, signal.SIGSTOP)
                    is_suspended = True
                except ProcessLookupError:
                    break
        else:
            # Hysteresis buffer (+0.5 GB / +3.0%) to prevent rapid pause/resume oscillations
            if avail_gb >= MIN_FREE_RAM_GB + 0.5 and avail_pct >= MIN_FREE_RAM_PERCENT + 3.0:
                print(f"\n[RAM GUARD] ✓ RAM recovered ({avail_gb:.2f} GB / {avail_pct:.1f}% available).")
                print(f"[RAM GUARD]     Resuming PID {proc.pid} ({task_name}) via SIGCONT...")
                try:
                    os.kill(proc.pid, signal.SIGCONT)
                    is_suspended = False
                except ProcessLookupError:
                    break

        time.sleep(2.0)

    proc.join()
    return proc.exitcode or 0


def get_active_runs() -> List[Dict[str, Any]]:
    """
    Returns the list of simulation runs to execute.
    
    If USE_CUSTOM_CONFIG is True:
        Returns only items in CUSTOM_SIMULATION_RUNS where "include" is True.
    Else:
        Scans data/Trips_data for all .csv files and automatically generates
        run configs mapping each .csv to a corresponding simulation_state.json
        in data/Simulation_state.
    """
    if USE_CUSTOM_CONFIG:
        return [r for r in CUSTOM_SIMULATION_RUNS if r.get("include", False)]
    
    runs = []
    if not os.path.exists(TRIPS_DATA_DIR):
        print(f"[WARN] Trips directory not found: {TRIPS_DATA_DIR}")
        return []
        
    for fname in sorted(os.listdir(TRIPS_DATA_DIR)):
        if fname.endswith(".csv") and not fname.startswith("."):
            base_name = os.path.splitext(fname)[0]
            # Strip common prefix if present for clean display name
            display_name = base_name.replace("filtered_trips_", "")
            state_json_name = f"simulation_state_{display_name}.json"
            runs.append({
                "name":       display_name,
                "trip_csv":   fname,
                "state_json": state_json_name,
                "include":    True
            })
    return runs


# ==============================================================================
# §1  PARALLEL WORKER: SIMULATION STATE JSON GENERATION (file1.py)
# ==============================================================================

def _worker_generate_json(task: Tuple[str, str, str]) -> Dict[str, Any]:
    """
    Worker function running in a separate multiprocessing process.
    Imports file1.py, overrides INPUT_CSV and OUTPUT_JSON in memory, and
    generates the simulation state JSON file without modifying file1.py on disk.
    Includes RAM safety checks before loading network & processing trips.
    """
    run_name, input_csv_path, output_json_path = task
    start_time = time.time()

    print(f"[{run_name}] Starting JSON generation -> {os.path.basename(output_json_path)} ...")

    if not os.path.exists(input_csv_path):
        return {
            "run_name": run_name,
            "status": "FAILED",
            "error": f"Input CSV file not found: {input_csv_path}",
            "elapsed_sec": time.time() - start_time
        }

    try:
        import file1
        importlib.reload(file1)  # Ensure a clean module namespace

        # Dynamically override I/O paths in memory (file1.py on disk is untouched!)
        file1.INPUT_CSV   = input_csv_path
        file1.OUTPUT_JSON = output_json_path

        wait_for_safe_ram(f"JSON Gen [{run_name}]: before load_network")
        # Execute file1 pipeline
        net, node_coords = file1.load_network(file1.SUMO_NET_XML)
        adj_walk, adj_drive = file1.build_adjacencies(net, node_coords)
        scc_nodes = file1.compute_drive_scc(net)

        wait_for_safe_ram(f"JSON Gen [{run_name}]: before process_passengers")
        passengers = file1.process_passengers(
            file1.INPUT_CSV, net, node_coords, adj_walk, adj_drive, scc_nodes
        )
        vehicles = file1.build_vehicle_fleet(
            net, node_coords, adj_drive, scc_nodes
        )
        file1.write_json(passengers, vehicles, file1.OUTPUT_JSON)

        elapsed = time.time() - start_time
        print(f"[{run_name}] ✓ JSON generated successfully ({len(passengers):,} passengers, "
              f"{len(vehicles):,} vehicles) in {elapsed:.1f}s")

        return {
            "run_name": run_name,
            "status": "SUCCESS",
            "output_json": output_json_path,
            "passengers": len(passengers),
            "vehicles": len(vehicles),
            "elapsed_sec": elapsed
        }

    except Exception as exc:
        import traceback
        err_msg = traceback.format_exc()
        print(f"[{run_name}] ✗ ERROR during JSON generation:\n{err_msg}")
        return {
            "run_name": run_name,
            "status": "FAILED",
            "error": str(exc),
            "elapsed_sec": time.time() - start_time
        }


# ==============================================================================
# §2  SEQUENTIAL WORKER: TRACI SIMULATION EXECUTION (file2.py)
# ==============================================================================

def _worker_run_traci(state_json_path: str, run_name: str) -> None:
    """
    Runs file2.py in a separate child process for isolation.
    Dynamically overrides file2.STATE_FILE and customizes trace/summary/log output
    filenames so each day's simulation results are preserved independently.
    """
    import file2
    importlib.reload(file2)  # Clean namespace

    # Override STATE_FILE in memory (file2.py on disk is untouched!)
    file2.STATE_FILE = state_json_path

    # Customise trace, summary, and log output files for this specific run
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{run_name}"
    file2.TRACE_XML_FILE  = os.path.join(file2.RESULTS_TRACE_DIR,    f"trace_{stamp}.xml")
    file2.SUMMARY_MD_FILE = os.path.join(file2.RESULTS_ANALYSIS_DIR, f"summary_{stamp}.md")
    
    log_filename = os.path.join(file2.RESULTS_LOGS_DIR, f"simulation_logs_{stamp}.txt")
    log_fh = open(log_filename, "w", encoding="utf-8")
    file2._log_file = log_fh

    print(f"\n[{run_name}] Launching TraCI simulation engine...")
    print(f"[{run_name}]   Input State   : {os.path.basename(state_json_path)}")
    print(f"[{run_name}]   Output Trace  : {os.path.basename(file2.TRACE_XML_FILE)}")
    print(f"[{run_name}]   Output Summary: {os.path.basename(file2.SUMMARY_MD_FILE)}")
    print(f"[{run_name}]   Output Logs   : {os.path.basename(log_filename)}")

    try:
        # Execute file2 main simulation loop
        file2.main()
    finally:
        log_fh.close()


# ==============================================================================
# §3  MASTER PIPELINE ORCHESTRATOR
# ==============================================================================

def run_pipeline() -> None:
    print("=" * 76)
    print("  master_run.py — Multi-Day Simulation Pipeline Orchestrator")
    print("=" * 76)

    active_runs = get_active_runs()
    if not active_runs:
        print("\n[WARN] No simulation runs found or selected.")
        if USE_CUSTOM_CONFIG:
            print("       Please set 'include': True for at least one run in CUSTOM_SIMULATION_RUNS.")
        else:
            print(f"       Please check that CSV files exist in {TRIPS_DATA_DIR}.")
        return

    mode_str = "Custom Config Mode" if USE_CUSTOM_CONFIG else "Auto-Scan Mode (data/Trips_data)"
    print(f"\n[CONFIG] Operating in {mode_str}")
    print(f"[CONFIG] Selected {len(active_runs)} run(s) for execution:")
    for r in active_runs:
        print(f"  • {r['name']} -> CSV: {r['trip_csv']} | JSON: {r['state_json']}")

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 1: Sequential Simulation State JSON Generation (file1.py - Once per Day)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("  PHASE 1: Sequential Simulation State JSON Generation (file1.py)")
    print("  Note: Executing once per day sequentially to prevent cumulative RAM buildup.")
    print("=" * 76)

    avail_gb, avail_pct = get_ram_status()
    print(f"  System RAM Available : {avail_gb:.2f} GB ({avail_pct:.1f}% free)")

    tasks = []
    for r in active_runs:
        csv_path  = os.path.join(TRIPS_DATA_DIR, r["trip_csv"])
        json_path = os.path.join(STATES_DATA_DIR, r["state_json"])
        tasks.append((r["name"], csv_path, json_path))

    json_results = []
    for run_name, csv_path, json_path in tasks:
        wait_for_safe_ram(f"Phase 1 JSON Gen -> {run_name}")
        avail_before, _ = get_ram_status()
        print(f"\n[{run_name}] Launching JSON generation (RAM free: {avail_before:.2f} GB)...")
        # Using a 1-process pool ensures 100% of memory is released back to Linux after each day
        with mp.Pool(processes=1) as pool:
            res = pool.map(_worker_generate_json, [(run_name, csv_path, json_path)])[0]
        avail_after, _ = get_ram_status()
        print(f"[{run_name}] Finished (RAM free after cleanup: {avail_after:.2f} GB)")
        json_results.append(res)

    print("\n  --- Phase 1 Summary ---")
    failed_runs = []
    successful_runs = []
    for res in json_results:
        if res["status"] == "SUCCESS":
            print(f"  ✓ [{res['run_name']}] {os.path.basename(res['output_json'])} "
                  f"({res['passengers']:,} pax, {res['vehicles']:,} veh) -> {res['elapsed_sec']:.1f}s")
            successful_runs.append(res["run_name"])
        else:
            print(f"  ✗ [{res['run_name']}] FAILED: {res.get('error', 'Unknown Error')}")
            failed_runs.append(res["run_name"])

    if not successful_runs:
        print("\n[ERROR] All JSON generation tasks failed. Aborting Phase 2.")
        return

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 2: Parallel TraCI Simulation Execution (file2.py)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("  PHASE 2: Parallel TraCI Simulation Execution (file2.py)")
    print("  Note: Running TraCI simulations in parallel across separate OS processes.")
    print("=" * 76)

    import signal
    procs = []
    for r in active_runs:
        run_name = r["name"]
        if run_name not in successful_runs:
            print(f"\n[{run_name}] Skipping Phase 2 because JSON generation failed.")
            continue

        state_json_path = os.path.join(STATES_DATA_DIR, r["state_json"])
        proc = mp.Process(target=_worker_run_traci, args=(state_json_path, run_name))
        procs.append((run_name, proc))

    print(f"\n  Launching {len(procs)} TraCI simulation instance(s) in PARALLEL...")
    for run_name, proc in procs:
        wait_for_safe_ram(f"Phase 2 Launch -> {run_name}")
        proc.start()
        print(f"  [PARALLEL LAUNCH] PID {proc.pid} -> {run_name}")
        time.sleep(1.0)  # Slight stagger to prevent simultaneous I/O spikes

    # Monitor system RAM while parallel simulations run
    suspended_pids = set()
    while any(p.is_alive() for _, p in procs):
        avail_gb, avail_pct = get_ram_status()

        # Suspend if RAM drops below critical threshold
        if avail_gb < MIN_FREE_RAM_GB or avail_pct < MIN_FREE_RAM_PERCENT:
            print(f"\n[RAM GUARD] ⚠️  CRITICAL RAM PRESSURE ({avail_gb:.2f} GB / {avail_pct:.1f}% available).")
            for run_name, p in procs:
                if p.is_alive() and p.pid not in suspended_pids:
                    print(f"[RAM GUARD]     Suspending PID {p.pid} ({run_name}) safely via SIGSTOP...")
                    try:
                        os.kill(p.pid, signal.SIGSTOP)
                        suspended_pids.add(p.pid)
                    except ProcessLookupError:
                        pass
        # Resume if RAM recovers with hysteresis
        elif suspended_pids and avail_gb >= MIN_FREE_RAM_GB + 0.5 and avail_pct >= MIN_FREE_RAM_PERCENT + 3.0:
            print(f"\n[RAM GUARD] ✓ RAM recovered ({avail_gb:.2f} GB / {avail_pct:.1f}% available).")
            for run_name, p in procs:
                if p.pid in suspended_pids:
                    print(f"[RAM GUARD]     Resuming PID {p.pid} ({run_name}) via SIGCONT...")
                    try:
                        os.kill(p.pid, signal.SIGCONT)
                    except ProcessLookupError:
                        pass
            suspended_pids.clear()

        time.sleep(2.0)

    print("\n  --- Phase 2 Summary ---")
    for run_name, proc in procs:
        proc.join()
        if proc.exitcode == 0:
            print(f"  ✓ [{run_name}] Simulation completed successfully (PID {proc.pid}).")
        else:
            print(f"  ✗ [{run_name}] Simulation exited with code {proc.exitcode} (PID {proc.pid}).")

    print("\n" + "=" * 76)
    print("✓ Master Pipeline execution finished.")
    print("=" * 76)


if __name__ == "__main__":
    run_pipeline()
