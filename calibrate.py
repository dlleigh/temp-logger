#!/usr/bin/env python3
"""Calibrate oven thermal time constants from local CSV data.

Reads temperature CSV files from the data directory, identifies cooling phases
from past firings, fits a double-exponential decay model to each, and saves
the median time constants to calibration.yml.

Usage:
    python calibrate.py                          # uses defaults from config
    python calibrate.py --data-dir /path/to/data # override data directory
    python calibrate.py --output calibration.yml # override output path
"""

import argparse
import csv
import glob
import os
import sys

import numpy as np
import yaml
from datetime import datetime, timedelta
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score


def load_csv_data(data_dir):
    """Load and concatenate all CSV files from the data directory."""
    csv_files = sorted(glob.glob(os.path.join(data_dir, '*.csv')))
    if not csv_files:
        print(f"No CSV files found in {data_dir}")
        return None

    rows = []
    for path in csv_files:
        with open(path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['temperature'] = float(row['temperature'])
                row['timestamp'] = datetime.fromisoformat(row['timestamp'])
                rows.append(row)

    if not rows:
        return None

    print(f"Loaded {len(rows)} readings from {len(csv_files)} CSV files")
    return rows


def find_firing_events(rows, threshold=400, gap_hours=12):
    """Find distinct firing events from temperature data.

    A firing is detected when dome firebrick temperature exceeds the threshold.
    Events separated by more than gap_hours are considered separate firings.
    Returns list of (peak_time, end_time) tuples for each firing's cooling phase.
    """
    # Filter to dome firebrick readings above threshold
    hot_readings = [r for r in rows
                    if r['location'] == 'dome firebrick' and r['temperature'] > threshold]

    if not hot_readings:
        print("No firing events found (no readings above %d°F)" % threshold)
        return []

    hot_readings.sort(key=lambda r: r['timestamp'])

    # Group into firings by time gap
    firings_raw = [[hot_readings[0]]]
    for r in hot_readings[1:]:
        if (r['timestamp'] - firings_raw[-1][-1]['timestamp']) > timedelta(hours=gap_hours):
            firings_raw.append([r])
        else:
            firings_raw[-1].append(r)

    firings = []
    for group in firings_raw:
        peak_reading = max(group, key=lambda r: r['temperature'])
        peak_time = peak_reading['timestamp']
        end_time = group[-1]['timestamp'] + timedelta(hours=12)
        firings.append((peak_time, end_time))

    print(f"Found {len(firings)} firing events")
    for i, (peak, end) in enumerate(firings):
        print(f"  Firing {i+1}: peak at {peak.strftime('%Y-%m-%d %H:%M')}")

    return firings


def extract_cooling_curve(rows, peak_time, end_time, location, min_temp=150):
    """Extract cooling-phase data for a specific location and firing."""
    readings = [r for r in rows
                if r['location'] == location
                and peak_time <= r['timestamp'] <= end_time]

    if not readings:
        return None, None

    readings.sort(key=lambda r: r['timestamp'])
    temps = [r['temperature'] for r in readings]
    times = [r['timestamp'] for r in readings]

    # Find peak in this location's data and trim to cooling only
    peak_idx = temps.index(max(temps))
    times = times[peak_idx:]
    temps = temps[peak_idx:]

    # Trim below min_temp
    for i, t in enumerate(temps):
        if t < min_temp:
            times = times[:i+1]
            temps = temps[:i+1]
            break

    if len(temps) < 30:
        return None, None

    # Convert to minutes from peak
    t0 = times[0]
    minutes = np.array([(t - t0).total_seconds() / 60.0 for t in times])
    temps = np.array(temps)

    return minutes, temps


def fit_double_exponential(minutes, temps):
    """Fit T(t) = A1*exp(-t/tau1) + A2*exp(-t/tau2) + T_ambient.

    Returns dict with parameters and fit quality, or None on failure.
    """
    temp_range = temps.max() - temps.min()

    def model(t, A1, tau1, A2, tau2, T_amb):
        return A1 * np.exp(-t / tau1) + A2 * np.exp(-t / tau2) + T_amb

    p0 = [temp_range * 0.4, 50, temp_range * 0.6, 250, temps.min()]
    bounds = ([0, 5, 0, 30, 0], [2000, 300, 2000, 1000, 200])

    try:
        popt, _ = curve_fit(model, minutes, temps, p0=p0, bounds=bounds, maxfev=10000)
        A1, tau1, A2, tau2, T_amb = popt

        # Ensure tau1 < tau2 (tau1 = fast component)
        if tau1 > tau2:
            A1, tau1, A2, tau2 = A2, tau2, A1, tau1

        y_pred = model(minutes, A1, tau1, A2, tau2, T_amb)
        r2 = r2_score(temps, y_pred)
        mae = float(np.mean(np.abs(temps - y_pred)))

        return {
            'A1': float(A1), 'tau1': float(tau1),
            'A2': float(A2), 'tau2': float(tau2),
            'T_ambient': float(T_amb),
            'r2': float(r2), 'mae': mae,
        }

    except (RuntimeError, ValueError) as e:
        print(f"    Fit failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Calibrate oven thermal time constants')
    parser.add_argument('--data-dir', default=None,
                        help='Directory containing CSV data files (default: from config)')
    parser.add_argument('--output', default=None,
                        help='Output calibration YAML file (default: from config)')
    parser.add_argument('--config', default=None,
                        help='Path to temp-logger.yml config file')
    args = parser.parse_args()

    # Load config for defaults
    config = {}
    config_path = args.config or os.environ.get('TEMP_LOGGER_CONFIG', '/etc/temp-logger.yml')
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        pass

    data_dir = args.data_dir or config.get('data_dir', '/home/pi/oven-data')
    output_path = args.output or config.get('calibration_file', '/etc/calibration.yml')

    locations = []
    for tc in config.get('thermocouples', []):
        locations.append(tc['location'])
    if not locations:
        locations = ['hearth firebrick', 'dome firebrick', 'dome cladding']

    # Load data
    rows = load_csv_data(data_dir)
    if rows is None:
        print("No data available for calibration")
        sys.exit(1)

    # Find firings
    firings = find_firing_events(rows)
    if not firings:
        print("No firing events detected in the data")
        sys.exit(1)

    # Fit each firing/location combination
    results = {loc: [] for loc in locations}

    for i, (peak_time, end_time) in enumerate(firings):
        print(f"\n--- Firing {i+1} ---")
        for location in locations:
            minutes, temps = extract_cooling_curve(rows, peak_time, end_time, location)
            if minutes is None:
                print(f"  {location}: insufficient cooling data")
                continue

            params = fit_double_exponential(minutes, temps)
            if params is None:
                continue

            results[location].append(params)
            print(f"  {location}: tau1={params['tau1']:.1f}min, tau2={params['tau2']:.1f}min, "
                  f"R2={params['r2']:.4f}, MAE={params['mae']:.1f}F")

    # Compute median time constants
    calibration = {}
    print("\n=== Calibrated Time Constants ===\n")

    for location in locations:
        fits = results[location]
        if not fits:
            print(f"{location}: No successful fits")
            continue

        tau1_values = [f['tau1'] for f in fits]
        tau2_values = [f['tau2'] for f in fits]

        tau1_median = float(np.median(tau1_values))
        tau2_median = float(np.median(tau2_values))

        key = location.replace(' ', '_')
        calibration[key] = {
            'tau1': round(tau1_median, 1),
            'tau2': round(tau2_median, 1),
        }

        print(f"{location}:")
        print(f"  tau1 (fast): {tau1_median:.1f} min  (from {len(fits)} firings: {[f'{v:.1f}' for v in tau1_values]})")
        print(f"  tau2 (slow): {tau2_median:.1f} min  (from {len(fits)} firings: {[f'{v:.1f}' for v in tau2_values]})")

    if not calibration:
        print("\nNo calibration data produced")
        sys.exit(1)

    # Save
    with open(output_path, 'w') as f:
        yaml.dump(calibration, f, default_flow_style=False)

    print(f"\nCalibration saved to {output_path}")


if __name__ == '__main__':
    main()
