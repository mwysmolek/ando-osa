"""The Method page and the README share this text: what the numbers mean and what to verify
on your instrument."""

METHOD_MD = """# How the numbers are computed

Read this before trusting a value. Every analysis works on the trace as the instrument
delivered it (wavelength in nm, level in dBm); nothing is smoothed or fitted.

## Peak search
Wavelength and level of the **global maximum** of the trace.

## FWHM and centre wavelength
Width between the **outermost −3 dB crossings** relative to the peak, with the crossing
points **interpolated linearly** between neighbouring samples. With several peaks above the
threshold this spans all of them – it is not a per-peak fit. The centre wavelength is the
midpoint of the two crossings.

## SNR
Peak level minus the **highest level found outside a ±10 nm window** around the peak.
Strictly a side-mode-suppression-style figure, not a noise-floor SNR. The marker shows which
sample set the reference.

## SRS (anti-Stokes)
Peak level minus the maximum level within **±5 nm of the expected anti-Stokes wavelength**
for the 13.2 THz Raman shift of fused silica: λ<sub>AS</sub> = λ<sub>p</sub> / (1 + Δν·λ<sub>p</sub>/c).
The anti-Stokes line sits at a *shorter* wavelength than the pump. (An earlier version of
this tool searched on the Stokes side despite the label; this was corrected.)

## Total power
10·log<sub>10</sub> of the **sum of the linear powers of all samples**, in dBm. It is a
sample sum, not an integral: it depends on the sampling step and on the resolution
bandwidth, so compare traces taken with the same settings only.

## Power content
Percentage of the total linear power that falls into each of up to five wavelength ranges.

## Constants
Windows (±10 nm, ±5 nm), the Raman shift (13.2 THz) and the −3 dB drop live at the top of
`ando_osa/analysis.py`.

# Things to verify on your instrument

This software was developed against one instrument; a few command-set details are worth
checking against your unit's programming manual:

* **Active trace C** is selected with `ACTV2` (per the AQ6317 manual).
* After each sweep the tool issues `REF=P` (reference level to peak) – switch it off in
  *Preferences* if you keep a fixed reference level.
* A sweep is started with `SGL` and stopped with `STP`; completion is polled with `SWEEP?`
  (0 = stopped). The timeout is 40 s by default (*Preferences*) – raise it for very slow
  high-sensitivity sweeps over wide spans.
* The accepted wavelength range is limited to 350–1750 nm (`ando_osa/instrument.py`);
  tighten it to match your model if desired.
* *Instrument ▸ Send command…* lets you try any command and read the answer; the Log page
  shows everything that went over the bus.
"""
