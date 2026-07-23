import math

# Total demand: 5325 passengers (from filtered_1hr_trips.csv)
TOTAL_DEMAND = 5325

data = [
    # (fleet, boarded, completed, rejections, no_veh_rej, deadlock_rej, avg_wait, med_wait, avg_inveh, med_inveh, avg_walk, subset, occupancy, serving%, deadhead%, omega, pmatch)
    (600,  3771, 3506, 1228, 1203, 25, 663.33, 570.00, 1243.90, 995.00, 99.40, 1.29, 1.96, 78.0, 22.0, +0.2802, 0.6840),
    (700,  4276, 4012,  740,  715, 25, 656.75, 560.00, 1289.17, 1005.00, 99.83, 1.28, 1.95, 76.3, 23.7, +0.0339, 0.5492),
    (800,  4594, 4273,  457,  432, 25, 631.66, 502.00, 1296.59, 1030.00, 99.95, 1.26, 1.91, 74.3, 25.7, -0.1277, 0.4609),
    (900,  4886, 4557,  240,  215, 25, 637.92, 499.00, 1321.91, 1040.00, 99.34, 1.26, 1.95, 71.0, 29.0, -0.2599, 0.3879),
    (1000, 5127, 4759,  115,   90, 25, 644.36, 477.00, 1354.33, 1045.00, 99.26, 1.27, 1.92, 68.7, 31.3, -0.6464, 0.1846),
    (1100, 5262, 4855,   49,   24, 25, 631.79, 457.00, 1305.13, 1010.00, 99.37, 1.25, 1.88, 64.8, 35.2, -0.7299, 0.1365),
    (1300, 5290, 4899,   19,    7, 25, 616.29, 414.00, 1291.25,  960.00, 99.33, 1.29, 1.81, 58.2, 41.8, -0.8134, 0.0944),
]

print("=" * 120)
print(f"{'Fleet':>6} | {'Board':>5} {'Cmpl':>5} {'Rej':>5} | {'Rej%':>5} {'Svc%':>5} | {'AvgWait':>8} {'MedWait':>8} {'AvgRide':>8} {'MedRide':>8} | {'Serv%':>5} {'Dead%':>5} | {'Ω':>7} {'P(m)':>6} | {'Trips/Veh':>9} {'Util':>5}")
print("-" * 120)

for fleet, boarded, completed, rej, no_veh, dl, avgw, medw, avgr, medr, walk, sub, occ, srv, dh, omega, pm in data:
    rej_pct = rej / TOTAL_DEMAND * 100
    svc_pct = boarded / TOTAL_DEMAND * 100
    trips_per_veh = completed / fleet
    # Marginal rejection reduction per 100 vehicles added
    util = completed / fleet
    
    print(f"{fleet:>6} | {boarded:>5} {completed:>5} {rej:>5} | {rej_pct:>4.1f}% {svc_pct:>4.1f}% | {avgw:>7.0f}s {medw:>7.0f}s {avgr:>7.0f}s {medr:>7.0f}s | {srv:>4.1f}% {dh:>4.1f}% | {omega:>+7.3f} {pm:>5.3f} | {trips_per_veh:>8.2f} {util:>5.2f}")

print()
print("=" * 80)
print("MARGINAL ANALYSIS (diminishing returns per +100 vehicles)")
print("=" * 80)
print(f"{'Step':>12} | {'ΔBoard':>6} {'ΔRej':>6} | {'Marginal Rej Reduction':>24} | {'ΔServ%':>7} | {'Verdict':>30}")
print("-" * 80)

for i in range(1, len(data)):
    f_prev, b_prev, c_prev, r_prev = data[i-1][0], data[i-1][1], data[i-1][2], data[i-1][3]
    f_cur,  b_cur,  c_cur,  r_cur  = data[i][0],   data[i][1],   data[i][2],   data[i][3]
    
    d_fleet = f_cur - f_prev
    d_board = b_cur - b_prev
    d_rej = r_prev - r_cur
    d_srv = data[i][13] - data[i-1][13]
    
    # Marginal rejection reduction per vehicle added
    marginal = d_rej / d_fleet if d_fleet > 0 else 0
    
    if marginal > 3.0:
        verdict = "STRONG gain"
    elif marginal > 1.0:
        verdict = "MODERATE gain"
    elif marginal > 0.5:
        verdict = "DIMINISHING returns"
    else:
        verdict = "NEGLIGIBLE gain"
    
    print(f"{f_prev}->{f_cur:>4} | {d_board:>+5} {d_rej:>+5} | {marginal:>8.2f} rej saved/veh added | {d_srv:>+6.1f}% | {verdict:>30}")

print()
print("=" * 80)
print("OPTIMAL FLEET ANALYSIS (Knee-Point Detection)")
print("=" * 80)

# Method: Find the fleet size where marginal rejection reduction drops below 1.0
# (i.e., adding 100 vehicles saves fewer than 100 rejections)
for i in range(1, len(data)):
    f_prev, r_prev = data[i-1][0], data[i-1][3]
    f_cur,  r_cur  = data[i][0],   data[i][3]
    d_fleet = f_cur - f_prev
    d_rej = r_prev - r_cur
    marginal = d_rej / d_fleet if d_fleet > 0 else 0
    
    if marginal < 1.0:
        # The previous step was the last "efficient" one
        knee_fleet = f_prev
        knee_idx = i - 1
        print(f"  Knee point at {f_prev} vehicles (marginal drops to {marginal:.2f} at {f_cur})")
        break

# Also compute Ω = 0 crossing (supply-demand equilibrium)
for i in range(len(data)):
    if data[i][15] < 0:
        if i > 0:
            # Linear interpolation
            o1, o2 = data[i-1][15], data[i][15]
            f1, f2 = data[i-1][0], data[i][0]
            f_eq = f1 + (0 - o1) * (f2 - f1) / (o2 - o1)
            print(f"  Ω = 0 equilibrium at ~{f_eq:.0f} vehicles (linear interpolation between {f1} and {f2})")
        break

# Rejection asymptote analysis
print()
print("Rejection Floor Analysis:")
for f, b, c, r, nv, dl, *_ in data:
    print(f"  {f:>5} veh: {r:>4} rejections ({nv:>4} coverage + {dl:>2} deadlock) → coverage rejections are reducible, deadlock rejections (~25) are structural")

print()
print("CONCLUSION:")
print("  The ~25 deadlock_timeout_onboard rejections are a STRUCTURAL FLOOR — these are caused by")
print("  SUMO traffic gridlock, NOT insufficient fleet size. Adding more vehicles CANNOT fix them.")
print(f"  Therefore, the effective reducible rejections at 900 vehicles = {data[3][3]} - 25 = {data[3][3]-25}")
print(f"  And at 1000 vehicles = {data[4][3]} - 25 = {data[4][3]-25}")

