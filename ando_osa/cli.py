"""Headless command line – the same engine as the desktop app, CI-friendly.

    python -m ando_osa scan                          # list VISA resources and their *IDN?
    python -m ando_osa sweep --start 1000 --stop 1500 --res 0.1 --sens SMID --out trace.csv
    python -m ando_osa sweep --simulate --out demo.csv --png demo.png --snr --srs
    python -m ando_osa analyze trace.csv --range 1060:1070 --json
    python -m ando_osa version
    python -m ando_osa                               # no command: the desktop app

The packaged ``kayei_spectrumstudio.exe`` understands the same commands.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import APP_NAME, __version__
from .analysis import DEFAULT_OPTIONS, analyze, format_value, ordered
from .instrument import RESOLUTIONS_NM, SENSITIVITY_CMDS, TRACES, validate_sweep_range

COMMANDS = ("scan", "sweep", "analyze", "version", "app")
SWEEP_TIMEOUT_S = 40.0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ando-osa", description=f"{APP_NAME} – headless commands")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("version", help="print the version")
    sub.add_parser("app", help="start the desktop app").add_argument("args", nargs=argparse.REMAINDER)
    s = sub.add_parser("scan", help="list VISA resources and what answers *IDN?")
    s.add_argument("--backend", default=None, help="pyvisa backend, e.g. @py")
    s = sub.add_parser("sweep", help="one sweep, saved as CSV (+ analysis, + PNG)")
    s.add_argument("--start", type=float, default=1000.0, help="start wavelength (nm)")
    s.add_argument("--stop", type=float, default=1500.0, help="stop wavelength (nm)")
    s.add_argument("--res", default="0.1", choices=RESOLUTIONS_NM, help="resolution (nm)")
    s.add_argument("--sens", default="SMID", choices=SENSITIVITY_CMDS, help="sensitivity")
    s.add_argument("--trace", default="A", choices=TRACES)
    s.add_argument("--resource", default=None, help="VISA resource name (default: first Ando found)")
    s.add_argument("--backend", default=None, help="pyvisa backend, e.g. @py")
    s.add_argument("--simulate", action="store_true", help="use the built-in simulator instead of an instrument")
    s.add_argument("--timeout", type=float, default=SWEEP_TIMEOUT_S, help="sweep timeout (s)")
    s.add_argument("--no-ref-peak", action="store_true", help="do not send REF=P after the sweep")
    s.add_argument("--out", required=True, help="CSV file for the trace (…_anal.csv gets the analysis)")
    s.add_argument("--png", default=None, help="also save a plot")
    _analysis_flags(s)
    s = sub.add_parser("analyze", help="analyse a trace CSV")
    s.add_argument("csv")
    s.add_argument("--json", action="store_true", help="print JSON instead of a table")
    s.add_argument("--out", default=None, help="write the analysis CSV here")
    _analysis_flags(s)
    return p


def _analysis_flags(s: argparse.ArgumentParser) -> None:
    s.add_argument("--no-peak", action="store_true", help="skip the peak search")
    s.add_argument("--no-fwhm", action="store_true", help="skip the FWHM")
    s.add_argument("--no-total", action="store_true", help="skip the total power")
    s.add_argument("--snr", action="store_true", help="SNR (highest level outside ±10 nm of the peak)")
    s.add_argument("--srs", action="store_true", help="SRS: anti-Stokes suppression")
    s.add_argument("--range", action="append", default=[], metavar="START:STOP",
                   help="power-content range in nm (up to five)")


def options_from_args(args) -> dict:
    opts = dict(DEFAULT_OPTIONS)
    opts.update({"Peak Search": not args.no_peak, "FWHM": not args.no_fwhm, "Total Power": not args.no_total,
                 "SNR": bool(args.snr), "SRS": bool(args.srs)})
    ranges = []
    for r in args.range:
        try:
            a, b = (float(x) for x in r.split(":"))
        except ValueError:
            raise SystemExit(f"--range wants START:STOP in nm, got {r!r}")
        ranges.append({"start": a, "stop": b})
    opts["Power Content"] = ranges
    return opts


def _print_results(results: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(results, indent=1))
        return
    for k, v in ordered(results):
        print(f"{k:<20} {format_value(k, v)}")


def open_osa(args):
    if getattr(args, "simulate", False):
        from .simulator import SimulatedOSA
        return SimulatedOSA(sweep_seconds=0.2)
    from .instrument import AndoOSA, open_resource_manager
    rm = open_resource_manager(getattr(args, "backend", None))
    osa = AndoOSA.open(rm, args.resource) if getattr(args, "resource", None) else AndoOSA.find(rm)
    if osa is None:
        raise SystemExit("No Ando OSA found. Run 'scan' to see what is on the bus, or use --simulate.")
    return osa


def cmd_scan(args) -> int:
    from .instrument import is_ando, open_resource_manager, probe_resources
    rm = open_resource_manager(args.backend)
    found = probe_resources(rm)
    if not found:
        print("No VISA resources found.")
        return 1
    for name, idn in found:
        tag = "\t<- Ando OSA" if is_ando(idn) else ""
        print(f"{name}\t{idn or '(no *IDN? answer)'}{tag}")
    return 0


def cmd_sweep(args) -> int:
    validate_sweep_range(args.start, args.stop)
    osa = open_osa(args)
    try:
        osa.configure_sweep(args.start, args.stop, args.res, args.sens)
        osa.set_active_trace(args.trace)
        osa.start_single_sweep()
        deadline = time.monotonic() + args.timeout
        while osa.sweep_in_progress():
            if time.monotonic() > deadline:
                osa.abort_sweep()
                raise SystemExit(f"Sweep did not finish within {args.timeout:.0f} s.")
            time.sleep(0.2)
        if not args.no_ref_peak:
            osa.set_reference_to_peak()
        w, lv = osa.read_trace(args.trace)
    finally:
        osa.close()
    from .storage import write_analysis_csv, write_trace_csv
    out = Path(args.out)
    write_trace_csv(out, w, lv)
    results, overlays = analyze(w, lv, options_from_args(args))
    write_analysis_csv(out.with_name(out.stem + "_anal.csv"), results)
    if args.png:
        from .plots import render_png
        render_png(args.png, [(args.trace, w, lv)], {args.trace: overlays}, title=out.stem)
    print(f"{len(w)} points -> {out}")
    _print_results(results, False)
    return 0


def cmd_analyze(args) -> int:
    from .storage import read_trace_csv, write_analysis_csv
    w, lv = read_trace_csv(args.csv)
    results, _ = analyze(w, lv, options_from_args(args))
    if args.out:
        write_analysis_csv(args.out, results)
    _print_results(results, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS or argv[0] == "app":
        rest = argv[1:] if argv and argv[0] == "app" else argv
        from osa_qt.app import main as app_main
        return app_main([sys.argv[0], *rest])
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    args = _parser().parse_args(argv)
    if args.command == "version":
        print(f"{APP_NAME} {__version__}")
        return 0
    try:
        return {"scan": cmd_scan, "sweep": cmd_sweep, "analyze": cmd_analyze}[args.command](args)
    except (ValueError, OSError, RuntimeError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
