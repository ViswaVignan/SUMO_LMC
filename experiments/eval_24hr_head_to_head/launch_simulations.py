#!/usr/bin/env python3
"""
launch_simulations.py — Robust headless launcher for the 24-hour head-to-head simulations.
Spawns background processes using start_new_session=True so they persist cleanly.
"""
import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_BIN = os.path.abspath(os.path.join(SCRIPT_DIR, "../../.venv/bin/python"))

SIMULATIONS = {
    "tuesday_topo": {
        "dir": os.path.join(SCRIPT_DIR, "tuesday/toposcan"),
        "log": os.path.join(SCRIPT_DIR, "tuesday/toposcan/results/simulation_toposcan.log"),
    },
    "tuesday_nlp": {
        "dir": os.path.join(SCRIPT_DIR, "tuesday/nlp_gct_lm"),
        "log": os.path.join(SCRIPT_DIR, "tuesday/nlp_gct_lm/results/simulation_nlp.log"),
    },
    "saturday_topo": {
        "dir": os.path.join(SCRIPT_DIR, "saturday/toposcan"),
        "log": os.path.join(SCRIPT_DIR, "saturday/toposcan/results/simulation_toposcan.log"),
    },
    "saturday_nlp": {
        "dir": os.path.join(SCRIPT_DIR, "saturday/nlp_gct_lm"),
        "log": os.path.join(SCRIPT_DIR, "saturday/nlp_gct_lm/results/simulation_nlp.log"),
    },
}

def is_running(target_dir):
    try:
        out = subprocess.check_output(["pgrep", "-a", "-f", "run_ridesharing_24hr_engine.py"], text=True)
        for line in out.strip().split("\n"):
            if target_dir in line:
                return True
    except subprocess.CalledProcessError:
        pass
    return False

def launch_sim(name):
    cfg = SIMULATIONS[name]
    sim_dir = cfg["dir"]
    log_path = cfg["log"]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    if is_running(sim_dir):
        print(f"[-] {name} is ALREADY RUNNING.")
        return None
    
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [PYTHON_BIN, "-u", "run_simulation.py"],
        cwd=sim_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    print(f"[+] Launched {name} (PID: {proc.pid}) -> {os.path.relpath(log_path, SCRIPT_DIR)}")
    return proc.pid

if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(SIMULATIONS.keys())
    if "all" in targets:
        targets = list(SIMULATIONS.keys())
    for t in targets:
        if t in SIMULATIONS:
            launch_sim(t)
        else:
            print(f"[!] Unknown target: {t}")
