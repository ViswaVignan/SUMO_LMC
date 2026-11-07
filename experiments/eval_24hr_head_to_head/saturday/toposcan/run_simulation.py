#!/usr/bin/env python3
import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "../../tools/run_ridesharing_24hr_engine.py"))

STATE_FILE = os.path.join(SCRIPT_DIR, "simulation_state_toposcan.json")
ROUTES_FILE = os.path.join(SCRIPT_DIR, "dynamic_soft_routes_toposcan.json")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")

cmd = [
    sys.executable, "-u", ENGINE_PATH,
    "--state-file", STATE_FILE,
    "--soft-routes-file", ROUTES_FILE,
    "--results-dir", RESULTS_DIR,
    "--prefix", "toposcan",
    "--day", "Saturday",
] + sys.argv[1:]

sys.exit(subprocess.call(cmd))
