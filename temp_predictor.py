import numpy as np
from datetime import datetime, timedelta
from collections import deque
from scipy.optimize import curve_fit

class TemperaturePredictor:
    def __init__(self, window_minutes=60):
        self.window_minutes = window_minutes
        self.temperatures = deque(maxlen=window_minutes*2)  # Store (timestamp, temp) tuples
        
    def add_measurement(self, temperature):
        """Add a new temperature measurement with current timestamp"""
        self.temperatures.append((datetime.now(), temperature))
        
    def predict_temperature(self, minutes_ahead=30):
        """Predict temperature after specified minutes using polynomial fit"""
        if len(self.temperatures) < 10:  # Need minimum points for reasonable fit
            return None
            
        # Clean old data outside window
        cutoff_time = datetime.now() - timedelta(minutes=self.window_minutes)
        while self.temperatures and self.temperatures[0][0] < cutoff_time:
            self.temperatures.popleft()
            
        # Prepare data for curve fitting
        times = np.array([(t[0] - self.temperatures[0][0]).total_seconds() / 60.0 
                         for t in self.temperatures])
        temps = np.array([t[1] for t in self.temperatures])
        
        # Third-degree polynomial function: temp = a*t³ + b*t² + c*t + d
        def polynomial(t, a, b, c, d):
            return a * t**3 + b * t**2 + c * t + d
            
        try:
            # Fit polynomial curve with initial guess
            p0 = [0, 0, 0, temps.mean()]  # Initial parameters
            popt, _ = curve_fit(polynomial, times, temps, p0=p0, maxfev=2000)
            
            # Predict future temperature
            future_time = times[-1] + minutes_ahead
            predicted_temp = polynomial(future_time, *popt)
            
            return predicted_temp
            
        except RuntimeError:
            return None