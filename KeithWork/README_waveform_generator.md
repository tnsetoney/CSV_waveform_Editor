# Rigol CAN Waveform Generator

This project generates Rigol-compatible CAN-H / CAN-L waveform files from the provided `Volvo ECU plaintext 1_6-normalised-CH1 1.csv` CAN log.

## What was created
- `rigol_can_waveform_generator.py`: Python script that parses the CSV, encodes extended CAN frames, and exports six waveform scenario files.
- `waveforms/`: output directory containing generated waveform CSV files and metadata.

## Generated scenarios
- `base`: clean CAN traffic waveform
- `timing_glitch`: inserts timing variations
- `slow_edges`: slows the edge transitions
- `ringing`: adds damped ringing artifacts
- `dropped_bits`: simulates dropped bit transitions
- `voltage_spikes`: adds transient voltage spikes
- `noise_overlay`: overlays low-level noise on CAN signals

## Usage
1. Install Python 3 and optionally `pyvisa` if you want to add Rigol USB control later.
2. Run the generator from the `testing` folder:
   ```bash
   python rigol_can_waveform_generator.py
   ```
3. Choose `1) Export all waveform scenarios`.

## DG822 Pro CSV GUI Uploader
This repository now includes a desktop GUI uploader:

- `dg822_csv_gui.py`

It can:
- discover VISA resources,
- connect to your DG822 Pro,
- load a dual-channel CSV (`CAN_H_V` / `CAN_L_V`) or two single-column CSV files,
- upload the waveforms to CH1/CH2 and enable outputs.

### Setup virtual environment (Windows PowerShell)
```powershell
cd KeithWork
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m ensurepip --upgrade
python -m pip install -r requirements.txt
```

### Run GUI
```powershell
cd KeithWork
.\.venv\Scripts\python.exe dg822_csv_gui.py
```

## Notes
- Output files are written to `waveforms/`.
- Each scenario loops through the generated waveform sample set.
- The script is menu-driven and can be extended to add direct Rigol USB control with `pyvisa` later.
