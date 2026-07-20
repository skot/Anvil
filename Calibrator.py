#!/usr/bin/env python3
"""Automate TPS546 current telemetry sweeps with a Rigol DL3021 load."""

import argparse
import csv
import math
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import TPS546D24


DEFAULT_CTRL_PORT = "/dev/cu.usbmodem90ea13d31"
DEFAULT_CTRL_BAUDRATE = 115200
DEFAULT_LOAD_HOST = "192.168.1.176"
DEFAULT_LOAD_PORT = 5555
DL3021_MAX_CURRENT_A = 40.0
DL3021_MAX_POWER_W = 200.0
PROJECT_DIR = Path(__file__).resolve().parent

CSV_FIELDS = (
    "timestamp",
    "direction",
    "set_current_a",
    "load_current_a",
    "load_voltage_v",
    "load_power_w",
    "tps_vin_v",
    "tps_vout_v",
    "tps_iout_a",
    "vr_temp_c",
    "sample_count",
)


class RigolDL3021:
    """Small SCPI client for a DL3021 raw TCP connection."""

    def __init__(self, host, port=DEFAULT_LOAD_PORT, timeout=5.0, sock=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = sock
        self._receive_buffer = b""

    def connect(self):
        if self.sock is None:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def write(self, command):
        if self.sock is None:
            raise RuntimeError("DL3021 is not connected")
        self.sock.sendall((command.rstrip() + "\n").encode("ascii"))

    def query(self, command):
        self.write(command)
        while b"\n" not in self._receive_buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("DL3021 closed the SCPI connection")
            self._receive_buffer += chunk
        response, self._receive_buffer = self._receive_buffer.split(b"\n", 1)
        return response.decode("ascii", errors="replace").strip()

    def query_float(self, command):
        response = self.query(command)
        try:
            value = float(response)
        except ValueError as exc:
            raise RuntimeError(f"Unexpected DL3021 response to {command}: {response!r}") from exc
        if not math.isfinite(value):
            raise RuntimeError(f"Non-finite DL3021 response to {command}: {response!r}")
        return value

    def identify(self):
        return self.query("*IDN?")

    def configure_cc(self):
        self.write(":SOURCE:INPUT:STATE OFF")
        self.write(":SOURCE:FUNCTION:MODE FIXED")
        self.write(":SOURCE:FUNCTION CURRENT")
        self.write(":SOURCE:TRANSIENT:STATE OFF")
        self.write(":SOURCE:CURRENT:RANGE 40")
        self.write(":SOURCE:CURRENT:VON MINIMUM")
        self.write(":SOURCE:CURRENT:ILIM 40")
        self.write(":SOURCE:CURRENT:LEVEL:IMMEDIATE 0")

    def verify_cc_configuration(self):
        mode = self.query(":SOURCE:FUNCTION:MODE?").upper()
        function = self.query(":SOURCE:FUNCTION?").upper()
        transient = self.query(":SOURCE:TRANSIENT:STATE?")
        current_range = self.query_float(":SOURCE:CURRENT:RANGE?")
        # DL3021A firmware reports WAV while the front panel is displaying the
        # waveform screen, even after accepting FUNC:MODE FIX without error.
        if mode not in ("FIX", "FIXED", "WAV", "WAVE"):
            raise RuntimeError(f"DL3021 is in an incompatible mode (reported {mode!r})")
        if function not in ("CC", "CURR", "CURRENT"):
            raise RuntimeError(f"DL3021 did not enter CC mode (reported {function!r})")
        if transient not in ("0", "OFF"):
            raise RuntimeError("DL3021 transient generator is still enabled")
        if current_range < DL3021_MAX_CURRENT_A:
            raise RuntimeError(
                f"DL3021 current range is only {current_range:g} A; expected the 40 A range"
            )
        error = self.query(":SYSTEM:ERROR?")
        if not error.lstrip().startswith("0,"):
            raise RuntimeError(f"DL3021 configuration error: {error}")

    def set_current(self, current_a):
        self.write(f":SOURCE:CURRENT:LEVEL:IMMEDIATE {current_a:.6f}")

    def current_setpoint(self):
        return self.query_float(":SOURCE:CURRENT:LEVEL:IMMEDIATE?")

    def set_input(self, enabled):
        state = "ON" if enabled else "OFF"
        self.write(f":SOURCE:INPUT:STATE {state}")

    def measure(self):
        return {
            "current": self.query_float(":MEASURE:CURRENT?"),
            "voltage": self.query_float(":MEASURE:VOLTAGE?"),
            "power": self.query_float(":MEASURE:POWER?"),
        }


def inclusive_range(start, stop, step):
    """Return an inclusive ascending range without cumulative float drift."""
    if step <= 0:
        raise ValueError("Current step must be greater than zero")
    if stop < start:
        raise ValueError("Stop current must be greater than or equal to start current")

    count = int(math.floor((stop - start) / step + 1e-9))
    values = [start + index * step for index in range(count + 1)]
    if not math.isclose(values[-1], stop, rel_tol=0.0, abs_tol=1e-9):
        values.append(stop)
    return values


def build_sweep(start, stop, step, sweep):
    ascending = inclusive_range(start, stop, step)
    descending = list(reversed(ascending))
    if sweep == "up":
        return [("up", value) for value in ascending]
    if sweep == "down":
        return [("down", value) for value in descending]
    if sweep == "both":
        return (
            [("up", value) for value in ascending]
            + [("down", value) for value in descending]
        )
    raise ValueError(f"Unknown sweep direction: {sweep}")


def average_dicts(samples):
    if not samples:
        raise ValueError("At least one sample is required")
    return {
        name: sum(sample[name] for sample in samples) / len(samples)
        for name in samples[0]
    }


def collect_point(load, control_serial, sample_count, sample_interval, debug=False):
    samples = []
    for index in range(sample_count):
        tps = TPS546D24.read_telemetry_sample(control_serial, debug=debug)
        rigol = load.measure()
        samples.append(
            {
                "load_current_a": rigol["current"],
                "load_voltage_v": rigol["voltage"],
                "load_power_w": rigol["power"],
                "tps_vin_v": tps["vin"],
                "tps_vout_v": tps["vout"],
                "tps_iout_a": tps["iout"],
                "vr_temp_c": tps["vr_temp"],
            }
        )
        if index + 1 < sample_count and sample_interval:
            time.sleep(sample_interval)
    return average_dicts(samples)


def check_safety(measurement, set_current, args):
    if measurement["vr_temp_c"] > args.max_vr_temp:
        raise RuntimeError(
            f"VR temperature {measurement['vr_temp_c']:.1f} °C exceeds "
            f"the {args.max_vr_temp:.1f} °C limit"
        )
    if abs(measurement["load_current_a"] - set_current) > args.max_current_error:
        raise RuntimeError(
            f"Measured load current {measurement['load_current_a']:.3f} A differs from "
            f"the {set_current:.3f} A setpoint by more than "
            f"{args.max_current_error:.3f} A"
        )
    if measurement["tps_vout_v"] < args.min_vout:
        raise RuntimeError(
            f"TPS546 VOUT fell to {measurement['tps_vout_v']:.3f} V, "
            f"below the {args.min_vout:.3f} V limit"
        )
    if measurement["load_power_w"] > args.max_load_power:
        raise RuntimeError(
            f"Load power {measurement['load_power_w']:.1f} W exceeds "
            f"the {args.max_load_power:.1f} W limit"
        )


def monitor_soak(load, control_serial, set_current, seconds, args):
    print(f"Holding at {set_current:g} A for {seconds:g} s with safety monitoring...")
    deadline = time.monotonic() + seconds
    while True:
        measurement = collect_point(load, control_serial, 1, 0.0, debug=args.debug)
        check_safety(measurement, set_current, args)
        remaining = max(0.0, deadline - time.monotonic())
        print(
            f"  soak: {remaining:>6.1f} s remaining, "
            f"load={measurement['load_current_a']:.3f} A, "
            f"VOUT={measurement['tps_vout_v']:.3f} V, "
            f"VR_TEMP={measurement['vr_temp_c']:.1f} °C"
        )
        if remaining <= 0:
            return
        time.sleep(min(args.soak_check_interval, remaining))


def default_output_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_DIR / "local" / f"tps546_calibration_{timestamp}.csv"


def open_control_serial(args):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required; install it with: python3 -m pip install pyserial") from exc

    try:
        return serial.Serial(
            port=args.ctrl_port,
            baudrate=args.ctrl_baudrate,
            timeout=args.serial_timeout,
            dsrdtr=False,
            rtscts=False,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not open control serial port {args.ctrl_port}. "
            "Quit Anvil first so it releases the port."
        ) from exc


def validate_args(args):
    if args.start_current < 0:
        raise ValueError("Start current cannot be negative")
    if args.stop_current > DL3021_MAX_CURRENT_A:
        raise ValueError(f"Stop current cannot exceed the DL3021 limit of {DL3021_MAX_CURRENT_A:g} A")
    if args.stop_current < args.start_current:
        raise ValueError("Stop current must be greater than or equal to start current")
    if args.current_step <= 0:
        raise ValueError("Current step must be greater than zero")
    if args.samples < 1:
        raise ValueError("Sample count must be at least one")
    if args.sample_interval < 0 or args.settle_seconds < 0 or args.top_soak_seconds < 0:
        raise ValueError("Timing values cannot be negative")
    if args.soak_check_interval <= 0:
        raise ValueError("Soak check interval must be greater than zero")
    if not 0 < args.max_load_power <= DL3021_MAX_POWER_W:
        raise ValueError(f"Maximum load power must be between 0 and {DL3021_MAX_POWER_W:g} W")
    if args.max_current_error <= 0:
        raise ValueError("Maximum current error must be greater than zero")
    if args.max_vr_temp <= 0 or args.min_vout <= 0:
        raise ValueError("VR temperature and VOUT safety limits must be greater than zero")


def confirm_run(args, points, output_path):
    print("TPS546 current calibration sweep")
    print(f"  DL3021:       {args.load_host}:{args.load_port}")
    print(f"  Control port: {args.ctrl_port} @ {args.ctrl_baudrate}")
    print(
        f"  Sweep:        {args.sweep}, {args.start_current:g} A to "
        f"{args.stop_current:g} A in {args.current_step:g} A steps ({len(points)} points)"
    )
    print(f"  Samples:      {args.samples} per point, {args.sample_interval:g} s apart")
    print(f"  Settle:       {args.settle_seconds:g} s after each load change")
    print(f"  CSV output:   {output_path}")
    print("")
    print("The TPS546 must already be initialized and enabled by Anvil.")
    print("Calibrator will control the electronic load and will turn its input off on exit.")
    if args.yes:
        return True
    response = input("Begin sweep? [y/N]: ").strip().lower()
    return response in ("y", "yes")


def run_calibration(args):
    validate_args(args)
    points = build_sweep(
        args.start_current,
        args.stop_current,
        args.current_step,
        args.sweep,
    )
    output_path = Path(args.output) if args.output else default_output_path()
    if not confirm_run(args, points, output_path):
        print("Cancelled.")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    load = RigolDL3021(args.load_host, args.load_port, args.load_timeout)
    control_serial = None
    load_connected = False

    try:
        load.connect()
        load_connected = True
        identity = load.identify()
        print(f"Connected load: {identity}")
        if "DL3021" not in identity.upper():
            raise RuntimeError(f"Expected a Rigol DL3021, received: {identity}")

        control_serial = open_control_serial(args)
        initial_tps = TPS546D24.read_telemetry_sample(control_serial, debug=args.debug)
        print(
            f"TPS546 initial: VIN={initial_tps['vin']:.3f} V, "
            f"VOUT={initial_tps['vout']:.3f} V, "
            f"IOUT={initial_tps['iout']:.3f} A, "
            f"VR_TEMP={initial_tps['vr_temp']:.3f} °C"
        )
        if initial_tps["vout"] < args.min_vout:
            raise RuntimeError(
                f"TPS546 VOUT is only {initial_tps['vout']:.3f} V; "
                "initialize and enable it in Anvil before running Calibrator"
            )

        load.configure_cc()
        load.verify_cc_configuration()
        load.set_input(True)

        with output_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            output_file.flush()

            print("")
            print("Dir  Set A  Load A  Load V  Power W  TPS IOUT A  TPS VOUT V  VR Temp C")
            print("---  -----  ------  ------  -------  ----------  ----------  ---------")
            top_soak_complete = False
            for direction, set_current in points:
                load.set_current(set_current)
                confirmed_setpoint = load.current_setpoint()
                if not math.isclose(confirmed_setpoint, set_current, rel_tol=0.0, abs_tol=0.001):
                    raise RuntimeError(
                        f"DL3021 accepted a {confirmed_setpoint:.3f} A setpoint instead of "
                        f"the requested {set_current:.3f} A"
                    )
                if args.settle_seconds:
                    time.sleep(args.settle_seconds)
                if (
                    not top_soak_complete
                    and direction == "down"
                    and math.isclose(set_current, args.stop_current)
                    and args.top_soak_seconds > 0
                ):
                    monitor_soak(
                        load,
                        control_serial,
                        set_current,
                        args.top_soak_seconds,
                        args,
                    )
                    top_soak_complete = True
                averages = collect_point(
                    load,
                    control_serial,
                    args.samples,
                    args.sample_interval,
                    debug=args.debug,
                )

                check_safety(averages, set_current, args)

                row = {
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "direction": direction,
                    "set_current_a": set_current,
                    **averages,
                    "sample_count": args.samples,
                }
                writer.writerow(row)
                output_file.flush()
                print(
                    f"{direction:>3}  {set_current:>5.2f}  "
                    f"{averages['load_current_a']:>6.3f}  "
                    f"{averages['load_voltage_v']:>6.3f}  "
                    f"{averages['load_power_w']:>7.3f}  "
                    f"{averages['tps_iout_a']:>10.3f}  "
                    f"{averages['tps_vout_v']:>10.3f}  "
                    f"{averages['vr_temp_c']:>9.3f}"
                )

        print(f"\nSweep complete. Results saved to {output_path}")
        return 0
    except KeyboardInterrupt:
        print("\nSweep interrupted by user.", file=sys.stderr)
        return 130
    except (ConnectionError, OSError, RuntimeError, ValueError) as exc:
        print(f"\nCalibration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if load_connected:
            try:
                load.set_current(0.0)
                load.set_input(False)
                print("DL3021 current set to 0 A and input turned OFF.")
            except Exception as exc:
                print(f"Warning: could not turn the DL3021 input off: {exc}", file=sys.stderr)
        load.close()
        if control_serial is not None:
            control_serial.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Sweep a Rigol DL3021 load and average TPS546 current telemetry."
    )
    parser.add_argument("--load-host", default=DEFAULT_LOAD_HOST)
    parser.add_argument("--load-port", type=int, default=DEFAULT_LOAD_PORT)
    parser.add_argument("--load-timeout", type=float, default=5.0)
    parser.add_argument("--ctrl-port", default=DEFAULT_CTRL_PORT)
    parser.add_argument("--ctrl-baudrate", type=int, default=DEFAULT_CTRL_BAUDRATE)
    parser.add_argument("--serial-timeout", type=float, default=1.0)
    parser.add_argument("--start-current", type=float, default=0.0)
    parser.add_argument("--stop-current", type=float, default=20.0)
    parser.add_argument("--current-step", type=float, default=1.0)
    parser.add_argument("--sweep", choices=("up", "down", "both"), default="up")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--top-soak-seconds", type=float, default=0.0)
    parser.add_argument("--soak-check-interval", type=float, default=2.0)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--max-vr-temp", type=float, default=100.0)
    parser.add_argument("--min-vout", type=float, default=0.5)
    parser.add_argument("--max-load-power", type=float, default=190.0)
    parser.add_argument("--max-current-error", type=float, default=0.25)
    parser.add_argument("--output", help="CSV output path (default: timestamped file in local/)")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation")
    parser.add_argument("--debug", action="store_true", help="Print low-level TPS546 traffic")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        return run_calibration(parse_args(argv))
    except ValueError as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
