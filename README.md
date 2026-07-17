# SignalGenerateCAN

Tools for generating, editing, and transferring CAN-H/CAN-L (or any dual/single
channel voltage) waveforms to a Rigol DG822 Pro arbitrary waveform generator
over USB/VISA, a standalone CSV waveform editor for preparing/tweaking the
source data, and a real-time PEAK PCAN tool for comparing/validating live CAN
bus traffic across two (or three, including a transmitted reference) channels.

## Contents

| File | Purpose |
| --- | --- |
| [dg822_csv_gui.py](dg822_csv_gui.py) | Main Tkinter GUI: connect to a DG822 over VISA, load CSV waveform(s), upload/download to the instrument, and control channel outputs. |
| [rigol_can_waveform_generator.py](rigol_can_waveform_generator.py) | Core `RigolWaveformManager` class used by the GUI and CLI: VISA connection handling, CSV parsing, waveform prep (voltage/DAC), multiple SCPI transfer strategies (`TRACE BIN`/`CODE`/`VOLTAGE`/`MMEM`) with fallbacks, output enable/disable, and an interactive CLI menu (`python rigol_can_waveform_generator.py`). |
| [csv_waveform_editor.py](csv_waveform_editor.py) | Standalone Tk + matplotlib tool to load a CSV, plot the (absolute) voltage values, drag individual or multi-selected points to edit the curve, resample it with a choice of interpolation methods (Linear/Cubic/B-Spline/Akima/Lanczos), undo any edit (auto-zooming to what changed), pan/zoom manually, and export the edited data to a new CSV. A bottom overview panel always shows the full curve with a viewport indicator. |
| [pcan_compare_tool.py](pcan_compare_tool.py) | Tk GUI that opens two PEAK PCAN channels (via python-can) and compares their live CAN frames against each other in real time (Match/Mismatch/Unmatched with running stats). An optional third "Channel C" can transmit a reference CAN trace CSV so received frames are also checked against the known-sent data (Sent OK/Mismatch/Missing). |
| [dg822.py](dg822.py) | Lower-level `dg822` class for direct PyVISA interaction with the DG8xx/DG9xx AWG series. |
| [debug_csv_download_only.py](debug_csv_download_only.py) | CLI debug script that downloads a dual-column CSV to DG822 memory without enabling outputs, for protocol troubleshooting. |
| [requirements.txt](requirements.txt) | Python dependencies: `pyvisa`, `pyvisa-py`, `matplotlib`, `numpy`, `scipy`, `python-can`. |
| [sample_csv/](sample_csv/) | Example CSV waveforms in both dual-column and split single-column voltage formats (see [sample_csv/README_samples.txt](sample_csv/README_samples.txt)). |
| [Docs/](Docs/) | Reference material, including the Rigol programming guide and sample high/low CSVs. |
| [KeithWork/](KeithWork/) | Prior research/probe scripts used to reverse-engineer the Rigol SCPI upload protocol, plus exported waveform scenarios. |
| `backup_working_*/` | Timestamped snapshots of known-working versions of key scripts, kept before risky edits. |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Usage

### Upload/download waveforms via GUI

```powershell
python dg822_csv_gui.py
```

Connect to the DG822 over VISA, choose a dual-column CSV (`CAN_H_V`/`CAN_L_V`)
or two single-column CH1/CH2 CSVs, set sample rate/amplitude/offset, then
upload (enables outputs) or download only (loads memory, keeps outputs off).
Channel outputs and aligned start/stop can also be controlled independently.

### Edit a waveform CSV

```powershell
python csv_waveform_editor.py
```

- Load any single-column, dual-column, or index+curve(s) CSV; values are
  plotted as absolute voltage.
- Drag a point to change its value (X/sample index stays fixed).
- Hold **Ctrl** and click points, or drag a selection box, to multi-select;
  dragging any selected point then moves the whole selection together.
- Hold the **right mouse button** and drag to pan the view; a plain right
  click cancels the active toolbar Pan/Zoom tool. Mouse wheel and the
  toolbar provide manual zoom (the view never auto-rescales).
- **Interpolate...** resamples every curve to a chosen point count using
  Linear, Cubic, B-Spline, Akima, or Lanczos interpolation.
- **Undo (Ctrl+Z)** reverts the last drag or interpolation and zooms the
  view to whatever changed.
- A read-only overview panel at the bottom always shows the full curve with
  an orange box marking the main plot's current viewport.
- Toggle whether the exported CSV includes a header row, then **Save As
  CSV...** to write the edited curve(s).

### Interactive CLI

```powershell
python rigol_can_waveform_generator.py
```

Detect/connect to the instrument, transfer one of the bundled scenario
waveforms, stop output, or inspect waveform stats, via a numbered menu.

### Compare two PEAK PCAN channels in real time

```powershell
python pcan_compare_tool.py
```

Requires the PEAK PCAN-Basic driver and python-can. Pick a channel and
bitrate for A and B (auto-detected via `can.detect_available_configs` when
available), click **Start**, and the tool matches frames arriving on both
channels by CAN ID (in arrival order) and reports Match / Mismatch /
Unmatched in a live table plus running per-channel statistics and an
overall match rate. Useful for validating that two taps on the same bus
(or a gateway/repeater between two segments) see identical traffic.

Optionally, a third **Channel C** can transmit a reference CAN trace CSV
(same format as `KeithWork/Volvo ECU plaintext 1_6-normalised-CH1 1.csv`:
`Time Stamp,ID,Extended,Dir,Bus,LEN,D1..D8`) onto the bus, with adjustable
playback speed and looping. Every frame Channel C sends is also checked
against what A and B subsequently receive, so the tool reports not only
whether A and B agree with each other, but whether each of them matches
the known-good reference data (Sent OK / Sent Mismatch / Sent Missing).
Channel C must be a different PCAN channel than A and B.

## Notes

- All instrument communication goes through PyVISA; if no VISA backend is
  installed, `pyvisa-py` (already in requirements.txt) is used.
- The Rigol DG822 firmware used during development rejected several SCPI
  command variants; `rigol_can_waveform_generator.py` retries multiple
  command spellings/transfer strategies and treats `SYST:ERR?` as the source
  of truth for success/failure rather than command-level exceptions alone.
