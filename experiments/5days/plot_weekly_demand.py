#!/usr/bin/env python3
"""
Manhattan Ride-Sharing Weekly Demand Analysis Plotter
=====================================================
Generates high-resolution graphs for each day of the first week of January 2016
(Jan 4 - Jan 10), highlighting Peak, Off-Peak (Min), and Median demand hours.

Outputs:
  1. Individual daily plots: `demand_plots/demand_plot_<Day>.png`
  2. Consolidated 7-day grid view: `weekly_demand_grid.png`
  3. Overlay comparative view: `weekly_demand_overlay.png`
"""

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
# Set publication-quality aesthetics
plt.style.use('ggplot')
plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['DejaVu Sans', 'Arial', 'Helvetica'],
    'axes.labelsize': 12,
    'axes.titlesize': 14,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'figure.titlesize': 16
})

# Time labels (48 half-hour steps from 00:00 to 23:30)
TIMESTAMPS = [
    '00:00', '00:30', '01:00', '01:30', '02:00', '02:30', '03:00', '03:30',
    '04:00', '04:30', '05:00', '05:30', '06:00', '06:30', '07:00', '07:30',
    '08:00', '08:30', '09:00', '09:30', '10:00', '10:30', '11:00', '11:30',
    '12:00', '12:30', '13:00', '13:30', '14:00', '14:30', '15:00', '15:30',
    '16:00', '16:30', '17:00', '17:30', '18:00', '18:30', '19:00', '19:30',
    '20:00', '20:30', '21:00', '21:30', '22:00', '22:30', '23:00', '23:30'
]

# Demand data from weekly_demand_analysis.md (Jan 4 - Jan 10, 2016)
DEMAND_DATA = {
    'Monday': [3404, 2644, 2122, 1713, 1375, 1107, 968, 967, 1063, 1259, 2170, 4187,
               7532, 10682, 13453, 15444, 16239, 15947, 14202, 12394, 11526, 11254, 11358, 12016,
               12365, 12185, 12349, 12790, 13637, 14796, 14751, 14090, 13871, 15003, 16751, 18307,
               19358, 19265, 18278, 16731, 14963, 13860, 12833, 12204, 10894, 8216, 6355, 4756],
    'Tuesday': [4247, 3357, 2681, 1987, 1489, 1189, 1009, 965, 952, 1254, 2558, 4715,
                8347, 12355, 15981, 18776, 19378, 18437, 17178, 15598, 14359, 13904, 14142, 14594,
                14371, 13877, 13799, 14108, 14818, 15785, 15429, 14265, 13486, 13988, 15938, 18108,
                19443, 19152, 17853, 16840, 16267, 15489, 15206, 14454, 11941, 9822, 7917, 5770],
    'Wednesday': [4737, 3668, 2837, 2194, 1780, 1400, 1182, 1164, 1134, 1241, 2294, 4179,
                  7824, 12024, 15391, 17758, 18535, 18250, 17113, 15532, 14379, 13854, 14001, 14644,
                  14542, 14186, 14151, 14314, 14922, 15513, 15022, 13835, 13058, 14030, 16310, 18530,
                  19985, 20220, 19422, 18530, 17661, 16934, 16483, 15621, 14318, 11871, 9046, 6635],
    'Thursday': [5633, 4346, 3455, 2680, 2104, 1612, 1328, 1249, 1167, 1292, 2390, 4414,
                 8198, 12278, 15667, 18041, 18578, 18169, 16904, 15241, 14205, 13783, 14158, 14800,
                 14662, 14122, 14287, 14799, 15512, 16043, 15341, 14181, 13208, 13846, 16068, 18895,
                 20566, 20785, 20538, 19539, 18361, 17805, 17838, 17662, 16427, 14937, 12630, 8706],
    'Friday': [8007, 6473, 5177, 4165, 3355, 2617, 2087, 1864, 1582, 1462, 2398, 4216,
               7552, 11436, 15270, 17742, 18176, 18132, 17293, 15649, 14827, 14667, 15019, 15764,
               15451, 14808, 15021, 15680, 16482, 16889, 16018, 14842, 14064, 14818, 17405, 19793,
               21220, 22453, 22303, 20554, 19026, 18407, 18132, 18773, 19302, 18724, 17864, 13103],
    'Saturday': [16223, 14976, 13816, 12442, 10920, 9201, 7575, 6093, 4108, 2440, 1765, 1832,
                 2638, 3649, 4906, 5811, 7389, 9677, 11944, 13284, 14201, 15123, 16497, 18761,
                 19876, 19232, 18158, 17172, 16924, 17341, 17890, 17985, 16871, 16801, 18267, 19755,
                 20649, 21676, 21485, 19441, 18222, 17549, 17012, 18070, 19283, 19819, 19410, 17899],
    'Sunday': [19832, 17944, 16529, 15186, 13817, 11759, 9803, 7946, 5102, 2736, 1845, 1634,
               2172, 2788, 3647, 4868, 6070, 7312, 9171, 11021, 13851, 15391, 15714, 16749,
               16533, 15992, 15444, 14967, 14709, 14531, 16981, 17422, 14493, 13909, 14305, 14771,
               15287, 14461, 12738, 11824, 11019, 10435, 10306, 10205, 8982, 7591, 6257, 13165]
}

# Color palette for each day
COLORS = {
    'Monday': '#1f77b4',
    'Tuesday': '#ff7f0e',
    'Wednesday': '#2ca02c',
    'Thursday': '#d62728',
    'Friday': '#9467bd',
    'Saturday': '#8c564b',
    'Sunday': '#e377c2'
}

def get_metrics(demand):
    """Calculates peak, off-peak (min), and median indices and values."""
    arr = np.array(demand)
    peak_idx = int(np.argmax(arr))
    offpeak_idx = int(np.argmin(arr))
    
    # Median value and closest index to median
    median_val = np.median(arr)
    median_idx = int(np.argmin(np.abs(arr - median_val)))
    
    return {
        'peak': (peak_idx, TIMESTAMPS[peak_idx], int(arr[peak_idx])),
        'offpeak': (offpeak_idx, TIMESTAMPS[offpeak_idx], int(arr[offpeak_idx])),
        'median': (median_idx, TIMESTAMPS[median_idx], int(arr[median_idx])),
        'median_val': median_val
    }

def plot_single_day(day, demand, output_dir):
    """Generates an individual high-resolution plot for a specific day."""
    metrics = get_metrics(demand)
    color = COLORS.get(day, '#1f77b4')
    
    fig, ax = plt.subplots(figsize=(12, 6), dpi=300)
    
    # Plot main line and filled area
    ax.plot(range(48), demand, color=color, linewidth=2.5, marker='o', markersize=4, label=f"{day} Demand")
    ax.fill_between(range(48), demand, color=color, alpha=0.15)
    
    # Highlight Peak Hour (Red star)
    p_idx, p_time, p_val = metrics['peak']
    ax.scatter(p_idx, p_val, color='red', s=140, zorder=5, marker='*', label=f"Peak: {p_time} ({p_val:,} trips)")
    ax.annotate(f"Peak: {p_time}\n({p_val:,})",
                xy=(p_idx, p_val),
                xytext=(p_idx - 3 if p_idx > 30 else p_idx + 1, p_val * 0.92),
                arrowprops=dict(arrowstyle="->", color='red', lw=1.5),
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="red", lw=1.2),
                fontsize=10, fontweight='bold', color='darkred')

    # Highlight Off-Peak Hour (Blue/Green circle)
    o_idx, o_time, o_val = metrics['offpeak']
    ax.scatter(o_idx, o_val, color='teal', s=80, zorder=5, marker='o', label=f"Off-Peak: {o_time} ({o_val:,} trips)")
    ax.annotate(f"Off-Peak: {o_time}\n({o_val:,})",
                xy=(o_idx, o_val),
                xytext=(o_idx + 1 if o_idx < 40 else o_idx - 5, max(o_val * 2.2, 3500)),
                arrowprops=dict(arrowstyle="->", color='teal', lw=1.5),
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="teal", lw=1.2),
                fontsize=9, fontweight='bold', color='teal')

    # Highlight Median Hour (Orange square)
    m_idx, m_time, m_val = metrics['median']
    ax.scatter(m_idx, m_val, color='darkorange', s=70, zorder=5, marker='s', label=f"Median: {m_time} (~{int(metrics['median_val']):,} trips)")
    ax.axhline(metrics['median_val'], color='darkorange', linestyle='--', linewidth=1.2, alpha=0.7)
    
    # Styling and formatting
    ax.set_title(f"Manhattan Ride-Sharing Demand Profile — {day} (Jan 2016)", fontsize=15, fontweight='bold', pad=15)
    ax.set_xlabel("Time of Day (30-minute Rolling Windows)", fontsize=12, fontweight='bold', labelpad=10)
    ax.set_ylabel("Passenger Trips per Hour", fontsize=12, fontweight='bold', labelpad=10)
    
    # Set x-ticks every 2 hours (4 half-hour intervals)
    xticks = list(range(0, 48, 4))
    ax.set_xticks(xticks)
    ax.set_xticklabels([TIMESTAMPS[i] for i in xticks], rotation=45, ha='right')
    ax.set_xlim(0, 47)
    ax.set_ylim(0, max(demand) * 1.15)
    
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x):,}"))
    ax.legend(loc="upper left", frameon=True, facecolor='white', framealpha=0.9, fontsize=10)
    
    plt.tight_layout()
    out_path = os.path.join(output_dir, f"demand_plot_{day}.png")
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_path}")

def plot_grid(output_dir):
    """Generates a 4x2 consolidated grid plot of all 7 days."""
    fig, axes = plt.subplots(4, 2, figsize=(18, 16), dpi=300)
    axes = axes.flatten()
    
    days = list(DEMAND_DATA.keys())
    
    for idx, day in enumerate(days):
        ax = axes[idx]
        demand = DEMAND_DATA[day]
        color = COLORS[day]
        metrics = get_metrics(demand)
        
        ax.plot(range(48), demand, color=color, linewidth=2, label=day)
        ax.fill_between(range(48), demand, color=color, alpha=0.15)
        
        # Peak Marker
        p_idx, p_time, p_val = metrics['peak']
        ax.scatter(p_idx, p_val, color='red', s=70, marker='*', zorder=5)
        ax.text(p_idx, p_val * 1.05, f"Peak {p_time}\n({p_val:,})", fontsize=8, ha='center',
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="red", alpha=0.85))
                
        # Off-Peak Marker
        o_idx, o_time, o_val = metrics['offpeak']
        ax.scatter(o_idx, o_val, color='teal', s=40, marker='o', zorder=5)
        
        ax.set_title(f"{day} (Peak: {p_time} | Off-Peak: {o_time})", fontsize=12, fontweight='bold')
        ax.set_xticks(list(range(0, 48, 6)))
        ax.set_xticklabels([TIMESTAMPS[i] for i in range(0, 48, 6)], rotation=30, ha='right', fontsize=9)
        ax.set_xlim(0, 47)
        ax.set_ylim(0, 25000)
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x):,}"))
        ax.grid(True, linestyle='--', alpha=0.6)
        
    # Hide the 8th empty subplot
    axes[7].axis('off')
    
    plt.suptitle("Manhattan 7-Day Diurnal Ride-Sharing Demand Profiles (January 2016)",
                 fontsize=18, fontweight='bold', y=0.99)
    plt.tight_layout()
    out_path = os.path.join(output_dir, "weekly_demand_grid.png")
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_path}")

def plot_overlay(output_dir):
    """Generates a combined overlay plot comparing weekdays and weekends."""
    fig, ax = plt.subplots(figsize=(14, 7), dpi=300)
    
    for day, demand in DEMAND_DATA.items():
        style = '-' if day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] else '--'
        lw = 2.2 if style == '-' else 2.8
        ax.plot(range(48), demand, color=COLORS[day], linewidth=lw, linestyle=style, label=day)
        
    ax.set_title("Weekly Demand Overlay: Weekdays vs. Weekends (Manhattan Jan 2016)",
                 fontsize=16, fontweight='bold', pad=15)
    ax.set_xlabel("Time of Day (30-minute Rolling Windows)", fontsize=12, fontweight='bold')
    ax.set_ylabel("Passenger Trips per Hour", fontsize=12, fontweight='bold')
    
    xticks = list(range(0, 48, 4))
    ax.set_xticks(xticks)
    ax.set_xticklabels([TIMESTAMPS[i] for i in xticks], rotation=45, ha='right')
    ax.set_xlim(0, 47)
    ax.set_ylim(0, 25000)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x):,}"))
    ax.grid(True, linestyle='--', alpha=0.6)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=True, fontsize=11)
    
    plt.tight_layout()
    out_path = os.path.join(output_dir, "weekly_demand_overlay.png")
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_path}")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plots_dir = os.path.join(base_dir, "demand_plots")
    os.makedirs(plots_dir, exist_ok=True)
    
    print("Generating individual daily plots...")
    for day, demand in DEMAND_DATA.items():
        plot_single_day(day, demand, plots_dir)
        
    print("Generating consolidated 7-day grid plot...")
    plot_grid(base_dir)
    
    print("Generating weekly comparison overlay plot...")
    plot_overlay(base_dir)
    
    print("\nAll demand plots successfully generated!")

if __name__ == "__main__":
    main()
