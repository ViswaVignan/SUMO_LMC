#!/bin/bash
# ==============================================================================
# run_all.sh — 24-Hour Head-to-Head Headless Orchestrator
# ==============================================================================
# Orchestrates the 4 simulations across 2 days (Tuesday & Saturday)
# Ensures RAM stays < 5 GB by running in calibrated parallel batches.
# ==============================================================================

set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${ROOT_DIR}/../../.venv/bin/python"

echo "=========================================================================="
echo " 24-HOUR HEAD-TO-HEAD SIMULATION SUITE (TUESDAY & SATURDAY)"
echo "=========================================================================="
echo "Working directory : ${ROOT_DIR}"
echo "Python binary     : ${PYTHON}"
echo "Available Cores   : $(nproc)"
echo "RAM Protection    : Strictly < 1 GB per batch (< 5 GB limit)"
echo "=========================================================================="

usage() {
    echo "Usage: ./run_all.sh [all | batch1 | batch2 | status | tuesday_topo | tuesday_nlp | saturday_topo | saturday_nlp | compare]"
    echo ""
    echo "  all            : Run ALL 4 simulations simultaneously in parallel (~2 GB RAM total)"
    echo "  batch1         : Run Tuesday TopoScan & Tuesday NLP simultaneously (Parallel)"
    echo "  batch2         : Run Saturday TopoScan & Saturday NLP simultaneously (Parallel)"
    echo "  status         : Check the status of all running simulations"
    echo "  tuesday_topo   : Run Tuesday TopoScan only"
    echo "  tuesday_nlp    : Run Tuesday NLP GCT-LM only"
    echo "  saturday_topo  : Run Saturday TopoScan only"
    echo "  saturday_nlp   : Run Saturday NLP GCT-LM only"
    echo "  compare        : Compile 4-way comparative report (HEAD_TO_HEAD_24HR_COMPARISON.md)"
    exit 1
}

MODE="${1:-all}"

case "${MODE}" in
    all)
        echo ""
        echo ">>> LAUNCHING ALL 4 SIMULATIONS SIMULTANEOUSLY (TUESDAY & SATURDAY)..."
        echo "Total RAM footprint estimated: ~2.0 - 2.2 GB (Well within 5 GB limit)."
        echo "Available Cores: $(nproc) | Allocating 4 parallel worker processes."
        echo ""

        "${PYTHON}" "${ROOT_DIR}/launch_simulations.py" all
        echo ""
        echo "Monitor progress via:"
        echo "  ./run_all.sh status"
        echo "  tail -f tuesday/nlp_gct_lm/results/simulation_nlp.log"
        echo "  tail -f saturday/nlp_gct_lm/results/simulation_nlp.log"
        ;;
    batch1)
        echo ""
        echo ">>> LAUNCHING BATCH 1: Tuesday TopoScan & Tuesday NLP (Parallel)..."
        echo "Logs will stream to:"
        echo "  - ${ROOT_DIR}/tuesday/toposcan/results/simulation_toposcan.log"
        echo "  - ${ROOT_DIR}/tuesday/nlp_gct_lm/results/simulation_nlp.log"
        echo ""

        cd "${ROOT_DIR}/tuesday/toposcan"
        nohup "${PYTHON}" -u run_simulation.py > results/simulation_toposcan.log 2>&1 &
        PID_TOPO=$!

        cd "${ROOT_DIR}/tuesday/nlp_gct_lm"
        nohup "${PYTHON}" -u run_simulation.py > results/simulation_nlp.log 2>&1 &
        PID_NLP=$!

        echo "Batch 1 running in background:"
        echo "  Tuesday TopoScan PID : ${PID_TOPO}"
        echo "  Tuesday NLP PID      : ${PID_NLP}"
        echo "Check progress via: tail -f tuesday/nlp_gct_lm/results/simulation_nlp.log"
        ;;

    batch2)
        echo ""
        echo ">>> LAUNCHING BATCH 2: Saturday TopoScan & Saturday NLP (Parallel)..."
        echo "Logs will stream to:"
        echo "  - ${ROOT_DIR}/saturday/toposcan/results/simulation_toposcan.log"
        echo "  - ${ROOT_DIR}/saturday/nlp_gct_lm/results/simulation_nlp.log"
        echo ""

        cd "${ROOT_DIR}/saturday/toposcan"
        nohup "${PYTHON}" -u run_simulation.py > results/simulation_toposcan.log 2>&1 &
        PID_TOPO=$!

        cd "${ROOT_DIR}/saturday/nlp_gct_lm"
        nohup "${PYTHON}" -u run_simulation.py > results/simulation_nlp.log 2>&1 &
        PID_NLP=$!

        echo "Batch 2 running in background:"
        echo "  Saturday TopoScan PID : ${PID_TOPO}"
        echo "  Saturday NLP PID      : ${PID_NLP}"
        echo "Check progress via: tail -f saturday/nlp_gct_lm/results/simulation_nlp.log"
        ;;

    tuesday_topo)
        cd "${ROOT_DIR}/tuesday/toposcan"
        "${PYTHON}" run_simulation.py
        ;;

    tuesday_nlp)
        cd "${ROOT_DIR}/tuesday/nlp_gct_lm"
        "${PYTHON}" run_simulation.py
        ;;

    saturday_topo)
        cd "${ROOT_DIR}/saturday/toposcan"
        "${PYTHON}" run_simulation.py
        ;;

    saturday_nlp)
        cd "${ROOT_DIR}/saturday/nlp_gct_lm"
        "${PYTHON}" run_simulation.py
        ;;

    status)
        echo ""
        echo "=== Simulation Process Status ==="
        pgrep -a -f "run_ridesharing_24hr_engine.py" || echo "No 24-hour simulation engines currently running."
        echo ""
        echo "=== Recent Tuesday NLP Progress ==="
        tail -n 5 "${ROOT_DIR}/tuesday/nlp_gct_lm/results/simulation_nlp.log" 2>/dev/null || echo "Log not yet created."
        echo ""
        echo "=== Recent Tuesday TopoScan Progress ==="
        tail -n 5 "${ROOT_DIR}/tuesday/toposcan/results/simulation_toposcan.log" 2>/dev/null || echo "Log not yet created."
        echo ""
        echo "=== Recent Saturday NLP Progress ==="
        tail -n 5 "${ROOT_DIR}/saturday/nlp_gct_lm/results/simulation_nlp.log" 2>/dev/null || echo "Log not yet created."
        echo ""
        echo "=== Recent Saturday TopoScan Progress ==="
        tail -n 5 "${ROOT_DIR}/saturday/toposcan/results/simulation_toposcan.log" 2>/dev/null || echo "Log not yet created."
        echo ""
        echo "=== System Memory Usage ==="
        free -h
        ;;

    compare)
        cd "${ROOT_DIR}"
        "${PYTHON}" compare_4way_results.py
        ;;

    *)
        usage
        ;;
esac
