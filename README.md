# Ando OSA Control

A PyQt5 desktop application for controlling **Ando AQ63xx-series optical
spectrum analyzers** (AQ6315, AQ6317 and similar) over GPIB/VISA, with live
plotting, trace analysis and automated time-lapse acquisition.

![screenshot placeholder](docs/screenshot.png)

## Features

- **Sweep control** — start/stop wavelength, resolution and sensitivity, run
  in a background thread so the GUI never freezes; abortable at any time.
- **Trace management** — display/blank and set write/fix/max/min/average
  modes for traces A, B and C; select the active trace.
- **CW / pulsed measurement modes** with configurable peak hold.
- **Analysis** — peak search, FWHM, SNR, SRS (anti-Stokes) suppression and
  up to five power-content ranges, with markers drawn on the plot.
- **Time-lapse** — repeated sweeps at a fixed interval; every measurement is
  saved as CSV + PNG into a timestamped folder, with a live min/max/median
  plot; fully abortable.
- **Data handling** — CSV import, save, and one-click "quick save" with
  auto-numbered files.

## Requirements

- Python 3.8+
- A VISA backend:
  - Windows: [NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html)
    or Keysight IO Libraries, plus a GPIB adapter (e.g. NI GPIB-USB-HS).
  - Linux: `pyvisa-py` with `linux-gpib`, or NI-VISA.
- Python packages: `pyvisa`, `PyQt5`, `numpy`, `matplotlib`
  (installed automatically below).

## Installation

```bash
git clone <this-repo>
cd ando
pip install .
```

Or for development:

```bash
pip install -e .
```

## Usage

```bash
ando-osa
# or
python -m ando_osa
```

On startup the application scans all VISA resources and connects to the
first instrument whose `*IDN?` response contains "ANDO". Use
**Connect/Disconnect** to re-scan manually.

### Output files

| File | Content |
|------|---------|
| `measurement_NNN.csv` / `.png` | One time-lapse measurement (per-run timestamped subfolder) |
| `XNNNN.csv` / `.png` | Quick-save trace data and plot |
| `*_anal.csv` | Analysis results (metric, value) for the saved trace |
| `*_overlay.png` | Plot variant with analysis markers |

## Analysis definitions (read before trusting the numbers)

- **Peak Search** — wavelength and level of the global maximum.
- **FWHM** — width between the *outermost* −3 dB crossings relative to the
  peak. With multiple peaks above the threshold this spans all of them; it
  is not a per-peak fit.
- **SNR** — peak level minus the highest level found outside a ±10 nm window
  around the peak. Strictly a side-mode-suppression-style figure, not a
  noise-floor SNR.
- **SRS (Anti-Stokes)** — peak level minus the maximum level within ±5 nm of
  the expected anti-Stokes wavelength for the 13.2 THz Raman shift of fused
  silica: λ<sub>AS</sub> = λ<sub>p</sub> / (1 + Δν·λ<sub>p</sub>/c).
  *Note: an earlier version of this tool searched on the Stokes (longer
  wavelength) side despite the label; this was corrected.*
- **Power Content** — percentage of total linear power within each
  wavelength range.

Constants (windows, Raman shift, −3 dB drop) live at the top of
[`ando_osa/analysis.py`](ando_osa/analysis.py).

## Things to verify on your instrument

This software was developed against one instrument; a couple of command-set
details are worth checking against your unit's programming manual:

- **Active trace C** is selected with `ACTV2` (per the AQ6317 manual).
- After each sweep the tool issues `REF=P` (reference level to peak).
- Sweep completion is polled with `SWEEP?` (0 = stopped), with a 40 s
  timeout — increase `SWEEP_TIMEOUT_S` in `ando_osa/workers.py` for very
  slow high-sensitivity sweeps over wide spans.
- The accepted wavelength range is limited to 350–1750 nm
  (`ando_osa/instrument.py`); tighten it to match your model if desired.

## Project layout

```
ando_osa/
  instrument.py   # thread-safe VISA driver (no GUI dependencies besides pyvisa)
  workers.py      # QThread workers for sweep and time-lapse
  analysis.py     # pure numpy trace analysis
  gui.py          # PyQt5 main window and dialogs
  __main__.py     # entry point
```

The driver and analysis modules have no GUI dependency, so they can be used
headlessly in your own scripts:

```python
import pyvisa
from ando_osa.instrument import AndoOSA

osa = AndoOSA.find(pyvisa.ResourceManager())
osa.configure_sweep(1000, 1500, "0.1", "SMID")
osa.start_single_sweep()
while osa.sweep_in_progress():
    ...
wavelengths, levels = osa.read_trace("A")
```

## License

[MIT](LICENSE)
