"""
Reads Locust CSV output and plots p90 response time vs concurrent users.
"""
import argparse
import pandas as pd
import matplotlib.pyplot as plt
import json
from pathlib import Path

def analyze_locust(csv_prefix):
    history_file = f"{csv_prefix}_stats_history.csv"
    if not Path(history_file).exists():
        print(f"Error: {history_file} not found.")
        return

    df = pd.DataFrame()
    try:
        df = pd.read_csv(history_file)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Filter and aggregate
    chat_df = df[df['Name'].str.contains('/chat', na=False)].copy()
    
    # Fallback to Aggregated if no specific chat names found (common in headless runs)
    if chat_df.empty:
        chat_df = df[df['Name'] == 'Aggregated'].copy()
        print("Using Aggregated data for analysis...")

    # Clean data: Convert '90%' to numeric (handles 'N/A' strings) and drop NaNs
    chat_df['90%'] = pd.to_numeric(chat_df['90%'], errors='coerce')
    chat_df = chat_df.dropna(subset=['90%'])

    if chat_df.empty:
        print("No valid numeric latency data found in Locust history.")
        return

    # Group by User Count and take the mean of the 90% column
    summary = chat_df.groupby('User Count')['90%'].mean().reset_index()
    summary = summary.sort_values('User Count')

    baseline_p90 = summary.iloc[0]['90%']
    threshold = 2 * baseline_p90
    
    breakpoint_row = summary[summary['90%'] >= threshold].head(1)
    
    if not breakpoint_row.empty:
        breakpoint_users = int(breakpoint_row.iloc[0]['User Count'])
        breakpoint_p90 = float(breakpoint_row.iloc[0]['90%'])
    else:
        breakpoint_users = int(summary.iloc[-1]['User Count'])
        breakpoint_p90 = float(summary.iloc[-1]['90%'])

    # Plotting
    plt.figure(figsize=(10, 6))
    plt.plot(summary['User Count'], summary['90%'], marker='o', label='p90 Latency')
    plt.axhline(y=threshold, color='r', linestyle='--', label='2x Baseline Threshold')
    
    plt.scatter([breakpoint_users], [breakpoint_p90], color='red', s=100, zorder=5)
    plt.annotate(f'Breakpoint: {breakpoint_users} users', 
                 (breakpoint_users, breakpoint_p90), 
                 textcoords="offset points", xytext=(0,10), ha='center', color='red')

    plt.xlabel('Concurrent Users')
    plt.ylabel('p90 Response Time (ms)')
    plt.title('Latency Breakpoint Analysis')
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.legend()

    reports_dir = Path("evals/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(reports_dir / "latency_breakpoint.png")
    
    # Save JSON
    analysis = {
        "baseline_p90_ms": float(baseline_p90),
        "breakpoint_users": breakpoint_users,
        "breakpoint_p90_ms": float(breakpoint_p90)
    }
    with open(reports_dir / "locust_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"Baseline p90: {baseline_p90:.1f}ms | Breakpoint: {breakpoint_users} users at {breakpoint_p90:.1f}ms")

    print("\n--- Latency vs. User Count Summary ---")
    print(f"{'Users':<10} | {'p90 Latency (ms)':<20}")
    print("-" * 35)
    for _, row in summary.iterrows():
        print(f"{int(row['User Count']):<10} | {row['90%']:<20.1f}")
    print("-" * 35)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-prefix", required=True)
    args = parser.parse_args()
    analyze_locust(args.csv_prefix)
