from __future__ import annotations
from pathlib import Path
from typing import Literal
import math
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="AquaSense Lab API", version="1.0.0", description="Configurable synthetic leak-localization test bench. Simulated data only; not hardware validated.")
app.mount('/assets', StaticFiles(directory=ROOT / 'frontend'), name='assets')

class SimulationInput(BaseModel):
    pipe_length_m: float = Field(23.0, gt=0, le=10000)
    sensor_a_m: float = Field(2.0, ge=0)
    sensor_b_m: float = Field(20.0, ge=0)
    true_leak_m: float = Field(8.0, ge=0)
    propagation_speed_m_s: float = Field(1000.0, gt=0, le=100000)
    sample_rate_hz: int = Field(8000, ge=1000, le=192000)
    signal_window_ms: float = Field(250.0, gt=10, le=5000)
    noise_level: float = Field(0.15, ge=0, le=5, description="Noise RMS relative to pulse peak")
    pulse_frequency_hz: float = Field(700.0, gt=20, le=10000)
    pulse_duration_ms: float = Field(8.0, gt=1, le=100)
    random_seed: int = Field(42, ge=0, le=2147483647)
    max_lag_ms: float = Field(100.0, gt=1, le=2000)

    @model_validator(mode='after')
    def validate_geometry(self):
        if self.sensor_a_m >= self.pipe_length_m or self.sensor_b_m >= self.pipe_length_m:
            raise ValueError('Sensor positions must be inside the pipe (0 to pipe length).')
        if self.sensor_a_m == self.sensor_b_m:
            raise ValueError('Sensor A and Sensor B must be at different positions.')
        if self.true_leak_m > self.pipe_length_m:
            raise ValueError('Leak position cannot exceed pipe length.')
        if self.pulse_frequency_hz >= self.sample_rate_hz / 2:
            raise ValueError('Pulse frequency must be below the Nyquist frequency (half the sample rate).')
        if self.pulse_duration_ms >= self.signal_window_ms:
            raise ValueError('Pulse duration must be shorter than the signal window.')
        return self

def pulse_at(t: np.ndarray, arrival_s: float, frequency: float, duration_s: float) -> np.ndarray:
    local = t - arrival_s
    mask = (local >= 0) & (local < duration_s)
    out = np.zeros_like(t)
    # Hann-windowed tone burst gives the correlation a measurable shape.
    u = local[mask] / duration_s
    out[mask] = np.sin(2 * np.pi * frequency * local[mask]) * (0.5 - 0.5 * np.cos(2 * np.pi * u))
    return out

def estimate_delay(a: np.ndarray, b: np.ndarray, max_lag_samples: int) -> int:
    # Positive lag means B's waveform is later than A's waveform.
    a = a - np.mean(a); b = b - np.mean(b)
    corr = np.correlate(b, a, mode='full')
    center = len(a) - 1
    lo, hi = max(0, center-max_lag_samples), min(len(corr), center+max_lag_samples+1)
    return int(np.argmax(corr[lo:hi]) + lo - center)

@app.get('/')
def home():
    return FileResponse(ROOT / 'frontend' / 'index.html')

@app.get('/api/health')
def health():
    return {'status':'ok', 'service':'AquaSense Lab API', 'mode':'synthetic-simulation-only'}

@app.post('/api/simulate')
def simulate(cfg: SimulationInput):
    fs = cfg.sample_rate_hz
    n = int(round(cfg.signal_window_ms / 1000 * fs))
    if n < 128:
        raise HTTPException(422, 'Signal window is too short for this sample rate.')
    t = np.arange(n, dtype=np.float64) / fs
    true_ta = abs(cfg.true_leak_m - cfg.sensor_a_m) / cfg.propagation_speed_m_s
    true_tb = abs(cfg.true_leak_m - cfg.sensor_b_m) / cfg.propagation_speed_m_s
    rng = np.random.default_rng(cfg.random_seed)
    duration = cfg.pulse_duration_ms / 1000
    a = pulse_at(t, true_ta, cfg.pulse_frequency_hz, duration)
    b = pulse_at(t, true_tb, cfg.pulse_frequency_hz, duration)
    # Add noise independently. Scale against the actual pulse amplitude.
    peak = max(float(np.max(np.abs(a))), float(np.max(np.abs(b))), 1e-9)
    a += rng.normal(0, cfg.noise_level * peak, size=n)
    b += rng.normal(0, cfg.noise_level * peak, size=n)
    max_lag_samples = min(int(cfg.max_lag_ms / 1000 * fs), n - 1)
    lag = estimate_delay(a, b, max_lag_samples)
    measured_dt = lag / fs  # t_B - t_A
    # For a leak between the two sensors, |x-A|-|x-B| = c*(t_A-t_B).
    # Solve using the ordered sensor positions, while accounting for A/B order.
    left, right = sorted((cfg.sensor_a_m, cfg.sensor_b_m))
    # Delay convention and geometry formula are evaluated against physical A/B coordinates.
    estimate = (cfg.sensor_a_m + cfg.sensor_b_m + cfg.propagation_speed_m_s * (true_tb - true_ta if False else -measured_dt)) / 2
    # The above equation assumes the source lies between sensors and A is the left sensor.
    # If A is to the right of B, reverse the delay sign.
    if cfg.sensor_a_m > cfg.sensor_b_m:
        estimate = (cfg.sensor_a_m + cfg.sensor_b_m + cfg.propagation_speed_m_s * measured_dt) / 2
    # Clamp to physical pipe bounds, but retain raw result for transparency.
    raw_estimate = float(estimate)
    bounded_estimate = min(max(raw_estimate, 0.0), cfg.pipe_length_m)
    within_sensors = left <= bounded_estimate <= right
    # Real data cannot resolve a leak outside the sensor pair with this two-sensor formula.
    return {
        'status':'ok', 'mode':'synthetic', 'warning':'Synthetic simulation only. This does not validate real pipe acoustics or ESP32 sensor performance.',
        'inputs':cfg.model_dump(),
        'signal':{'samples':n, 'duration_ms':n/fs*1000, 'sample_rate_hz':fs, 'theoretical_arrival_a_ms':true_ta*1000, 'theoretical_arrival_b_ms':true_tb*1000},
        'result':{'estimated_leak_m':round(bounded_estimate,4), 'raw_estimate_m':round(raw_estimate,4), 'true_leak_m':cfg.true_leak_m,
                  'absolute_error_m':round(abs(bounded_estimate-cfg.true_leak_m),4), 'measured_delay_ms':round(measured_dt*1000,4),
                  'theoretical_delay_ms':round((true_tb-true_ta)*1000,4), 'within_sensor_span':within_sensors,
                  'interpretation':'Leak is between the two sensors.' if within_sensors else 'Estimate falls outside the sensor span; two-sensor between-sensors formula is not reliable for this geometry.'}
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000, reload=True)
