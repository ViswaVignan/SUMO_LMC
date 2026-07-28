# Parallelization Failure Analysis: Why Sequential Processing Outperformed Multi-Core Execution

This document details the architectural decisions and roadblocks encountered when attempting to parallelize the combinatorial subset evaluation (the dispatch assignment engine) within the V3 Manhattan Ride-Sharing simulation. 

Initially, a Map-Reduce multi-core framework (utilizing 10 cores) was implemented to rapidly evaluate passenger subsets and calculate optimal vehicle assignments. However, rigorous profiling revealed that parallelization drastically degraded simulation stability and performance. The architecture was subsequently reverted to a highly-optimized sequential pipeline. The reasons for this failure are categorized into Python-specific limitations and SUMO/TraCI architectural constraints.

---

## 1. Python Architecture Issues

### 1.1 The Global Interpreter Lock (GIL) Constraint
When attempting to use **Multithreading** (`concurrent.futures.ThreadPoolExecutor`), the architecture collided with Python's Global Interpreter Lock (GIL). 
*   The assignment engine relies heavily on CPU-bound mathematical operations (calculating detour costs, subset generation, and spatial distances). 
*   Because the GIL only allows one thread to execute Python bytecode at a time, multithreading provided no actual parallel speedup. Threads continuously blocked each other, introducing context-switching overhead without any multi-core utilization.

### 1.2 IPC Serialization Overhead (The Pickling Bottleneck)
To bypass the GIL, we implemented **Multiprocessing** (`multiprocessing.Pool`), which spawns entirely separate memory processes. However, this introduced a severe data serialization bottleneck:
*   To evaluate assignments across 2,000+ vehicles and thousands of active passengers, the master process had to serialize (pickle) the enormous `vehicles` dictionary, the `passengers_by_id` state, and the Manhattan network graph `net`.
*   This data was pushed across Inter-Process Communication (IPC) pipes to the worker processes at *every single macro-step* (every 30 seconds of simulation time).
*   **Result:** The time spent packing and unpacking megabytes of object data across cores vastly outweighed the computational time saved by evaluating subsets in parallel. The overhead created a massive performance regression, making the parallel engine significantly slower than a single-threaded loop.

---

## 2. SUMO & TraCI Thread-Safety Issues

Even if the Python serialization overhead could be mitigated through shared memory (`multiprocessing.shared_memory`), the simulation architecture strictly depends on the Eclipse SUMO engine for physical routing, leading to catastrophic failure.

### 2.1 Lack of Thread-Safety in `libsumo` / `TraCI`
The simulation uses `traci.simulation.findRoute` to evaluate the physical travel time (cost) of adding a passenger to a vehicle's route. 
*   The TraCI API operates over a TCP socket connection to the SUMO server, while `libsumo` (the high-performance C++ binding) accesses the SUMO memory space directly.
*   **Neither interface is thread-safe.** When multiple parallel workers attempted to simultaneously query `findRoute` or read live edge weights, it resulted in race conditions.
*   **Result:** Concurrent access caused the SUMO C++ backend to throw **Segmentation Faults (SIGSEGV)**, instantly crashing the simulation. In cases where it didn't crash, it caused deadlock timeouts as multiple threads fought to lock the single TraCI communication socket.

### 2.2 Routing State Corruption
Because the simulation relies on `ROUTING_MODE_AGGREGATED` to actively poll live traffic congestion, multiple cores querying and modifying route states concurrently caused the underlying routing cache inside SUMO to become corrupted. Vehicles were returned empty paths or infinite travel times, severely breaking the Game-Theoretic assignment logic.

---

## 3. The Resolution: High-Performance Sequential Processing

Because true parallelization was blocked by SUMO's single-threaded API and Python's IPC overhead, we abandoned the multi-core approach in favor of algorithmic optimization:

1.  **Distance-Based Pruning Constraints:** Instead of blindly evaluating all combinations across 10 cores, the sequential engine was restricted to only generate and evaluate subsets of passengers that physically reside within a tight spatial radius of the vehicle. This prevented combinatorial explosion entirely.
2.  **In-Memory Route Caching:** We implemented a local `_route_cache` dictionary that stores the output of `findRoute` during a macro-step. If two vehicles need to evaluate a path between the same two nodes, the second vehicle bypasses SUMO entirely and reads the result from the Python dictionary in $O(1)$ time. The cache is cleared every 30 seconds to maintain live traffic awareness.

### Conclusion
Attempting to force multi-core parallelization onto a state-heavy, C++ coupled simulation like SUMO yielded negative returns. By embracing a sequential architecture, eliminating IPC overhead, and drastically pruning the search space via spatial logic and caching, the simulation executes significantly faster and maintains absolute thread safety and mathematical integrity.
