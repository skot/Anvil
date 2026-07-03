#!/usr/bin/env python3
"""Interactive bitaxeProto bringup console."""

import argparse
import glob
import sys
import time

import bitaxeraw
import mc3
import TPS546D24
import tps546D24_values
from pmbusconst import PMBUS_OPERATION


DEFAULT_CTRL_PORT = "/dev/cu.usbmodem90ea13d31"
DEFAULT_ASIC_PORT = "/dev/cu.usbmodem90ea13d33"
DEFAULT_CTRL_BAUDRATE = 115200
DEFAULT_ASIC_BAUDRATE = 115200


class Anvil:
    def __init__(self, ctrl_port, asic_port, ctrl_baudrate, asic_baudrate, timeout, debug=False):
        self.ctrl_port = ctrl_port
        self.asic_port = asic_port
        self.ctrl_baudrate = ctrl_baudrate
        self.asic_baudrate = asic_baudrate
        self.timeout = timeout
        self.debug = debug
        self.ctrl = None
        self.asic = None
        self.tps_initialized = False

    def run(self):
        print("Anvil - bitaxeProto bringup console")
        print(f"Control serial: {self.ctrl_port} @ {self.ctrl_baudrate}")
        print(f"ASIC serial:    {self.asic_port} @ {self.asic_baudrate}")
        print("")
        self.connect_serial_ports()
        print("")

        while True:
            print("Main menu")
            print("  1) Reconnect serial ports")
            print("  2) TPS546 voltage regulator")
            print("  3) Proto MC3 ASICs")
            print("  4) Fan")
            print("  5) List serial ports")
            print("  q) Quit")
            choice = input("> ").strip().lower()

            if choice == "1":
                self.connect_serial_ports()
            elif choice == "2":
                self.tps_menu()
            elif choice == "3":
                self.asic_menu()
            elif choice == "4":
                self.fan_menu()
            elif choice == "5":
                self.list_serial_ports()
            elif choice in ("q", "quit", "exit"):
                self.shutdown()
                return 0
            else:
                print("Unknown option")
            print("")

    def connect_serial_ports(self):
        serial_module = load_pyserial()
        if not serial_module:
            return False

        ctrl_ok = self.connect_control(serial_module)
        asic_ok = self.connect_asic(serial_module)
        if ctrl_ok and asic_ok:
            print("Serial ports ready.")
        else:
            print("Serial setup incomplete. Check the selected ports or run option 3 to list candidates.")
        return ctrl_ok and asic_ok

    def connect_control(self, serial_module=None):
        if self.ctrl and self.ctrl.is_open:
            self.ctrl.close()

        if serial_module is None:
            serial_module = load_pyserial()
            if not serial_module:
                return None

        try:
            self.ctrl = serial_module.Serial(
                port=self.ctrl_port,
                baudrate=self.ctrl_baudrate,
                timeout=self.timeout,
                dsrdtr=False,
                rtscts=False,
            )
            print("Connected control serial.")
            return self.ctrl
        except Exception as exc:
            print(f"Error opening control serial port: {exc}")
            self.ctrl = None
            return None

    def connect_asic(self, serial_module=None):
        if self.asic and self.asic.is_open:
            self.asic.close()

        if serial_module is None:
            serial_module = load_pyserial()
            if not serial_module:
                return None

        try:
            self.asic = serial_module.Serial(
                port=self.asic_port,
                baudrate=self.asic_baudrate,
                timeout=self.timeout,
                dsrdtr=False,
                rtscts=False,
            )
            print("Connected ASIC serial.")
            return self.asic
        except Exception as exc:
            print(f"Error opening ASIC serial port: {exc}")
            self.asic = None
            return None

    def require_control(self):
        if self.ctrl and self.ctrl.is_open:
            return self.ctrl
        print("Control serial is not connected yet.")
        return self.connect_control()

    def require_asic(self):
        if self.asic and self.asic.is_open:
            return self.asic
        print("ASIC serial is not connected yet.")
        return self.connect_asic()

    def tps_menu(self):
        while True:
            print("")
            print("TPS546 voltage regulator")
            print("  1) Initialize TPS546 for bitaxeProto")
            print("  2) Turn regulator ON")
            print("  3) Turn regulator OFF")
            print("  4) Status snapshot")
            print("  5) Poll status")
            print("  6) Read settings")
            print("  7) Clear faults")
            print("  b) Back")
            choice = input("TPS546> ").strip().lower()

            if choice == "1":
                self.tps_initialize()
            elif choice == "2":
                self.tps_on()
            elif choice == "3":
                self.tps_off()
            elif choice == "4":
                self.tps_status()
            elif choice == "5":
                self.tps_poll_status()
            elif choice == "6":
                self.tps_read_settings()
            elif choice == "7":
                self.tps_clear_faults()
            elif choice in ("b", "back", "q"):
                return
            else:
                print("Unknown option")

    def tps_initialize(self):
        ser = self.require_control()
        if not ser:
            return

        config = tps546D24_values.TPS546_CONFIG_PROTO
        print("")
        print("Initializing TPS546D24 with TPS546_CONFIG_PROTO...")
        TPS546D24.Init(ser, config)
        TPS546D24.init_disable(ser)
        TPS546D24.clear_faults(ser)
        TPS546D24.TPS546_status(ser)
        TPS546D24.write_settings(ser, config)
        TPS546D24.TPS546_status(ser)
        TPS546D24.enable_pin(ser, True, debug=self.debug)
        self.tps_initialized = True
        print("")
        print("TPS546 initialized. Regulator is configured and left OFF.")

    def tps_on(self):
        ser = self.require_control()
        if not ser:
            return
        if not self.tps_initialized:
            print("Warning: TPS546 has not been initialized in this Anvil session.")
            if not confirm("Turn on anyway?"):
                return

        TPS546D24.enable_pin(ser, True, debug=self.debug)
        time.sleep(0.1)
        TPS546D24.enable_regulator(ser)
        time.sleep(1.0)
        TPS546D24.TPS546_status(ser)

    def tps_off(self):
        ser = self.require_control()
        if not ser:
            return

        print("Disabling regulator...")
        TPS546D24.smb_write_byte(ser, PMBUS_OPERATION, TPS546D24.OPERATION_OFF)
        time.sleep(0.2)
        TPS546D24.TPS546_status(ser)

    def tps_status(self):
        ser = self.require_control()
        if ser:
            TPS546D24.TPS546_status(ser)

    def tps_poll_status(self):
        ser = self.require_control()
        if not ser:
            return

        interval = prompt_float("Poll interval seconds", default=5.0, minimum=0.25)
        print("Polling TPS546 status. Press Ctrl-C to stop.")
        try:
            while True:
                TPS546D24.TPS546_status(ser)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("")
            print("Stopped polling.")

    def tps_read_settings(self):
        ser = self.require_control()
        if ser:
            TPS546D24.read_settings(ser)

    def tps_clear_faults(self):
        ser = self.require_control()
        if ser:
            TPS546D24.clear_faults(ser)
            TPS546D24.TPS546_status(ser)

    def asic_menu(self):
        while True:
            print("")
            print("Proto MC3 ASICs")
            print("  1) Enable VDDIO 5V")
            print("  2) Disable VDDIO 5V")
            print("  3) Enumerate MC3 chain")
            print("  4) Raw ASIC UART TX test")
            print("  b) Back")
            choice = input("ASIC> ").strip().lower()

            if choice == "1":
                self.asic_vddio(True)
            elif choice == "2":
                self.asic_vddio(False)
            elif choice == "3":
                self.mc3_enumerate()
            elif choice == "4":
                self.asic_uart_tx_test()
            elif choice in ("b", "back", "q"):
                return
            else:
                print("Unknown option")

    def asic_vddio(self, enabled):
        ser = self.require_control()
        if not ser:
            return False

        state = bitaxeraw.GPIO_HIGH if enabled else bitaxeraw.GPIO_LOW
        label = "Enabling" if enabled else "Disabling"
        print(f"{label} VDDIO 5V on GPIO21...")
        bitaxeraw.gpio_set(ser, 0xAB, bitaxeraw.GPIO_VDDIO_5V_EN, state, debug=self.debug)
        time.sleep(0.1)
        return True

    def mc3_enumerate(self):
        ctrl = self.require_control()
        asic = self.require_asic()
        if not ctrl or not asic:
            return

        print("MC3 enumeration expects TPS core voltage on, VDDIO 5V on, and 25 MHz CLKI present.")
        if not confirm("Run MC3 enumeration now?"):
            return

        mc3.enumerate_chain(ctrl, asic, debug=self.debug)

    def asic_uart_tx_test(self):
        asic = self.require_asic()
        if not asic:
            return

        pattern = bytes([0x55, 0xAA, 0x00, 0xFF]) * 16
        print(f"Sending raw ASIC UART test pattern on {asic.port} @ {asic.baudrate} baud...")
        print(f"raw tx: [{bitaxeraw.prettyHex(pattern)}]")
        bytes_written = asic.write(pattern)
        asic.flush()
        print(f"Wrote {bytes_written} byte(s) to ASIC serial.")

    def fan_menu(self):
        while True:
            print("")
            print("Fan")
            print("  1) Set fan duty percent")
            print("  2) Set raw fan duty")
            print("  3) Read RPM")
            print("  4) Poll RPM")
            print("  b) Back")
            choice = input("Fan> ").strip().lower()

            if choice == "1":
                self.fan_set_percent()
            elif choice == "2":
                self.fan_set_raw_duty()
            elif choice == "3":
                self.fan_read_rpm()
            elif choice == "4":
                self.fan_poll_rpm()
            elif choice in ("b", "back", "q"):
                return
            else:
                print("Unknown option")

    def fan_set_percent(self):
        ser = self.require_control()
        if not ser:
            return

        percent = prompt_int("Fan duty percent", default=50, minimum=0, maximum=100)
        duty = round(percent * 255 / 100)
        print(f"Setting fan duty to {percent}% ({duty}/255)...")
        bitaxeraw.fan_set_duty(ser, 0xAC, duty, debug=self.debug)

    def fan_set_raw_duty(self):
        ser = self.require_control()
        if not ser:
            return

        duty = prompt_int("Fan raw duty", default=128, minimum=0, maximum=255)
        print(f"Setting fan duty to {duty}/255...")
        bitaxeraw.fan_set_duty(ser, 0xAC, duty, debug=self.debug)

    def fan_read_rpm(self):
        ser = self.require_control()
        if not ser:
            return None

        rpm = bitaxeraw.get_fan_rpm(ser, 0xAD, debug=self.debug)
        if rpm is not None:
            print(f"Fan RPM: {rpm}")
        return rpm

    def fan_poll_rpm(self):
        interval = prompt_float("Poll interval seconds", default=2.0, minimum=1.0)
        print("Polling fan RPM. Press Ctrl-C to stop.")
        try:
            while True:
                self.fan_read_rpm()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("")
            print("Stopped polling.")

    def list_serial_ports(self):
        port_info = serial_port_info()
        ports = sorted(port_info) if port_info else sorted(
            glob.glob("/dev/cu.usb*")
            + glob.glob("/dev/tty.usb*")
            + glob.glob("/dev/cu.SLAB*")
            + glob.glob("/dev/tty.SLAB*")
        )
        if not ports:
            print("No common USB serial ports found.")
            return
        for port in ports:
            markers = []
            if port == self.ctrl_port:
                markers.append("control")
            if port == self.asic_port:
                markers.append("ASIC")
            marker = f" ({', '.join(markers)})" if markers else ""
            description = f" - {port_info[port]}" if port_info and port_info.get(port) else ""
            print(f"  {port}{marker}{description}")

    def shutdown(self):
        if self.ctrl and self.ctrl.is_open:
            self.ctrl.close()
            print("Closed control serial.")
        if self.asic and self.asic.is_open:
            self.asic.close()
            print("Closed ASIC serial.")


def confirm(prompt):
    response = input(f"{prompt} [y/N] ").strip().lower()
    return response in ("y", "yes")


def load_pyserial():
    try:
        import serial
    except ImportError:
        print("pyserial is not installed. Install it with: python -m pip install pyserial")
        return None

    if not hasattr(serial, "Serial"):
        print("The imported serial module is not pyserial.")
        print("Install pyserial with: python -m pip install pyserial")
        return None

    return serial


def serial_port_info():
    try:
        from serial.tools import list_ports
    except Exception:
        return {}

    info = {}
    for port in list_ports.comports():
        info[port.device] = port.description
    return info


def prompt_float(prompt, default, minimum=None):
    while True:
        response = input(f"{prompt} [{default}]: ").strip()
        if not response:
            return default
        try:
            value = float(response)
        except ValueError:
            print("Enter a number.")
            continue
        if minimum is not None and value < minimum:
            print(f"Enter a value >= {minimum}.")
            continue
        return value


def prompt_int(prompt, default, minimum=None, maximum=None):
    while True:
        response = input(f"{prompt} [{default}]: ").strip()
        if not response:
            return default
        try:
            value = int(response, 0)
        except ValueError:
            print("Enter a decimal or 0x-prefixed hex value.")
            continue
        if minimum is not None and value < minimum:
            print(f"Enter a value >= {minimum}.")
            continue
        if maximum is not None and value > maximum:
            print(f"Enter a value <= {maximum}.")
            continue
        return value


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Interactive bitaxeProto bringup console.")
    parser.add_argument(
        "--ctrl-port",
        default=DEFAULT_CTRL_PORT,
        help=f"ESP32 control serial port, default: {DEFAULT_CTRL_PORT}",
    )
    parser.add_argument(
        "--asic-port",
        default=DEFAULT_ASIC_PORT,
        help=f"ESP32 ASIC serial port, default: {DEFAULT_ASIC_PORT}",
    )
    parser.add_argument(
        "--ctrl-baudrate",
        "--baudrate",
        type=int,
        default=DEFAULT_CTRL_BAUDRATE,
        help=f"Control serial baudrate, default: {DEFAULT_CTRL_BAUDRATE}",
    )
    parser.add_argument(
        "--asic-baudrate",
        type=int,
        default=DEFAULT_ASIC_BAUDRATE,
        help=f"ASIC serial baudrate, default: {DEFAULT_ASIC_BAUDRATE}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Control serial timeout in seconds, default: 1.0",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw control packets for GPIO operations.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    app = Anvil(
        ctrl_port=args.ctrl_port,
        asic_port=args.asic_port,
        ctrl_baudrate=args.ctrl_baudrate,
        asic_baudrate=args.asic_baudrate,
        timeout=args.timeout,
        debug=args.debug,
    )
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
