#!/usr/bin/env python3
"""Interactive bitaxeBonanza-1004x bringup console."""

import argparse
import glob
import sys
import time

import bitaxeraw
import bridge_loader
import bzm2
import TPS546D24
import tps546D24_values
from pmbusconst import PMBUS_OPERATION


DEFAULT_CTRL_PORT = "/dev/cu.usbmodem2553f62b1"
DEFAULT_ASIC_PORT = "/dev/cu.usbmodem2553f62b3"
DEFAULT_CTRL_BAUDRATE = 115200
DEFAULT_ASIC_BAUDRATE = 2000000
IO_TEST_MAX_CORE_VOLTS = 0.2  # Discharged stack/tap threshold, not a VDD operating point.


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
        self.bzm_chip_ids = []
        self.bzm_sequence = 0
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False

    def run(self):
        print("Anvil - bitaxeBonanza-1004x bringup console")
        print(f"Control serial: {self.ctrl_port} @ {self.ctrl_baudrate}")
        print(f"ASIC serial:    {self.asic_port} @ {self.asic_baudrate}")
        print("")
        self.connect_serial_ports()
        print("")

        while True:
            print("Main menu")
            print("  1) Reconnect serial ports")
            print("  2) TPS546 voltage regulator")
            print("  3) Bonanza BZM2 ASICs")
            print("  4) Fan")
            print("  5) ESP32 board diagnostics")
            print("  6) List serial ports")
            print("  7) Read domain/chip voltages")
            print("  8) RP2040 bridge firmware")
            print("  q) Quit")
            choice = input("> ").strip().lower()

            try:
                if choice == "1":
                    self.connect_serial_ports()
                elif choice == "2":
                    self.tps_menu()
                elif choice == "3":
                    self.asic_menu()
                elif choice == "4":
                    self.fan_menu()
                elif choice == "5":
                    self.board_diagnostics()
                elif choice == "6":
                    self.list_serial_ports()
                elif choice == "7":
                    self.read_domain_voltages()
                elif choice == "8":
                    self.bridge_firmware_menu()
                elif choice in ("q", "quit", "exit"):
                    self.shutdown()
                    return 0
                else:
                    print("Unknown option")
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"Operation failed: {exc}")
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
            print("Serial setup incomplete. Check the selected ports or use List serial ports.")
        return ctrl_ok and asic_ok

    def connect_control(self, serial_module=None):
        self.tps_initialized = False
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
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
            print("  1) Initialize TPS546 for bitaxeBonanza-1004x")
            print("  2) Turn regulator ON")
            print("  3) Turn regulator OFF")
            print("  4) Status snapshot")
            print("  5) Poll status")
            print("  6) Read settings")
            print("  7) Clear faults")
            print("  8) Average telemetry samples")
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
            elif choice == "8":
                self.tps_average_telemetry()
            elif choice in ("b", "back", "q"):
                return
            else:
                print("Unknown option")

    def tps_initialize(self):
        self.tps_initialized = False
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
        ser = self.require_control()
        if not ser:
            return

        TPS546D24.enable_pin(ser, False, debug=self.debug)
        config = tps546D24_values.TPS546_CONFIG_BONANZA
        print("")
        print("Initializing TPS546D24 with TPS546_CONFIG_BONANZA...")
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

        self.board_info()
        bitaxeraw.fan_set_speed(ser, 0xAC, 100, debug=self.debug)
        self.asic_disable()
        config = tps546D24_values.TPS546_CONFIG_BONANZA
        vout_min = config["VOUT_MIN"]
        vout_max = config["VOUT_MAX"]
        default_vout = config["VOUT_COMMAND"]
        target_vout = prompt_float(
            "TPS546 output voltage / VOUT_COMMAND volts",
            default=default_vout,
            minimum=vout_min,
            maximum=vout_max,
        )
        print(f"Expected average BZM2 VDD across four series chips: {target_vout / 4.0:.3f}V")

        TPS546D24.set_vout_command(ser, target_vout, debug=self.debug)
        TPS546D24.enable_pin(ser, True, debug=self.debug)
        time.sleep(0.1)
        TPS546D24.enable_regulator(ser)
        time.sleep(1.0)
        TPS546D24.TPS546_status(ser)

    def tps_off(self):
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
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

    def tps_average_telemetry(self):
        ser = self.require_control()
        if not ser:
            return

        sample_count = prompt_int("Number of samples", default=10, minimum=1, maximum=10000)
        interval = prompt_float("Interval between samples seconds", default=0.1, minimum=0.0)
        samples = []

        print("")
        print("Sample  VIN (V)  VOUT (V)  IOUT (A)  VR_TEMP (C)")
        print("------  -------  --------  --------  -----------")
        try:
            for index in range(sample_count):
                sample = TPS546D24.read_telemetry_sample(ser, debug=self.debug)
                samples.append(sample)
                print(
                    f"{index + 1:>6}  "
                    f"{sample['vin']:>7.3f}  "
                    f"{sample['vout']:>8.3f}  "
                    f"{sample['iout']:>8.3f}  "
                    f"{sample['vr_temp']:>11.3f}"
                )
                if index + 1 < sample_count and interval:
                    time.sleep(interval)
        except KeyboardInterrupt:
            print("\nSampling stopped by user.")
        except RuntimeError as exc:
            print(f"\nSampling stopped: {exc}")

        if not samples:
            print("No telemetry samples collected.")
            return

        averages = TPS546D24.average_telemetry(samples)
        print("------  -------  --------  --------  -----------")
        print(
            f"AVG({len(samples):>2})  "
            f"{averages['vin']:>7.3f}  "
            f"{averages['vout']:>8.3f}  "
            f"{averages['iout']:>8.3f}  "
            f"{averages['vr_temp']:>11.3f}"
        )

    def asic_menu(self):
        actions = {
            "1": ("Reset and enumerate BZM2 chain (core VDD on)", self.bzm_enumerate),
            "2": ("Read BZM2 identity registers", self.bzm_identity),
            "3": ("Configure and read BZM2 voltage/temp", self.bzm_sensors),
            "4": ("Initialize/verify both BZM2 PLLs at 800 MHz", self.bzm_frequency),
            "5": ("Read both BZM2 PLLs", self.bzm_pll_status),
            "6": ("BZM2 loopback test", self.bzm_loopback),
            "7": ("Read ASIC register", self.bzm_read_register),
            "8": ("Write ASIC register", self.bzm_write_register),
            "9": ("Bounded genesis mining test", self.bzm_genesis_test),
            "10": ("Assert ASIC reset and disable 5V", self.asic_disable),
            "11": ("ESP32 board diagnostics (read only)", self.board_diagnostics),
            "12": ("Raw ASIC UART TX test", self.asic_uart_tx_test),
            "13": ("First-chip NOOP test (VDD off, 5V on during test)", lambda: self.bzm_io_test("noop")),
            "14": ("Core-off address assignment diagnostic (full chain needs VDD)", lambda: self.bzm_io_test("assign")),
            "15": ("Manual 5V_EN on/off", self.bzm_5v_menu),
        }
        while True:
            print("\nBonanza BZM2 ASICs")
            for key, (label, _) in actions.items():
                print(f" {key:>2}) {label}")
            print("  b) Back")
            choice = input("ASIC> ").strip().lower()
            if choice in ("b", "back", "q"):
                return
            if choice in actions:
                try:
                    actions[choice][1]()
                except (OSError, RuntimeError, ValueError) as exc:
                    print(f"BZM2 operation failed: {exc}")
            else:
                print("Unknown option")

    def require_chain(self):
        asic = self.require_asic()
        if not asic:
            raise RuntimeError("ASIC serial is unavailable")
        if not self.bzm_chip_ids:
            raise RuntimeError("Reset and enumerate the BZM2 chain first")
        return asic

    def asic_disable(self):
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        ctrl = self.require_control()
        if ctrl:
            try:
                bitaxeraw.gpio_set(ctrl, 0xA4, bitaxeraw.GPIO_ASIC_RST, 0, self.debug)
            finally:
                bitaxeraw.gpio_set(ctrl, 0xA5, bitaxeraw.GPIO_5V_EN, 0, self.debug)

    def bzm_set_5v(self, enabled):
        ctrl = self.require_control()
        if not ctrl:
            return
        self.board_info()
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
        try:
            if enabled:
                bitaxeraw.gpio_set(ctrl, 0xA4, bitaxeraw.GPIO_ASIC_RST, 0, self.debug)
                bitaxeraw.gpio_set(ctrl, 0xA5, bitaxeraw.GPIO_5V_EN, 1, self.debug)
            else:
                self.asic_disable()
            level = bitaxeraw.gpio_get(ctrl, 0xA8, bitaxeraw.GPIO_5V_EN, self.debug)
            if level != int(enabled):
                raise RuntimeError(f"5V_EN readback is {level}, expected {int(enabled)}")
        except BaseException:
            if enabled:
                self.asic_disable()
            raise
        print(f"5V_EN={level} ({'ON' if level else 'OFF'}); ASIC reset asserted.")
        return level

    def bzm_5v_menu(self):
        while True:
            print("\nManual 5V_EN test (ASIC reset held asserted)")
            print("  1) Turn 5V_EN ON")
            print("  2) Turn 5V_EN OFF")
            print("  3) Read 5V_EN")
            print("  b) Back")
            choice = input("5V> ").strip().lower()
            if choice in ("b", "back", "q"):
                return
            if choice in ("1", "2"):
                self.bzm_set_5v(choice == "1")
            elif choice == "3":
                ctrl = self.require_control()
                if ctrl:
                    print(f"5V_EN={bitaxeraw.gpio_get(ctrl, 0xA8, bitaxeraw.GPIO_5V_EN, self.debug)}")
            else:
                print("Unknown option")

    def bzm_enumerate(self):
        ctrl, asic = self.require_control(), self.require_asic()
        if not ctrl or not asic:
            return
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
        # Require the 1004x GPIO map before changing board power/reset.
        self.board_info()
        if not bitaxeraw.gpio_get(ctrl, 0xA6, bitaxeraw.GPIO_TPS546_PGOOD, self.debug):
            raise RuntimeError("TPS546 PGOOD is low. Initialize and turn on the regulator first")
        telemetry = TPS546D24.read_telemetry_sample(ctrl, debug=self.debug)
        if not 2.1 <= telemetry['vout'] <= 3.2:
            raise RuntimeError(f"Core rail {telemetry['vout']:.3f} V is outside the Bonanza profile")
        if bitaxeraw.gpio_get(ctrl, 0xA7, bitaxeraw.GPIO_ASIC_TRIP, self.debug):
            raise RuntimeError("ASIC trip input is asserted")
        count = prompt_int("Expected BZM2 chips", default=4, minimum=1, maximum=4)
        print("Resetting clears ASIC addresses, clocks and all mining work.")
        if not confirm("Reset and enumerate BZM2 now?"):
            return
        try:
            bitaxeraw.fan_set_speed(ctrl, 0xAC, 100, debug=self.debug)
            bzm2.reset(ctrl, asic, self.debug)
            self.bzm_chip_ids = bzm2.enumerate_chain(asic, bzm2.DEFAULT_CHIP_IDS[:count], self.debug)
            print(f"BZM2 chain count: {len(self.bzm_chip_ids)}")
            self.bzm_identity()
        except BaseException:
            self.asic_disable()
            raise

    def bzm_identity(self):
        asic = self.require_chain()
        for address in self.bzm_chip_ids:
            value = bzm2.read_u32(asic, address, bzm2.REG_ASIC_ID, self.debug)
            print(f"ASIC 0x{address:02X}: ASIC_ID=0x{value:08X} chain_enable={bool(value & 0x100)}")

    def bzm_io_power_sample(self, ctrl):
        """Require both disabled core controls and a discharged measured stack."""
        operation = TPS546D24.smb_read_byte(ctrl, PMBUS_OPERATION)
        enabled = bitaxeraw.gpio_get(ctrl, 0xB0, bitaxeraw.GPIO_TPS546_EN, self.debug)
        pgood = bitaxeraw.gpio_get(ctrl, 0xB1, bitaxeraw.GPIO_TPS546_PGOOD, self.debug)
        rail = TPS546D24.read_telemetry_sample(ctrl, debug=self.debug)['vout']
        taps = bitaxeraw.read_domain_voltages(ctrl, 0xB2, self.debug)
        if bitaxeraw.gpio_get(ctrl, 0xB3, bitaxeraw.GPIO_ASIC_TRIP, self.debug):
            raise RuntimeError("ASIC trip input is asserted")
        off = (not operation & 0x80 and not enabled and not pgood and
               all(0 <= v <= IO_TEST_MAX_CORE_VOLTS for v in (rail, *taps)))
        return {'core_off': off, 'operation': operation, 'enable': enabled,
                'pgood': pgood, 'vout': rail, 'taps': taps}

    def bzm_io_test(self, mode, count=None, assume_yes=False):
        """Bounded control-UART test; never establish a managed powered chain."""
        if mode not in ("noop", "assign"):
            raise ValueError("I/O test must be noop or assign")
        if mode == "assign" and count is None:
            count = prompt_int("Expected BZM2 chips", default=4, minimum=1, maximum=4)
        if mode == "assign" and (not isinstance(count, int) or not 1 <= count <= 4):
            raise ValueError("Expected chip count must be 1..4")
        ctrl, asic = self.require_control(), self.require_asic()
        if not ctrl or not asic:
            return False
        self.board_info()
        print("I/O-only test: turn TPS/core VDD off, reset ASICs, enable 5 V and release reset.")
        print("Completion or failure asserts reset and turns 5 V off; PLLs and engines are not configured.")
        if mode == "assign":
            print("With core VDD off, this board has only answered from the first ASIC.")
            print("For all four ASICs, enable core VDD and use ASIC menu 1 (Reset and enumerate).")
        if not assume_yes and not confirm(f"Run BZM2 {mode} test with ASIC VDD off?"):
            return False
        result = {'mode': mode, 'chip_ids': [], 'noop_responses': [], 'id_registers': {}}
        self.bzm_sensors_configured = False
        try:
            self.asic_disable()
            bitaxeraw.fan_set_speed(ctrl, 0xAC, 100, debug=self.debug)
            TPS546D24.smb_write_byte(ctrl, PMBUS_OPERATION, 0)
            TPS546D24.enable_pin(ctrl, False, debug=self.debug)
            deadline = time.monotonic() + 3
            while True:
                before = self.bzm_io_power_sample(ctrl)
                if before['core_off']:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Core rail did not turn off/discharge for I/O test: {before}")
                time.sleep(0.05)
            result['before'] = before
            print(f"Core off: VOUT={before['vout']:.3f} V, taps={before['taps']}, PGOOD=0.")
            bzm2.reset(ctrl, asic, self.debug)
            active = self.bzm_io_power_sample(ctrl)
            if not active['core_off']:
                raise RuntimeError(f"Core rail changed after enabling 5 V: {active}")
            if (bitaxeraw.gpio_get(ctrl, 0xB4, bitaxeraw.GPIO_5V_EN, self.debug) != 1 or
                    bitaxeraw.gpio_get(ctrl, 0xB5, bitaxeraw.GPIO_ASIC_RST, self.debug) != 1):
                raise RuntimeError("5 V/reset are not enabled for I/O communication")
            if mode == "noop":
                # Reset gates the chain at its first unassigned ASIC (0xFA).
                for _ in range(3):
                    reply = bzm2.noop(asic, debug=self.debug)
                    result['noop_responses'].append(reply.hex(' '))
                    print(f"ASIC 0xFA NOOP: {reply.hex(' ')}")
            else:
                try:
                    ids = bzm2.enumerate_chain(asic, bzm2.DEFAULT_CHIP_IDS[:count], self.debug)
                except RuntimeError as exc:
                    raise RuntimeError(f"{exc}. This is a core-off diagnostic; for full-chain enumeration, "
                                       "enable core VDD and use ASIC menu 1 (Reset and enumerate)") from exc
                result['chip_ids'] = ids
                for address in ids:
                    value = bzm2.read_u32(asic, address, bzm2.REG_ASIC_ID, self.debug)
                    if value != (address | 0x100):
                        raise RuntimeError(f"ASIC 0x{address:02X} ID changed: 0x{value:08X}")
                    result['id_registers'][address] = value
                    print(f"ASIC 0x{address:02X}: ASIC_ID=0x{value:08X}")
            after = self.bzm_io_power_sample(ctrl)
            if not after['core_off']:
                raise RuntimeError(f"Core rail changed during I/O test: {after}")
            result['after'] = after
        finally:
            self.asic_disable()
        print(f"BZM2 {mode} I/O test passed; ASIC reset asserted and 5 V off. Core VDD remains off.")
        return result

    def bzm_sensors(self):
        asic = self.require_chain()
        bzm2.configure_sensors(asic, self.bzm_chip_ids, self.debug)
        self.bzm_sensors_configured = True
        for address in self.bzm_chip_ids:
            sample = bzm2.read_sensors(asic, address, self.debug)
            print(f"ASIC 0x{address:02X}: {sample['temperature_c']:.1f} C, "
                  f"CH0={sample['ch0_v']:.4f} V CH1={sample['ch1_v']:.4f} V "
                  f"CH2={sample['ch2_v']:.4f} V")
            print(f"  thermal_fault={sample['thermal_fault']} thermal_trip={sample['thermal_trip']} "
                  f"voltage_fault={sample['voltage_fault']} voltage_trip={sample['voltage_trip']}")
            print("  raw: " + " ".join(f"0x{v:08X}" for v in sample['raw']))

    def bzm_frequency(self):
        asic = self.require_chain()
        frequency = 800
        print("Initializing the reference 800 MHz startup profile.")
        print("Programs both PLL domains and releases engine soft reset; reapply work afterward.")
        if not confirm("Program BZM2 PLLs now?"):
            return
        self.bzm_clocks_verified = False
        result = bzm2.set_frequency(asic, self.bzm_chip_ids, frequency, self.debug)
        self.bzm_clocks_verified = True
        print(f"BZM2 hash clock: {result['actual_mhz']:.2f} MHz")
        self.bzm_pll_status()

    def bzm_pll_status(self):
        asic = self.require_chain()
        for address in self.bzm_chip_ids:
            for index, status in enumerate(bzm2.read_plls(asic, address, self.debug)):
                print(f"ASIC 0x{address:02X} PLL{index}: {status}")

    def bzm_loopback(self):
        asic = self.require_chain()
        for address in self.bzm_chip_ids:
            print(f"ASIC 0x{address:02X}: {bzm2.loopback(asic, address, debug=self.debug).hex(' ')}")

    def prompt_bzm_register(self):
        address = prompt_int("ASIC address", default=self.bzm_chip_ids[0], minimum=0, maximum=0xF9)
        engine = prompt_int("Engine (0xFFF = control/notch)", default=0xFFF, minimum=0, maximum=0xFFF)
        offset = prompt_int("Register offset", default=0x0B, minimum=0, maximum=255)
        return address, engine, offset

    def bzm_read_register(self):
        asic = self.require_chain()
        address, engine, offset = self.prompt_bzm_register()
        count = prompt_int("Bytes to read", default=4, minimum=1, maximum=256)
        data = bzm2.read_register(asic, address, offset, count, engine, self.debug)
        print(f"Register data: {data.hex(' ')} (little-endian 0x{int.from_bytes(data, 'little'):X})")

    def bzm_write_register(self):
        asic = self.require_chain()
        address, engine, offset = self.prompt_bzm_register()
        data = bytes.fromhex(input("Data bytes in wire order (e.g. 01 00 00 00): ").strip())
        if not 1 <= len(data) <= 256:
            raise ValueError("Write requires 1..256 bytes")
        if not confirm(f"Write ASIC {address:02X} engine {engine:03X} register {offset:02X}: {data.hex(' ')}?"):
            return
        # Raw writes can invalidate clocks/sensors/addressing prerequisites.
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
        bzm2.write_register(asic, address, offset, data, engine, self.debug)
        self.bzm_chip_ids = []
        print("Register write sent. Reset and enumerate before further managed operations.")

    def bzm_genesis_test(self):
        asic = self.require_chain()
        if not self.bzm_clocks_verified or not self.bzm_sensors_configured:
            raise RuntimeError("Configure sensors and set/verify PLLs before the mining test")
        offset = prompt_int("Nonce correction (0x4C from fork's 1002 profile; verify on 1004x)",
                            default=0x4C, minimum=0, maximum=255)
        print("Tests one bottom/top engine pair per chip, over 256 nonces around the genesis solution.")
        if not confirm("Run bounded BZM2 genesis test?"):
            return
        self.bzm_sequence = self.bzm_sequence % 255 + 1
        sequence = self.bzm_sequence
        verified = set()
        try:
            for address in self.bzm_chip_ids:
                sample = bzm2.read_sensors(asic, address, self.debug)
                if (sample['thermal_fault'] or sample['thermal_trip'] or sample['voltage_fault'] or
                        sample['voltage_trip'] or not 0 < sample['temperature_c'] < 85 or
                        not all(0.5 <= sample[k] <= 0.85 for k in ('ch0_v', 'ch1_v'))):
                    raise RuntimeError(f"ASIC {address:02X}: sensor precheck failed: {sample}")
            bzm2.start_genesis_test(asic, self.bzm_chip_ids, sequence, self.debug)
            for address in self.bzm_chip_ids:
                for _ in range(8):
                    result = bzm2.read_result(asic, address, self.debug)
                    if not result['valid']:
                        break
                    valid = bzm2.validate_genesis_result(result, sequence, offset)
                    print(f"{result} genesis_verified={valid}")
                    if valid:
                        verified.add((address, result['engine']))
            expected = {(a, e) for a in self.bzm_chip_ids for e in bzm2.SMOKE_ENGINES}
            print(f"Genesis results verified: {len(verified)}/{len(expected)} engines")
            if verified != expected:
                raise RuntimeError("Genesis test did not verify every selected engine; inspect raw results and nonce offset")
        finally:
            bzm2.stop_genesis_test(asic, self.bzm_chip_ids, self.debug)

    def bridge_firmware_menu(self):
        while True:
            print("\nRP2040 bridge firmware (ESP32 SWD)")
            print("  1) Probe RP2040 SWD connection")
            print("  2) Load bridge firmware from .bin/.uf2")
            print("  b) Back")
            choice = input("Bridge> ").strip().lower()
            if choice in ("b", "back", "q"):
                return
            if choice == "1":
                ctrl = self.require_control()
                if ctrl:
                    print(f"RP2040 SWD DPIDR: 0x{bridge_loader.probe(ctrl, self.debug):08X}")
            elif choice == "2":
                self.load_bridge_firmware()
            else:
                print("Unknown option")

    def load_bridge_firmware(self, path=None, assume_yes=False):
        if path is None:
            path = input("Bridge firmware .bin/.uf2 path: ").strip()
        # Validate the entire file before opening SWD or disabling any rail.
        image = bridge_loader.FirmwareImage.load(path)
        print(f"Bridge image: {image.path}")
        print(f"Flash bytes: {len(image.data)}; CRC32: {image.crc32:08X}")
        print(f"Flash-image SHA256: {image.sha256}")
        ctrl = self.require_control()
        if not ctrl:
            return False
        print(f"RP2040 SWD DPIDR: 0x{bridge_loader.probe(ctrl, self.debug):08X}")
        if not assume_yes and not confirm("Replace RP2040 bridge firmware with this image?"):
            return False
        if self.asic and self.asic.is_open:
            self.asic.close()
        self.bzm_chip_ids = []
        self.bzm_clocks_verified = False
        self.bzm_sensors_configured = False
        last_percent = -5

        def progress(done, total):
            nonlocal last_percent
            percent = done * 100 // total
            if percent >= last_percent + 5 or done == total:
                print(f"Bridge flash: {done}/{total} bytes ({percent}%) verified")
                last_percent = percent

        bridge_loader.program(ctrl, image, progress=progress, debug=self.debug)
        print("RP2040 flash readback verified and target reset. TPS output and 5 V remain off.")
        print("Initialize/enable the TPS and enumerate the BZM2 chain before mining.")
        return True

    def board_info(self):
        ctrl = self.require_control()
        if not ctrl:
            raise RuntimeError("Control serial is unavailable")
        data = bitaxeraw.control_command(ctrl, 0xD0, 0, 1, debug=self.debug)
        if len(data) < 4 or data[0] != 1 or data[1] != 1 or len(data) != 4 + data[3]:
            raise RuntimeError(f"Incompatible ESP32 firmware info: {data.hex(' ')}")
        identity = data[4:].decode('ascii')
        if not identity.startswith('bitaxe-raw-bonanza/1004x/'):
            raise RuntimeError('ESP32 needs the updated 1004x bitaxe-raw-bonanza firmware')
        print(f"ESP32 firmware: {identity} (protocol {data[1]}.{data[2]})")
        return data

    def read_domain_voltages(self):
        ctrl = self.require_control()
        if not ctrl:
            return
        taps = bitaxeraw.read_domain_voltages(ctrl, debug=self.debug)
        print(f"Stack taps: D1/GPIO5={taps[0]:.3f} V D2/GPIO4={taps[1]:.3f} V D3/GPIO3={taps[2]:.3f} V")
        rail = TPS546D24.read_telemetry_sample(ctrl, debug=self.debug)['vout']
        voltages = bitaxeraw.chip_voltages_from_taps(taps, rail)
        print(f"TPS546 output: {rail:.3f} V")
        print("ASIC VDD (bottom to top, A1..A4): " + ", ".join(f"{v:.3f} V" for v in voltages))
        return taps, voltages

    def board_diagnostics(self):
        ctrl = self.require_control()
        if not ctrl:
            return False
        ok = True
        for label, gpio in (("TPS546 enable", bitaxeraw.GPIO_TPS546_EN),
                            ("TPS546 PGOOD", bitaxeraw.GPIO_TPS546_PGOOD)):
            try:
                print(f"{label}: {bitaxeraw.gpio_get(ctrl, 0xD1, gpio, self.debug)}")
            except (OSError, RuntimeError) as exc:
                print(f"{label}: {exc}")
                return False
        # All board controls are local; the RP2040 is only the ASIC UART bridge.
        try:
            print(f"Fan RPM: {bitaxeraw.get_fan_rpm(ctrl, 0xD3, self.debug)}")
            self.read_domain_voltages()
        except (OSError, RuntimeError) as exc:
            print(f"ESP32 fan diagnostics failed: {exc}")
            return False
        try:
            self.board_info()
            data = bitaxeraw.control_command(ctrl, 0xD2, 0, 0x10, debug=self.debug)
            if len(data) != 3 or data[0] != 1:
                raise RuntimeError(f"Invalid ESP32 board status: {data.hex(' ')}")
            flags = data[1]
            print(f"5V_EN={bool(flags & 1)} reset_asserted={bool(flags & 2)} "
                  f"ASIC_TRIP={bool(flags & 4)} trip_latched={bool(flags & 8)} "
                  f"fan_raw_duty={data[2]}")
        except (OSError, RuntimeError) as exc:
            print(f"ESP32 board diagnostics failed: {exc}")
            ok = False
        return ok

    def asic_uart_tx_test(self):
        asic = self.require_asic()
        if asic and confirm("Send UART test pattern (requires reset/re-enumeration afterward)?"):
            # Even debug patterns must honor the bridge's two-byte TX format.
            bitaxeraw.asic_write(asic, [0x55, 0xAA, 0, 0xFF] * 16, self.debug)
            self.bzm_chip_ids = []
            self.bzm_clocks_verified = False

    def fan_menu(self):
        while True:
            print("")
            print("Fan")
            print("  1) Set fan speed percent")
            print("  2) Set raw fan PWM byte")
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

        percent = prompt_int("Fan speed percent", default=50, minimum=0, maximum=100)
        duty = bitaxeraw.fan_speed_percent_to_raw_duty(percent)
        print(f"Setting fan speed to {percent}% (raw active-low duty {duty}/255)...")
        bitaxeraw.fan_set_speed(ser, 0xAC, percent, debug=self.debug)

    def fan_set_raw_duty(self):
        ser = self.require_control()
        if not ser:
            return

        duty = prompt_int("Fan raw PWM byte", default=128, minimum=0, maximum=255)
        print(f"Setting raw active-low fan PWM byte to {duty}/255...")
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


def prompt_float(prompt, default, minimum=None, maximum=None):
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
        if maximum is not None and value > maximum:
            print(f"Enter a value <= {maximum}.")
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
    parser = argparse.ArgumentParser(description="Interactive bitaxeBonanza-1004x bringup console.")
    ctrl_default, asic_default = bitaxeraw.discover_ports()
    parser.add_argument(
        "--ctrl-port",
        default=ctrl_default or DEFAULT_CTRL_PORT,
        help=f"ESP32 control serial port, default: {DEFAULT_CTRL_PORT}",
    )
    parser.add_argument(
        "--asic-port",
        default=asic_default or DEFAULT_ASIC_PORT,
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
        default=3.0,
        help="Serial timeout in seconds, default: 3.0",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw control packets where supported.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="Read ESP32 board diagnostics and exit without enabling power")
    mode.add_argument("--bridge-probe", action="store_true", help="Probe the RP2040 over ESP32 SWD without flashing")
    mode.add_argument("--flash-bridge", metavar="FILE", help="Load an RP2040 .bin/.uf2 through ESP32 SWD and exit")
    mode.add_argument("--bzm-io-test", choices=("noop", "assign"),
                      help="Test BZM2 UART with core VDD off and 5 V enabled only during the test")
    parser.add_argument("--chips", type=int, choices=range(1, 5), default=4,
                        help="Expected chips for --bzm-io-test assign (default: 4)")
    parser.add_argument("--yes", action="store_true", help="Confirm the selected bridge flash or BZM2 I/O test without prompting")
    args = parser.parse_args(argv)
    if args.yes and not (args.flash_bridge or args.bzm_io_test):
        parser.error("--yes requires --flash-bridge FILE or --bzm-io-test")
    return args


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
    try:
        if args.bzm_io_test:
            if not app.connect_serial_ports():
                return 1
            return 0 if app.bzm_io_test(args.bzm_io_test, args.chips, assume_yes=args.yes) else 1
        if args.flash_bridge or args.bridge_probe:
            if not app.connect_control():
                return 1
            if args.bridge_probe:
                print(f"RP2040 SWD DPIDR: 0x{bridge_loader.probe(app.ctrl, args.debug):08X}")
                return 0
            return 0 if app.load_bridge_firmware(args.flash_bridge, assume_yes=args.yes) else 1
        if args.probe:
            if not app.connect_control():
                return 1
            return 0 if app.board_diagnostics() else 1
        return app.run()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting Anvil.")
        return 130 if args.bzm_io_test else 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Anvil operation failed: {exc}")
        return 1
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
