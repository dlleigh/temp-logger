import numpy as np
from datetime import datetime, timedelta
from collections import deque
from scipy.optimize import curve_fit

class TemperaturePredictor:
    def __init__(self, window_minutes=60, tau1=None, tau2=None):
        """
        Args:
            window_minutes: How many minutes of recent data to use for fitting.
            tau1: Calibrated fast decay time constant (minutes). If None, fits all 5 params.
            tau2: Calibrated slow decay time constant (minutes). If None, fits all 5 params.
        """
        self.window_minutes = window_minutes
        self.tau1 = tau1
        self.tau2 = tau2
        self.calibrated = tau1 is not None and tau2 is not None
        self.temperatures = deque(maxlen=window_minutes * 2)

    def add_measurement(self, temperature):
        """Add a new temperature measurement with current timestamp"""
        self.temperatures.append((datetime.now(), temperature))

    def _is_cooling(self, temps, min_points=10):
        """Detect if the oven is in a cooling phase.

        Uses a simple heuristic: a linear fit to the recent data has a negative slope,
        and the temperature has generally been decreasing (allowing for sensor noise).
        """
        if len(temps) < min_points:
            return False
        # Check that a linear trend is negative
        times = np.arange(len(temps), dtype=float)
        slope = np.polyfit(times, temps, 1)[0]
        return slope < 0

    def predict_temperature(self, minutes_ahead=30):
        """Predict temperature after specified minutes using double-exponential decay.

        If calibrated tau values are available, fixes them and only fits amplitudes
        and ambient temperature (3 free params). Otherwise falls back to fitting
        all 5 parameters of the double-exponential model.

        Only produces predictions during the cooling phase.
        """
        if len(self.temperatures) < 10:
            return None

        # Clean old data outside window
        cutoff_time = datetime.now() - timedelta(minutes=self.window_minutes)
        while self.temperatures and self.temperatures[0][0] < cutoff_time:
            self.temperatures.popleft()

        if len(self.temperatures) < 10:
            return None

        # Prepare data for curve fitting
        first_time = self.temperatures[0][0]
        times = np.array([(t[0] - first_time).total_seconds() / 60.0
                         for t in self.temperatures])
        temps = np.array([t[1] for t in self.temperatures])

        # Only predict during cooling phase
        if not self._is_cooling(temps):
            return None

        try:
            future_time = times[-1] + minutes_ahead

            if self.calibrated:
                # Calibrated mode: fix tau1, tau2, only fit A1, A2, T_ambient
                tau1, tau2 = self.tau1, self.tau2

                def model(t, A1, A2, T_amb):
                    return A1 * np.exp(-t / tau1) + A2 * np.exp(-t / tau2) + T_amb

                temp_range = temps.max() - temps.min()
                p0 = [temp_range * 0.4, temp_range * 0.6, temps.min()]
                bounds = ([0, 0, 0], [2000, 2000, 200])
                popt, _ = curve_fit(model, times, temps, p0=p0, bounds=bounds, maxfev=5000)
                return float(model(future_time, *popt))
            else:
                # Uncalibrated fallback: fit all 5 params
                def model(t, A1, tau1, A2, tau2, T_amb):
                    return A1 * np.exp(-t / tau1) + A2 * np.exp(-t / tau2) + T_amb

                temp_range = temps.max() - temps.min()
                p0 = [temp_range * 0.4, 50, temp_range * 0.6, 250, temps.min()]
                bounds = ([0, 5, 0, 30, 0], [2000, 300, 2000, 1000, 200])
                popt, _ = curve_fit(model, times, temps, p0=p0, bounds=bounds, maxfev=5000)
                return float(model(future_time, *popt))

        except (RuntimeError, ValueError):
            return None
