# Changelog

## 0.2.0 – kayEi SpectrumStudio

The Ando OSA tool becomes a kayEi desktop app, in the look and with the plumbing of RiskStudio
and TwinStudio.

* **The app**: PySide6, the kayEi navy theme, an *Instrument* panel on the left (connection,
  sweep settings, analysis switches – all remembered between runs), pages for the
  **Spectrum** (KPI tiles, the plot with its markers, a sortable / copyable results table),
  the **Time-lapse** (progress, min/max/median envelope, peak wavelength and level trend,
  one row per measurement, `summary.csv`), the **Log** (every bus command at DEBUG) and the
  **Method**. Menus, shortcuts (F5 sweep, Esc stop, Ctrl+S quick save), drag-and-drop of CSV
  files, one running copy per user.
* **Portable Windows build**: `kayEi-SpectrumStudio-portable-<version>.zip` from GitHub
  Actions – unzip anywhere, run `kayei_spectrumstudio.exe`, no installer, no admin rights.
  Self-test, optional code signing, SHA-256 sums, release on a version tag. In-app update
  check (*Help ▸ Check for updates*) that downloads, verifies and unpacks the new zip next to
  the old folder. A Linux `.tar.gz` build on request.
* **Simulator**: a simulated AQ6317B with a 1064 nm fibre-laser spectrum (ASE, Raman Stokes
  and anti-Stokes, a side mode, a sensitivity-dependent noise floor, slow drift) – try the
  app without an instrument, and the CI runs the real packaged exe against it.
* **Instrument**: VISA backend fallback (NI-VISA / Keysight first, then pyvisa-py), a bus scan
  that lists every resource with its `*IDN?` so the right one can be picked, **continuous
  sweeps** (settings changes apply to the next sweep), `STP` on stop, a **command console**
  (*Instrument ▸ Send command…*), `REF=P` and the sweep timeout as preferences.
* **Analysis**: FWHM crossings interpolated between samples, **centre wavelength**, **total
  power**, results per trace, markers for the SNR reference, the anti-Stokes window and the
  power-content bands; analysis after every sweep is on by default and the power ranges are
  a small dialog instead of a modal form.
* **Files**: light "paper" PNGs by default (the dark screen look is a preference), the plain
  and the marked plot, analysis CSVs next to the traces, a tolerant CSV importer (comma,
  semicolon, tab, comments), quick saves into a timestamped session folder.
* **Headless**: `python -m ando_osa sweep|scan|analyze|version` – the same engine without Qt;
  the exe understands the same commands.
* Tests for the analysis, the driver (against a fake bus), the simulator, storage, the CLI,
  the desktop app (offscreen) and the update plumbing; ruff in CI.

## 0.1.0 – first release

PyQt5 GUI for Ando AQ63xx OSAs: sweeps, trace management, CW/pulsed, peak / FWHM / SNR /
SRS / power-content analysis, time-lapse with CSV + PNG per measurement.
