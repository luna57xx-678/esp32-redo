# AquaSense Lab / ESP32 Redo

A separate, self-contained local web app for testing the hidden water-leak localization workflow before ESP32 hardware is ready.

## What it does
- A responsive dashboard with editable inputs for pipe length, both sensor positions, true simulated leak position, assumed propagation speed, sample rate, signal window, pulse frequency/duration, noise level, random seed, and maximum lag search.
- FastAPI backend validates inputs and generates two noisy synthetic sensor signals.
- A basic cross-correlation time-delay estimate is converted to a leak-position estimate for a leak between the two sensors.
- Shows estimated position, absolute error, measured/theoretical delay, sample count, sensor map, interpretation, and downloadable JSON trace.
- No frontend build tool or Node/npm required. The frontend is plain HTML/CSS/JavaScript served by FastAPI.

## Windows / VS Code setup
Open a PowerShell terminal in the extracted `esp32-redo` folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in the browser. API health: http://127.0.0.1:8000/api/health. Interactive API docs: http://127.0.0.1:8000/docs.

Stop the server with `Ctrl+C` in the terminal where Uvicorn is running.

## Important model limitations
This is a **synthetic test bench**, not a validated physical model. The entered true leak position is used to create synthetic arrivals; it is not supplied to the delay-estimation equation itself. The displayed estimate is calculated from the measured cross-correlation lag and the assumed propagation speed. The basic two-sensor formula is reliable only when the leak lies between the two sensors and the sensor geometry/model assumptions hold. The generated tone bursts are deliberately simplified and do not reproduce real pipe acoustics, water pressure, reflections, joints, sensor mounting, microphone response, ADC noise, or clock drift. Use the dashboard to test software behavior and explore parameters, not to claim field accuracy.

## Sensor integration later
When hardware is ready, replace the synthetic signal generation in `backend/main.py` with ingestion of timestamped windows from ESP32 nodes, while preserving validation, trace output, and UI. This project does not yet read ESP32 devices or MQTT messages.
