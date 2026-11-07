#!/usr/bin/env python3
"""
visualize_soft_routes.py — Launch the Interactive Manhattan Soft Routes Visualizer
"""
import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PATH = os.path.join(SCRIPT_DIR, "visualizer", "server.py")
PYTHON_BIN = os.path.abspath(os.path.join(SCRIPT_DIR, "../../.venv/bin/python"))

if not os.path.exists(PYTHON_BIN):
    PYTHON_BIN = sys.executable

cmd = [PYTHON_BIN, SERVER_PATH] + sys.argv[1:]
sys.exit(subprocess.call(cmd))
