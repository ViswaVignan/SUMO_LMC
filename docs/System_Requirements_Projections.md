# Ride-Sharing Simulation: System Requirements & Scaling Projections

This document outlines the hardware requirements (RAM and Disk Storage) required to run the V3 Manhattan Game-Theoretic Ride-Sharing Simulation over extended horizons. The projections are calculated based on the empirical profiling of a 9,000-second (2.5 hour) baseline simulation, which generated a 139 MB XML trace file.

---

## 1. Storage Projections (Disk Space)
The simulation outputs a dense XML trace logging every vehicle's physical position, occupancy, and passenger logical states at 30-second macro-steps. The disk space scales strictly linearly with simulation time.

| Simulation Horizon | Projected Trace Size | Disk Requirement Assessment |
| :--- | :--- | :--- |
| **1 Hour** | ~55 MB | Trivial. |
| **24 Hours** | ~1.32 GB | Negligible. Easily handled by any standard hard drive. |
| **1 Month (30 Days)** | ~39.6 GB | Highly feasible. Any modern laptop or server with 50 GB of free space can comfortably store the full monthly dataset. |

**Conclusion on Storage:** Storage capacity is **not** a limiting factor for long-term simulation runs.

---

## 2. Memory Projections (RAM)
*This is the current architectural bottleneck.* 

The current simulation script (`file2.py`) relies on Python's native `xml.etree.ElementTree` to build the trace file. This library constructs the entire XML document as a nested dictionary-like structure in active RAM, holding it in memory for the *entire duration* of the simulation, and only writing it to the hard drive at the absolute end (`tree.write()`).

Because Python's internal XML tree objects carry significant object-oriented overhead, they typically consume **~5x the physical file size in RAM**.

| Simulation Horizon | Python XML RAM Overhead | Python Object State RAM (Passengers/Vehicles) | **Total RAM Required** | Feasibility |
| :--- | :--- | :--- | :--- | :--- |
| **1 Hour** | ~275 MB | < 10 MB | **~500 MB** (w/ SUMO) | Runs perfectly on any machine. |
| **24 Hours** | ~6.6 GB | ~50 MB | **~7.0 GB** | Runs safely on a standard 16GB RAM laptop. |
| **1 Month** | **~198 GB** | ~1.5 GB | **> 200 GB** | 💥 **CRITICAL FAILURE (OOM Crash)** |

**Conclusion on Memory:** Under the current architecture, attempting to run the simulation for a full month will inevitably result in an `Out Of Memory (OOM)` crash, as no standard workstation contains 200+ GB of RAM to hold the XML tree.

---

## 3. Required Architectural Fix for 1-Month Scale

To successfully execute a 1-month simulation on a standard 8GB or 16GB RAM laptop, the underlying Python architecture must be slightly refactored to eliminate the in-memory data accumulation. 

### The Solution: Streaming I/O
Instead of appending `<step>` elements to a master `root` XML object in RAM, the simulation must be updated to use a **Streaming XML Writer** (or simply appending strings directly to an open file stream `open("trace.xml", "a")`).

1. **Step Execution:** The Game-Theoretic engine calculates assignments for the current 30-second window.
2. **Immediate Disk Flush:** The python script writes the exact telemetry for that 30-second window directly to the hard drive and immediately deletes it from RAM.
3. **Garbage Collection:** Python's Garbage Collector reclaims the memory.

By implementing this disk-streaming architecture, the memory footprint will remain completely flat regardless of how long the simulation runs. The total RAM requirement for a 1-month run will drop to a constant **~2.0 GB** (1.5 GB to hold the passenger dictionary for final statistical analysis + 500 MB for the Eclipse SUMO network instance), making it flawlessly scalable.

---

## 4. Parallel Execution Feasibility (7-Day Batches)

The planned methodology is to run **7 simulation days parallelly** simultaneously, completing a week of data before launching the next batch.

### 4.1 SUMO Thread-Safety & Process Isolation
Running 7 parallel instances will **NOT** cause the TraCI/libsumo thread-safety issues (Segmentation Faults) encountered during the multi-core dispatch development.
- The previous crash occurred because multiple CPU threads attempted to access a *single* SUMO C++ memory space simultaneously.
- When launching 7 parallel days (`python3 file2.py --day 1`, `python3 file2.py --day 2`), you are launching 7 completely independent **OS processes**. Each process spins up its own strictly isolated instance of the SUMO C++ backend. Because the memory is isolated at the Operating System level, they will execute simultaneously with absolute stability.

### 4.2 Hardware Requirements (Lab Computer: 64 GB RAM)
To execute 7 parallel runs, the hardware must sustain 7x the baseline requirements:

1. **CPU:** Requires at least an 8-core CPU to prevent the 7 independent processes from bottlenecking each other. Most lab workstations comfortably meet this.
2. **RAM (Using Current Unoptimized Code):** 
   - 7 parallel instances × ~7.0 GB per 24-hour run = **~49.0 GB RAM**.
   - With 64 GB available, the lab machine **can technically survive** the unoptimized memory bloat without crashing. However, OS background processes and Python garbage collection spikes may push the machine dangerously close to its 64 GB limit.
3. **RAM (Using the Recommended Streaming XML Fix):**
   - 7 parallel instances × ~500 MB per run = **~3.5 GB RAM total**.
   - Implementing the disk-streaming fix makes the 7-day parallel execution incredibly lightweight, leaving 60+ GB of RAM free for the operating system and ensuring zero risk of an OOM crash.
