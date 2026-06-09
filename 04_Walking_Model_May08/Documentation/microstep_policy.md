# Micro-steps vs. Rolling Horizon Policy

## The Core Policy (Version1_final.pdf)
Your core policy uses a **Rolling Horizon Optimization** strategy. 
The mathematical rule is: Every $\Delta t$ seconds (e.g., 30 seconds), the system freezes. The algorithm looks at all waiting passengers and all available vehicles, computes the cost function for all subsets, makes assignments, and gives vehicles their routes. The system then "rolls" forward until the next $\Delta t$.

*Crucially, the math and routing decisions only happen exactly once every $\Delta t$ seconds.*

## The Flaw with SUMO 30-Second Jumps
If we tell the physical SUMO simulator to jump 30 seconds all at once, the system goes "blind" during that window.
Imagine a vehicle is assigned a passenger at $t=300$. It starts driving. At $t=305$, the vehicle physically crosses the passenger's pickup edge. In reality, the passenger boards right then.

However, because the Python script jumped SUMO straight to $t=330$, the script doesn't look at the vehicle until $t=330$. The passenger physically waited on the street for 25 extra seconds while the vehicle was parked next to them because the script didn't trigger the "boarding" action. Because the script thinks the passenger hasn't boarded, it keeps the vehicle "locked" and refuses to assign it any new ride-sharing passengers.

## How the 5-Second Micro-step Script Works
To fix the blindness, we implement an internal 5-second physics loop:

```python
# The Optimization Cycle (Runs strictly every 30s)
while current_time <= horizon:
    
    # ── Internal Physics Engine Loop (Micro-steps) ──
    for _ in range(6): 
        traci.simulationStep(current_time + 5) # Advance physical cars by 5s
        detect_pickups_and_dropoffs()          # Check if anyone can board
        
    # ... End of 30s. Now run the Mathematical Optimization!
    choose_best_assignments()
```

### Why this perfectly adheres to the policy:
1. **Mathematical Integrity:** The `choose_best_assignments()` and `evaluate_subset()` functions are **still only called exactly once every 30 seconds**. The algorithmic policy is 100% preserved.
2. **Physical Reality:** The cars just move in smoother 5-second increments so we can detect the exact moment a passenger boards. This unblocks the vehicle's capacity immediately, drastically boosting your system's efficiency and resolving the massive rejection bottleneck you saw earlier.
