#!/usr/bin/env python3
"""Interactive bitaxeProto bringup console."""

import argparse
import glob
import sys
import time

import bitaxeraw
import bonanza_display
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
        self.mc3_hash_frequency_mhz = 200
        self.bonanza_values = {
            name: spec["default"] for name, spec in bonanza_display.FIELD_SPECS.items()
        }

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
            print("  5) bonanzaDisplay")
            print("  6) List serial ports")
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
                self.bonanza_display_menu()
            elif choice == "6":
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
            print("Serial setup incomplete. Check the selected ports or use List serial ports.")
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

        config = tps546D24_values.TPS546_CONFIG_PROTO
        vout_min = config["VOUT_MIN"]
        vout_max = config["VOUT_MAX"]
        default_vout = config["VOUT_COMMAND"]
        target_vout = prompt_float(
            "TPS546 output voltage / VOUT_COMMAND volts",
            default=default_vout,
            minimum=vout_min,
            maximum=vout_max,
        )
        print(f"Expected MC3 VDD from board divider: {target_vout / 2.0:.3f}V")

        TPS546D24.set_vout_command(ser, target_vout, debug=self.debug)
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
        while True:
            print("")
            print("Proto MC3 ASICs")
            print("  1) Enable VDDIO 5V")
            print("  2) Disable VDDIO 5V")
            print("  3) Enumerate MC3 chain")
            print("  4) Read MC3 voltage/temp")
            print("  5) Start app-note MC3 mining test")
            print("  6) Start app-note mining with distinct chip ranges")
            print("  7) Read MC3 nonce buffer(s)")
            print("  8) Poll app-note mining health")
            print("  9) App-note work note rollover test")
            print(" 10) App-note target-rate sanity test")
            print(" 11) Set/verify MC3 hash frequency")
            print(" 12) MC3 SPD logger hashrate test")
            print(" 13) Cold-set MC3 hash frequency")
            print(" 14) Raw ASIC UART TX test")
            print("  b) Back")
            choice = input("ASIC> ").strip().lower()

            if choice == "1":
                self.asic_vddio(True)
            elif choice == "2":
                self.asic_vddio(False)
            elif choice == "3":
                self.mc3_enumerate()
            elif choice == "4":
                self.mc3_sensor_read_test()
            elif choice == "5":
                self.mc3_start_app_note_mining()
            elif choice == "6":
                self.mc3_start_app_note_mining_distinct_ranges()
            elif choice == "7":
                self.mc3_read_nonce_buffer()
            elif choice == "8":
                self.mc3_poll_app_note_mining_health()
            elif choice == "9":
                self.mc3_work_note_rollover_test()
            elif choice == "10":
                self.mc3_target_rate_sanity_test()
            elif choice == "11":
                self.mc3_set_hash_frequency()
            elif choice == "12":
                self.mc3_spdlog_hashrate_test()
            elif choice == "13":
                self.mc3_cold_set_hash_frequency()
            elif choice == "14":
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

    def mc3_sensor_read_test(self):
        asic = self.require_asic()
        if not asic:
            return

        print("This assumes the MC3 chain has already been enumerated with INIT.")
        print("  1) Rail summary")
        print("  2) Raw voltage channel read/scan")
        print("  3) Voltage matrix diagnostic")
        mode = input("Sensor> ").strip().lower()
        if mode in ("", "1"):
            sensor_mode = "summary"
        elif mode == "2":
            sensor_mode = "raw"
        elif mode == "3":
            sensor_mode = "matrix"
        elif mode in ("b", "back", "q"):
            return
        else:
            print("Unknown sensor option")
            return

        first_chip_id = prompt_int("First chip ID", default=0, minimum=0, maximum=255)
        chip_count = prompt_int("Chip count", default=4, minimum=1, maximum=256 - first_chip_id)
        voltage_clock = mc3.VOLTAGE_CLOCK_DEFAULT
        try:
            if sensor_mode == "summary":
                mc3.mc3_voltage_temp_rail_summary(
                    asic,
                    first_chip_id=first_chip_id,
                    chip_count=chip_count,
                    voltage_clock=voltage_clock,
                    debug=self.debug,
                )
            elif sensor_mode == "matrix":
                mc3.voltage_matrix_test(
                    asic,
                    first_chip_id=first_chip_id,
                    chip_count=chip_count,
                    voltage_clock=voltage_clock,
                    debug=self.debug,
                )
            else:
                voltage_channel = prompt_int("Voltage channel (-1 scan all)", default=13, minimum=-1, maximum=15)
                mc3.sensor_read_test(
                    asic,
                    first_chip_id=first_chip_id,
                    chip_count=chip_count,
                    voltage_channel=voltage_channel,
                    voltage_clock=voltage_clock,
                    debug=self.debug,
                )
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 sensor read failed: {exc}")

    def mc3_start_app_note_mining(self):
        asic = self.require_asic()
        if not asic:
            return

        print("This writes the static version-rolling work vector from the MC3 mining app note.")
        print("Expected preconditions: TPS core voltage ON, VDDIO 5V ON, 25 MHz CLKI present, and MC3 INIT enumeration already completed.")
        print("The test broadcasts the same work to all chips in the chain.")
        if not confirm("Start MC3 app-note mining test now?"):
            return

        try:
            rolltime = mc3.rolltime_for_pll_mhz(self.mc3_hash_frequency_mhz)
            work = mc3.start_app_note_version_rolling_mining(
                asic,
                rolltime=rolltime,
                debug=self.debug,
            )
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 mining start failed: {exc}")
            return

        print("MC3 app-note mining work written.")
        print(f"  Hash MHz/ROLLTIME: {self.mc3_hash_frequency_mhz} / 0x{rolltime:08X}")
        print(f"  V_BASE: 0x{mc3.v_base_value_for_work(work):08X}")
        print(f"  nTime:  0x{work.ntime:08X}")
        print(f"  nBits:  0x{work.nbits:08X}")
        print(f"  Target: H=0x{work.work_target_h:08X} L=0x{work.work_target_l:08X}")
        print(f"  Note:   {' '.join(f'0x{word:08X}' for word in work.note)}")

    def mc3_start_app_note_mining_distinct_ranges(self):
        asic = self.require_asic()
        if not asic:
            return

        print("This writes the static app-note work but assigns each chip a distinct version range.")
        print("For the default 16-bit version mask, four chips get V_BASE strides of 0x4000.")
        print("Expected preconditions: TPS core voltage ON, VDDIO 5V ON, 25 MHz CLKI present, and MC3 INIT enumeration already completed.")
        first_chip_id = prompt_int("First chip ID", default=0, minimum=0, maximum=255)
        chip_count = prompt_int("Chip count", default=4, minimum=1, maximum=256 - first_chip_id)
        version_mask_bits = prompt_int(
            "Version mask bits",
            default=mc3.DEFAULT_VERSION_MASK_BITS,
            minimum=1,
            maximum=32,
        )
        work = mc3.app_note_version_rolling_work()
        try:
            v_bases = mc3.v_base_values_for_chip_range(
                work,
                first_chip_id=first_chip_id,
                chip_count=chip_count,
                version_mask_bits=version_mask_bits,
            )
        except ValueError as exc:
            print(f"Invalid version range settings: {exc}")
            return

        print("Assigned V_BASE values:")
        for chip_id, v_base in v_bases:
            print(f"  chip {chip_id}: 0x{v_base:08X}")
        if not confirm("Start MC3 app-note mining with distinct chip ranges now?"):
            return

        try:
            rolltime = mc3.rolltime_for_pll_mhz(self.mc3_hash_frequency_mhz)
            mc3.start_app_note_version_rolling_mining_distinct_ranges(
                asic,
                first_chip_id=first_chip_id,
                chip_count=chip_count,
                version_mask_bits=version_mask_bits,
                rolltime=rolltime,
                debug=self.debug,
            )
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 distinct-range mining start failed: {exc}")
            return

        print("MC3 app-note mining work written with distinct chip version ranges.")
        print(f"  Hash MHz/ROLLTIME: {self.mc3_hash_frequency_mhz} / 0x{rolltime:08X}")
        print(f"  nTime:  0x{work.ntime:08X}")
        print(f"  nBits:  0x{work.nbits:08X}")
        print(f"  Target: H=0x{work.work_target_h:08X} L=0x{work.work_target_l:08X}")
        print(f"  Note:   {' '.join(f'0x{word:08X}' for word in work.note)}")

    def mc3_read_nonce_buffer(self):
        asic = self.require_asic()
        if not asic:
            return

        chip_ids = self.prompt_mc3_chip_ids()
        do_update = confirm("Issue NONCE_UPDATE before reading?")
        try:
            if do_update:
                mc3.update_nonce_buffer(asic, debug=self.debug)
                time.sleep(0.01)
            for chip_id in chip_ids:
                parsed = mc3.read_version_rolling_nonce_buffer(asic, chip_id=chip_id, debug=self.debug)
                self.print_mc3_nonce_buffer(chip_id, parsed)
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 nonce read failed: {exc}")
            return

    def prompt_mc3_chip_ids(self):
        read_all = confirm("Read nonce buffers for all chips?")
        if read_all:
            first_chip_id = prompt_int("First chip ID", default=0, minimum=0, maximum=255)
            chip_count = prompt_int("Chip count", default=4, minimum=1, maximum=256 - first_chip_id)
            return tuple(range(first_chip_id, first_chip_id + chip_count))

        chip_id = prompt_int("Chip ID", default=0, minimum=0, maximum=255)
        return (chip_id,)

    def print_mc3_nonce_buffer(self, chip_id, parsed, work=None):
        if work is None:
            work = mc3.app_note_version_rolling_work()

        print("")
        print(f"Chip {chip_id} nonce buffer")
        print(f"Nonce buffer note: {' '.join(f'0x{word:08X}' for word in parsed['note'])}")
        print("Idx  Valid  Core  nTime  Nonce       Version")
        print("---  -----  ----  -----  ----------  ----------")
        for nonce in parsed["nonces"]:
            print(
                f"{nonce['index']:>3}  "
                f"{'yes' if nonce['valid'] else 'no ':>5}  "
                f"{nonce['core_id']:>4}  "
                f"0x{nonce['ntime_offset']:04X}  "
                f"0x{nonce['nonce']:08X}  "
                f"0x{nonce['version']:08X}"
            )

        validation_results = mc3.validate_version_rolling_nonces(work, parsed)
        target_hex = f"{mc3.compact_target_from_nbits(work.nbits):064X}"
        print("")
        print("Host validation against app-note nBits target")
        print(f"Target: {target_hex}")
        for result in validation_results:
            nonce_record = result["nonce_record"]
            if not nonce_record["valid"]:
                print(f"  nonce {nonce_record['index']}: invalid slot, skipped")
                continue
            status = "PASS" if result["meets_target"] else "FAIL"
            print(
                f"  nonce {nonce_record['index']}: {status} "
                f"version=0x{result['version']:08X} "
                f"ntime=0x{result['ntime']:08X} "
                f"nonce=0x{result['nonce']:08X}"
            )
            print(f"    hash: {result['hash_hex']}")

    def summarize_mc3_nonce_buffer(self, work, parsed, expected_note=None):
        validation_results = mc3.validate_version_rolling_nonces(work, parsed)
        valid_count = sum(1 for nonce in parsed["nonces"] if nonce["valid"])
        pass_count = sum(
            1
            for result in validation_results
            if result["valid"] and result["meets_target"]
        )
        return {
            "note": parsed["note"],
            "note_ok": expected_note is None or parsed["note"] == expected_note,
            "valid_count": valid_count,
            "pass_count": pass_count,
        }

    def read_mc3_nonce_summaries(self, asic, chip_ids, work, expected_note=None, update=True):
        if update:
            mc3.update_nonce_buffer(asic, debug=self.debug)
            time.sleep(0.01)

        summaries = {}
        for chip_id in chip_ids:
            parsed = mc3.read_version_rolling_nonce_buffer(asic, chip_id=chip_id, debug=self.debug)
            summaries[chip_id] = self.summarize_mc3_nonce_buffer(
                work,
                parsed,
                expected_note=expected_note,
            )
        return summaries

    def print_mc3_nonce_summary(self, summaries):
        print("Chip  Note OK  Valid  Pass  Note")
        print("----  -------  -----  ----  -----------------------------------------------")
        for chip_id, summary in summaries.items():
            note = " ".join(f"0x{word:08X}" for word in summary["note"])
            note_ok = "yes" if summary["note_ok"] else "NO"
            print(
                f"{chip_id:>4}  {note_ok:>7}  "
                f"{summary['valid_count']:>5}  {summary['pass_count']:>4}  {note}"
            )

    def prompt_mc3_range_settings(self):
        first_chip_id, chip_count = self.prompt_mc3_chip_range()
        version_mask_bits = prompt_int(
            "Version mask bits",
            default=mc3.DEFAULT_VERSION_MASK_BITS,
            minimum=1,
            maximum=32,
        )
        return first_chip_id, chip_count, version_mask_bits

    def prompt_mc3_chip_range(self):
        first_chip_id = prompt_int("First chip ID", default=0, minimum=0, maximum=255)
        chip_count = prompt_int("Chip count", default=4, minimum=1, maximum=256 - first_chip_id)
        return first_chip_id, chip_count

    def start_distinct_app_note_work(self, asic, work, first_chip_id, chip_count, version_mask_bits):
        rolltime = mc3.rolltime_for_pll_mhz(self.mc3_hash_frequency_mhz)
        mc3.start_app_note_version_rolling_mining_distinct_ranges(
            asic,
            first_chip_id=first_chip_id,
            chip_count=chip_count,
            version_mask_bits=version_mask_bits,
            work=work,
            rolltime=rolltime,
            debug=self.debug,
        )

    def mc3_poll_app_note_mining_health(self):
        asic = self.require_asic()
        if not asic:
            return

        print("Repeatedly starts distinct-range app-note mining with a fresh note, then validates all selected chips.")
        first_chip_id, chip_count, version_mask_bits = self.prompt_mc3_range_settings()
        interval = prompt_float("Cycle interval seconds", default=5.0, minimum=0.25)
        mine_seconds = prompt_float("Seconds to mine each note before reading", default=1.0, minimum=0.05)
        duration = prompt_float("Total duration seconds", default=30.0, minimum=interval)
        chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))

        if not confirm("Start polling app-note mining health now?"):
            return

        try:
            deadline = time.monotonic() + duration
            cycle = 1
            while True:
                cycle_start = time.monotonic()
                note_id = 0x1000 + cycle
                work = mc3.app_note_version_rolling_work(note=(note_id, 0, 0, 0))
                elapsed = duration - max(0.0, deadline - time.monotonic())
                print("")
                print(f"Poll {cycle} at {elapsed:.1f}s, note 0x{note_id:08X}")
                self.start_distinct_app_note_work(asic, work, first_chip_id, chip_count, version_mask_bits)
                time.sleep(min(mine_seconds, max(0.0, deadline - time.monotonic())))
                summaries = self.read_mc3_nonce_summaries(
                    asic,
                    chip_ids,
                    work,
                    expected_note=work.note,
                    update=True,
                )
                self.print_mc3_nonce_summary(summaries)
                if time.monotonic() >= deadline:
                    break
                next_cycle = cycle_start + interval
                time.sleep(min(max(0.0, next_cycle - time.monotonic()), max(0.0, deadline - time.monotonic())))
                cycle += 1
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 mining health poll failed: {exc}")

    def mc3_work_note_rollover_test(self):
        asic = self.require_asic()
        if not asic:
            return

        print("Starts app-note work with note 1, reads buffers, then starts note 2 and confirms buffers roll over.")
        first_chip_id, chip_count, version_mask_bits = self.prompt_mc3_range_settings()
        settle_seconds = prompt_float("Seconds to mine each note before reading", default=1.0, minimum=0.1)
        chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))

        if not confirm("Run work note rollover test now?"):
            return

        try:
            for note_id in (1, 2):
                work = mc3.app_note_version_rolling_work(note=(note_id, 0, 0, 0))
                print("")
                print(f"Starting app-note work note {note_id}...")
                self.start_distinct_app_note_work(asic, work, first_chip_id, chip_count, version_mask_bits)
                time.sleep(settle_seconds)
                summaries = self.read_mc3_nonce_summaries(
                    asic,
                    chip_ids,
                    work,
                    expected_note=work.note,
                    update=True,
                )
                self.print_mc3_nonce_summary(summaries)
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 work note rollover test failed: {exc}")

    def mc3_target_rate_sanity_test(self):
        asic = self.require_asic()
        if not asic:
            return

        print("Runs the app-note work with an easy target and then a harder target, reporting returned nonce counts and an approximate hashrate.")
        print("This is a probabilistic smoke test; useful estimates need nonzero counts that do not fill every chip buffer.")
        first_chip_id, chip_count, version_mask_bits = self.prompt_mc3_range_settings()
        phase_seconds = prompt_float("Seconds to mine each target", default=5.0, minimum=0.25)
        hard_target_h = prompt_int("Hard target H", default=0x02000000, minimum=0, maximum=0xFFFFFFFF)
        hard_target_l = prompt_int("Hard target L", default=0xFFFFFFFF, minimum=0, maximum=0xFFFFFFFF)
        chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))
        max_buffered_nonces = len(chip_ids) * mc3.VERSION_ROLLING_NONCE_COUNT
        phases = (
            ("easy", mc3.DEFAULT_WORK_TARGET_H, mc3.DEFAULT_WORK_TARGET_L, 0x2001),
            ("hard", hard_target_h, hard_target_l, 0x2002),
        )

        if not confirm("Run target-rate sanity test now?"):
            return

        try:
            for label, target_h, target_l, note_id in phases:
                work = mc3.app_note_version_rolling_work(
                    note=(note_id, 0, 0, 0),
                    work_target_h=target_h,
                    work_target_l=target_l,
                )
                print("")
                print(f"Starting {label} target H=0x{target_h:08X} L=0x{target_l:08X}...")
                self.start_distinct_app_note_work(asic, work, first_chip_id, chip_count, version_mask_bits)
                mine_start = time.monotonic()
                time.sleep(phase_seconds)
                mine_elapsed = time.monotonic() - mine_start
                summaries = self.read_mc3_nonce_summaries(
                    asic,
                    chip_ids,
                    work,
                    expected_note=work.note,
                    update=True,
                )
                self.print_mc3_nonce_summary(summaries)
                total_valid = sum(summary["valid_count"] for summary in summaries.values())
                total_pass = sum(summary["pass_count"] for summary in summaries.values())
                print(f"{label} target totals: valid={total_valid}, host-pass={total_pass}")
                if total_valid:
                    hashrate = mc3.hashrate_from_nonce_count(
                        total_valid,
                        mine_elapsed,
                        target_h,
                        target_l,
                    )
                    qualifier = "lower-bound " if total_valid >= max_buffered_nonces else ""
                    print(
                        f"{label} target estimate: {qualifier}{hashrate / 1e9:.2f} GH/s "
                        f"from {total_valid} nonce(s) over {mine_elapsed:.2f}s"
                    )
                    if total_valid >= max_buffered_nonces:
                        print("  Buffer filled; use a harder target or shorter phase for a better estimate.")
                else:
                    print("No nonces returned; use an easier target or longer phase for a measurable estimate.")
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 target-rate sanity test failed: {exc}")

    def mc3_set_hash_frequency(self):
        asic = self.require_asic()
        if not asic:
            return

        supported = ", ".join(str(freq) for freq in sorted(mc3.PLL_RECOMMENDED_CONFIGS))
        print("Sets PLL0 from the MC3 recommended PLL table, selects PLL0 globally, enables it, and verifies lock.")
        print("Supported MHz values:")
        print(supported)
        first_chip_id, chip_count = self.prompt_mc3_chip_range()
        frequency_mhz = prompt_int(
            "Hash frequency MHz",
            default=self.mc3_hash_frequency_mhz,
            minimum=100,
            maximum=1000,
        )
        update_rolltime = confirm("Update ROLLTIME for this frequency?")

        try:
            pll_tuple = mc3.recommended_pll_config_for_mhz(frequency_mhz)
            pll_cfg = mc3.pll_config_value_for_mhz(frequency_mhz)
            rolltime = mc3.rolltime_for_pll_mhz(frequency_mhz)
        except ValueError as exc:
            print(exc)
            return

        chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))
        expected_per_chip = mc3.expected_hashrate_ghs(frequency_mhz, chip_count=1)
        expected_total = mc3.expected_hashrate_ghs(frequency_mhz, chip_count=chip_count)
        print(
            f"PLL0 {frequency_mhz} MHz config: "
            f"REFDIV={pll_tuple[0]} FBDIV={pll_tuple[1]} "
            f"POSTDIV1={pll_tuple[2]} POSTDIV2={pll_tuple[3]} "
            f"PLL0_CFG=0x{pll_cfg:08X}"
        )
        print(f"Expected ROLLTIME: 0x{rolltime:08X}")
        print(f"Theoretical rate: {expected_per_chip:.1f} GH/s per chip, {expected_total:.1f} GH/s total")
        print("Note: PLL0_CFG bit packing follows the MC3 errata; readback/lock are the safety checks.")

        try:
            before_status = [
                mc3.read_hash_frequency_status(asic, chip_id, debug=self.debug)
                for chip_id in chip_ids
            ]
            print("")
            print("Current hash-frequency status")
            print("Chip  CFG OK  Locked  Rolltime OK  PLL0_CFG     PLL0_EN      ROLLTIME")
            print("----  ------  ------  -----------  ----------  ----------  ----------")
            for status in before_status:
                cfg_ok = status["pll0_cfg"] == pll_cfg
                rolltime_ok = (not update_rolltime) or status["rolltime"] == rolltime
                print(
                    f"{status['chip_id']:>4}  "
                    f"{'yes' if cfg_ok else 'NO ':>6}  "
                    f"{'yes' if status['pll0_locked'] else 'NO ':>6}  "
                    f"{'yes' if rolltime_ok else 'NO ':>11}  "
                    f"0x{status['pll0_cfg']:08X}  "
                    f"0x{status['pll0_en']:08X}  "
                    f"0x{status['rolltime']:08X}"
                )

            already_matches = all(
                mc3.hash_frequency_status_matches(
                    status,
                    frequency_mhz,
                    check_rolltime=update_rolltime,
                )
                for status in before_status
            )
            if already_matches:
                print("")
                print("All selected chips already match; skipping PLL writes.")
                self.mc3_hash_frequency_mhz = frequency_mhz
                return

            print("")
            print("PLL reprogramming will use the errata sequence: disable, configure, enable 0x1, enable 0x3.")
            print("Reapply mining work after changing frequency.")
            if not confirm("Force PLL write now?"):
                return

            mc3.set_hash_frequency(
                asic,
                frequency_mhz,
                start_chip_id=first_chip_id,
                chip_num=mc3.CHIP_NUM_ALL,
                update_rolltime=update_rolltime,
                debug=self.debug,
            )
            time.sleep(0.1)
            print("")
            print("Post-write hash-frequency status")
            print("Chip  CFG OK  Locked  Rolltime OK  PLL0_CFG     PLL0_EN      ROLLTIME")
            print("----  ------  ------  -----------  ----------  ----------  ----------")
            for chip_id in chip_ids:
                status = mc3.read_hash_frequency_status(asic, chip_id, debug=self.debug)
                cfg_ok = status["pll0_cfg"] == pll_cfg
                rolltime_ok = (not update_rolltime) or status["rolltime"] == rolltime
                print(
                    f"{chip_id:>4}  "
                    f"{'yes' if cfg_ok else 'NO ':>6}  "
                    f"{'yes' if status['pll0_locked'] else 'NO ':>6}  "
                    f"{'yes' if rolltime_ok else 'NO ':>11}  "
                    f"0x{status['pll0_cfg']:08X}  "
                    f"0x{status['pll0_en']:08X}  "
                    f"0x{status['rolltime']:08X}"
                )
            self.mc3_hash_frequency_mhz = frequency_mhz
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 hash frequency set/verify failed: {exc}")

    def mc3_cold_set_hash_frequency(self):
        asic = self.require_asic()
        if not asic:
            return

        supported = ", ".join(str(freq) for freq in sorted(mc3.PLL_RECOMMENDED_CONFIGS))
        print("Cold-start PLL0 hash-frequency setup.")
        print("Run this immediately after ASIC reset/enumeration, before starting mining or SPDLOG.")
        print("This follows the app-note startup order: GLOBAL, optional PLL0_CFG, PLL0_EN, then matching ROLLTIME.")
        print("Supported MHz values:")
        print(supported)
        first_chip_id, chip_count = self.prompt_mc3_chip_range()
        frequency_mhz = prompt_int(
            "Hash frequency MHz",
            default=self.mc3_hash_frequency_mhz,
            minimum=100,
            maximum=1000,
        )
        write_pll_config = confirm("Write PLL0_CFG register?")
        update_rolltime = confirm("Update ROLLTIME for this frequency?")

        try:
            pll_tuple = mc3.recommended_pll_config_for_mhz(frequency_mhz)
            pll_cfg = mc3.pll_config_value_for_mhz(frequency_mhz)
            rolltime = mc3.rolltime_for_pll_mhz(frequency_mhz)
            chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))
            before_status = [
                mc3.read_hash_frequency_status(asic, chip_id, debug=self.debug)
                for chip_id in chip_ids
            ]
        except (RuntimeError, TimeoutError, ValueError) as exc:
            print(f"MC3 cold hash-frequency setup failed before write: {exc}")
            return

        expected_per_chip = mc3.expected_hashrate_ghs(frequency_mhz, chip_count=1)
        expected_total = mc3.expected_hashrate_ghs(frequency_mhz, chip_count=chip_count)
        print(
            f"PLL0 {frequency_mhz} MHz config: "
            f"REFDIV={pll_tuple[0]} FBDIV={pll_tuple[1]} "
            f"POSTDIV1={pll_tuple[2]} POSTDIV2={pll_tuple[3]} "
            f"PLL0_CFG=0x{pll_cfg:08X}"
        )
        print(f"Expected ROLLTIME: 0x{rolltime:08X}")
        print(f"Theoretical rate: {expected_per_chip:.1f} GH/s per chip, {expected_total:.1f} GH/s total")
        print("")
        print("Pre-write PLL0 status")
        print("Chip  Enabled  Locked  PLL0_CFG     PLL0_EN      ROLLTIME")
        print("----  -------  ------  ----------  ----------  ----------")
        pll_already_on = False
        for status in before_status:
            enabled = bool(status["pll0_en"] & 0x1)
            pll_already_on = pll_already_on or enabled or status["pll0_locked"]
            print(
                f"{status['chip_id']:>4}  "
                f"{'yes' if enabled else 'no ':>7}  "
                f"{'yes' if status['pll0_locked'] else 'no ':>6}  "
                f"0x{status['pll0_cfg']:08X}  "
                f"0x{status['pll0_en']:08X}  "
                f"0x{status['rolltime']:08X}"
            )

        if pll_already_on:
            print("")
            print("Warning: PLL0 already appears enabled or locked on at least one selected chip.")
            print("This is not a clean cold-start condition; use option 11 for read-only verification.")
            if not confirm("Continue with cold PLL write anyway?"):
                return

        print("")
        print("Writes to broadcast:")
        print(f"  0x{mc3.GLOBAL_SPD:08X} = 0x{mc3.DEFAULT_GLOBAL_SPD_VALUE:08X}")
        if write_pll_config:
            print(f"  0x{mc3.PLL0_CFG:08X} = 0x{pll_cfg:08X}")
        else:
            print(f"  0x{mc3.PLL0_CFG:08X} skipped")
        print(f"  0x{mc3.PLL0_EN:08X} = 0x{mc3.PLL0_ENABLE:08X}")
        print(f"  0x{mc3.PLL0_EN:08X} = 0x{mc3.DEFAULT_PLL0_ENABLE:08X}")
        if update_rolltime:
            print(f"  0x{mc3.ROLLTIME:08X} = 0x{rolltime:08X}")
        if not confirm("Run cold hash-frequency setup now?"):
            return

        try:
            mc3.cold_set_hash_frequency(
                asic,
                frequency_mhz,
                start_chip_id=first_chip_id,
                chip_num=mc3.CHIP_NUM_ALL,
                write_pll_config=write_pll_config,
                update_rolltime=update_rolltime,
                debug=self.debug,
            )
            time.sleep(0.1)
            print("")
            print("Post-write hash-frequency status")
            print("Chip  CFG OK  Locked  Rolltime OK  PLL0_CFG     PLL0_EN      ROLLTIME")
            print("----  ------  ------  -----------  ----------  ----------  ----------")
            for chip_id in chip_ids:
                status = mc3.read_hash_frequency_status(asic, chip_id, debug=self.debug)
                cfg_ok = status["pll0_cfg"] == pll_cfg
                rolltime_ok = (not update_rolltime) or status["rolltime"] == rolltime
                print(
                    f"{chip_id:>4}  "
                    f"{'yes' if cfg_ok else 'NO ':>6}  "
                    f"{'yes' if status['pll0_locked'] else 'NO ':>6}  "
                    f"{'yes' if rolltime_ok else 'NO ':>11}  "
                    f"0x{status['pll0_cfg']:08X}  "
                    f"0x{status['pll0_en']:08X}  "
                    f"0x{status['rolltime']:08X}"
                )
            self.mc3_hash_frequency_mhz = frequency_mhz
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 cold hash-frequency setup failed: {exc}")

    def mc3_spdlog_hashrate_test(self):
        asic = self.require_asic()
        if not asic:
            return

        print("Starts distinct-range app-note work, runs the MC3 SPD logger, and reports measured GH/s per chip.")
        first_chip_id, chip_count, version_mask_bits = self.prompt_mc3_range_settings()
        frequency_mhz = prompt_int(
            "Configured hash frequency MHz",
            default=self.mc3_hash_frequency_mhz,
            minimum=100,
            maximum=1000,
        )
        self.mc3_hash_frequency_mhz = frequency_mhz
        rolltime = mc3.rolltime_for_pll_mhz(frequency_mhz)
        leading_zeros = prompt_int("Core target leading zeros", default=24, minimum=24, maximum=32)
        core_target = mc3.core_target_for_leading_zeros(leading_zeros)
        requested_runtime = prompt_float("SPDLOG runtime seconds", default=4.0, minimum=0.1)
        timer_count = mc3.spdlog_timer_count_for_seconds(requested_runtime)

        runtime = mc3.spdlog_runtime_seconds(timer_count)
        chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))
        work = mc3.app_note_version_rolling_work(note=(0x3001, 0, 0, 0))
        base = mc3.SPDLOG_BASE_DEFAULT
        registers = mc3.spdlog_registers(base=base)

        print(f"Requested runtime: {requested_runtime:.3f}s")
        print(f"SPDLOG timer count: 0x{timer_count:04X} ({timer_count}), actual runtime: {runtime:.3f}s")
        print(f"Using ROLLTIME for {frequency_mhz} MHz: 0x{rolltime:08X}")
        print(f"Core target 0x{core_target:02X}: {leading_zeros} leading zeros")
        print(f"GLOBAL write: 0x{mc3.GLOBAL_SPD:08X} = 0x{mc3.DEFAULT_GLOBAL_SPD_VALUE:08X}")
        print(f"WORK_CFG write: 0x{mc3.WORK_CFG:08X} = 0x{mc3.spdlog_work_cfg_value(core_target):08X}")
        print(
            f"SPDLOG registers: "
            f"TIMER=0x{registers['timer']:08X} "
            f"RST=0x{registers['rst']:08X} "
            f"PASS=0x{registers['pass']:08X} "
            f"FAIL=0x{registers['fail']:08X}"
        )
        print("SPDLOG start: broadcast GLOBAL, WORK_CFG, RST, then TIMER to the selected chip range.")
        print("The app note recommends lower difficulty for quick measurements.")
        if not confirm("Run MC3 SPD logger hashrate test now?"):
            return

        try:
            self.start_distinct_app_note_work(asic, work, first_chip_id, chip_count, version_mask_bits)
            time.sleep(0.05)
            mc3.start_spdlog_broadcast(
                asic,
                start_chip_id=first_chip_id,
                chip_num=mc3.CHIP_NUM_ALL,
                timer_count=timer_count,
                core_target=core_target,
                debug=self.debug,
            )
            spdlog_wait_seconds = max(5.0, runtime + 0.1)
            time.sleep(spdlog_wait_seconds)

            print("")
            print("Chip  Pass        Fail        Runtime   Pass GH/s  Cand GH/s  WORK_CFG    TIMER")
            print("----  ----------  ----------  --------  ---------  ---------  ----------  ----------")
            total_hashrate = 0.0
            total_candidate_hashrate = 0.0
            total_pass = 0
            total_fail = 0
            for chip_id in chip_ids:
                result = mc3.read_spdlog(
                    asic,
                    chip_id=chip_id,
                    timer_count=timer_count,
                    core_target=core_target,
                    debug=self.debug,
                )
                total_hashrate += result["hashrate_hs"]
                total_candidate_hashrate += result["candidate_hashrate_hs"]
                total_pass += result["pass"]
                total_fail += result["fail"]
                print(
                    f"{chip_id:>4}  "
                    f"{result['pass']:>10}  "
                    f"{result['fail']:>10}  "
                    f"{result['runtime_seconds']:>8.3f}  "
                    f"{result['hashrate_hs'] / 1e9:>9.2f}  "
                    f"{result['candidate_hashrate_hs'] / 1e9:>9.2f}  "
                    f"0x{result['work_cfg']:08X}  "
                    f"0x{result['timer']:08X}"
                )
            print("----  ----------  ----------  --------  ---------  ---------  ----------  ----------")
            print(
                f"ALL   {total_pass:>10}  {total_fail:>10}            "
                f"{total_hashrate / 1e9:>9.2f}  "
                f"{total_candidate_hashrate / 1e9:>9.2f}"
            )
            if total_pass == 0 and total_fail > 0:
                print("")
                print("Note: SPDLOG counted failed candidates but no passes. The hash cores are not silent;")
                print("      the next thing to check is target/check configuration, not just PLL lock.")
                print("")
                print("Chip  Target H/L             ROLLTIME    PLL lock")
                print("----  ---------------------  ----------  --------")
                for chip_id in chip_ids:
                    result = mc3.read_spdlog(
                        asic,
                        chip_id=chip_id,
                        timer_count=timer_count,
                        core_target=core_target,
                        debug=self.debug,
                    )
                    target = f"0x{result['target_h']:08X}/0x{result['target_l']:08X}"
                    locked = "yes" if result["pll0_locked"] else "NO"
                    print(
                        f"{chip_id:>4}  {target:<21}  "
                        f"0x{result['rolltime']:08X}  {locked:>8}"
                    )
        except (RuntimeError, TimeoutError) as exc:
            print(f"MC3 SPD logger hashrate test failed: {exc}")

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
        bitaxeraw.fan_set_duty(ser, 0xAC, duty, debug=self.debug)

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

    def bonanza_display_menu(self):
        field_names = tuple(bonanza_display.FIELD_SPECS)
        while True:
            print("")
            print("bonanzaDisplay")
            for index, field_name in enumerate(field_names, start=1):
                spec = bonanza_display.FIELD_SPECS[field_name]
                print(f" {index:>2}) Write {spec['label']}")
            print(f" {len(field_names) + 1:>2}) Write all dashboard values")
            print("  b) Back")
            choice = input("Display> ").strip().lower()

            if choice in ("b", "back", "q"):
                return
            try:
                option = int(choice)
            except ValueError:
                print("Unknown option")
                continue

            if 1 <= option <= len(field_names):
                self.bonanza_write_field(field_names[option - 1], prompt=True)
            elif option == len(field_names) + 1:
                self.bonanza_write_all()
            else:
                print("Unknown option")

    def prompt_bonanza_value(self, field_name):
        spec = bonanza_display.FIELD_SPECS[field_name]
        current = self.bonanza_values[field_name]
        if spec["kind"] == "string":
            return prompt_string(
                spec["label"],
                default=current,
                maximum=spec["size"] - 1,
                ascii_only=True,
            )
        maximum = 100 if field_name == "fan_percent" else 0xFFFFFFFF
        return prompt_int(spec["label"], default=current, minimum=0, maximum=maximum)

    def bonanza_write_field(self, field_name, prompt=False, command_id=0xAE):
        ser = self.require_control()
        if not ser:
            return False

        if prompt:
            self.bonanza_values[field_name] = self.prompt_bonanza_value(field_name)
        value = self.bonanza_values[field_name]
        spec = bonanza_display.FIELD_SPECS[field_name]
        try:
            bonanza_display.write_field(
                ser,
                command_id,
                field_name,
                value,
                debug=self.debug,
            )
        except (ValueError, RuntimeError) as exc:
            print(f"bonanzaDisplay write failed: {exc}")
            return False
        print(f"Wrote {spec['label']} = {value!r} to register 0x{spec['register']:02X}.")
        return True

    def bonanza_write_all(self):
        print("Enter the complete dashboard snapshot.")
        for field_name in bonanza_display.FIELD_SPECS:
            self.bonanza_values[field_name] = self.prompt_bonanza_value(field_name)

        print("Writing dashboard values to bonanzaDisplay at I2C address 0x3C...")
        for offset, field_name in enumerate(bonanza_display.FIELD_SPECS):
            if not self.bonanza_write_field(
                field_name,
                command_id=(0xB0 + offset) & 0xFF,
            ):
                print("Stopped dashboard write after the first error.")
                return False
        print("bonanzaDisplay dashboard write complete.")
        return True

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


def prompt_string(prompt, default, maximum=None, ascii_only=False):
    while True:
        response = input(f"{prompt} [{default}]: ").strip()
        value = response if response else default
        if ascii_only:
            try:
                value.encode("ascii")
            except UnicodeEncodeError:
                print("Enter ASCII characters only.")
                continue
        if maximum is not None and len(value) > maximum:
            print(f"Enter at most {maximum} characters.")
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
        help="Print raw control packets where supported.",
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
