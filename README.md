# Anvil

Anvil is an interactive Python bringup console for bitaxe prototypes running
`bitaxe-raw` firmware on the ESP32. This version of Anvil is for the bitaxeProto-1102x with four MC3 ASICs.

## Features

- Auto-connects to the bitaxe-raw control and ASIC serial ports.
- Configures, enables, disables, and monitors the TPS546D24S voltage regulator.
- Controls Proto MC3 VDDIO 5V enable.
- Enumerates the MC3 ASIC chain over the ULink UART interface.
- Starts an MC3 version-rolling mining smoke test from the static app-note work vector.
- Reads the MC3 version-rolling nonce buffer.
- Sends raw ASIC UART test patterns for logic-analyzer debugging.
- Sets fan speed percent or raw active-low PWM byte and reads/polls fan RPM.
- Writes identity and mining metrics to a bonanzaDisplay over the dedicated DISP I2C bus.
- Lists available serial ports to help identify the control and ASIC interfaces.

## Usage

```bash
./Anvil.py
```

Default ports:

```text
Control serial: /dev/cu.usbmodem90ea13d31 @ 115200
ASIC serial:    /dev/cu.usbmodem90ea13d33 @ 115200
```

Override ports when needed:

```bash
./Anvil.py --ctrl-port /dev/cu.usbmodemXXXX --asic-port /dev/cu.usbmodemYYYY
```

Use `--debug` to print extra low-level control packets.

## TPS546 Current Calibrator

`Calibrator.py` automates TPS546 current telemetry sweeps with a Rigol DL3021
electronic load connected over LAN. Initialize and enable the TPS546 in Anvil,
quit Anvil so it releases the control serial port, and then run:

```bash
./Calibrator.py
```

The defaults connect to the load at `192.168.1.176:5555`, sweep from 0 A to
20 A in 1 A steps, settle for 2 seconds at each step, average 10 samples, and
write a timestamped CSV file under `local/`. The CSV contains both DL3021
voltage/current/power measurements and TPS546 VIN/VOUT/IOUT/temperature data.

For an up/down high-current validation with a five-minute soak at 40 A:

```bash
./Calibrator.py \
  --stop-current 40 \
  --sweep both \
  --top-soak-seconds 300 \
  --max-vr-temp 100
```

Review the displayed plan and confirm before starting. Calibrator aborts if
VOUT collapses, VR temperature exceeds the configured limit, or load power
exceeds the configured limit. It also verifies the DL3021 mode, setpoint, and
measured current at every step. It sets the load to 0 A and turns its input
off after success, failure, or Ctrl-C. Top-current soak periods are also
monitored continuously using the same safety limits.

## Firmware Expectations

Anvil expects a bitaxe-raw firmware build with these control pages:

```text
GPIO page: 0x06
  0x00 = ASIC reset
  0x01 = VDDIO 5V enable, ESP32 GPIO21
  0x02 = TPS546 enable, ESP32 GPIO10

FAN page: 0x08
  0x00 = set active-low PWM byte, raw 0-255
  0x01 = read RPM, little-endian u32

DISP page: 0x09
  0x20 = write to the dedicated display I2C bus
```

The `bonanzaDisplay` menu writes the display at address `0x3C`. String fields
are bounded NUL-terminated ASCII and numeric fields are unsigned 32-bit
little-endian values, matching the bonanzaDisplay register protocol.

The ASIC serial port is the second USB CDC interface and is bridged by
bitaxe-raw to ESP32 UART1:

```text
ASIC TX: ESP32 GPIO17
ASIC RX: ESP32 GPIO18
```

MC3 ULink starts at 115200 baud.

## bitaxeProto 1102x Pin Mapping

```text
VDDIO 5V Enable | ESP32 GPIO21
FAN PWM         | ESP32 GPIO8
FAN TACH        | ESP32 GPIO9
ASIC Reset      | ESP32 GPIO1
TPS546 Enable   | ESP32 GPIO10
ASIC TX         | ESP32 GPIO17
ASIC RX         | ESP32 GPIO18
Board SDA       | ESP32 GPIO47
Board SCL       | ESP32 GPIO48
Display GPIO1   | ESP32 GPIO4
Display GPIO2   | ESP32 GPIO5
Display SCL     | ESP32 GPIO6
Display SDA     | ESP32 GPIO7
```

## Current Bringup Flow

1. Start Anvil.
2. Use `TPS546 voltage regulator` to initialize and turn on core voltage.
   `Turn regulator ON` prompts for `VOUT_COMMAND` between the configured
   `VOUT_MIN` and `VOUT_MAX` and prints the expected MC3 VDD as half of the
   TPS546 output voltage.
3. Use `Proto MC3 ASICs` to enable VDDIO 5V.
4. Run `Enumerate MC3 chain`; a healthy four-chip chain reports:

```text
MC3 chain count: 4
```

5. Run `Read MC3 voltage/temp` to configure the on-chip sensors and read each
   addressed ASIC. The default sub-option is a compact rail summary with chip
   temperature and `VDDIO12`, `VDDH`, `VDDI1`, `VDDI2`, `VDDI3`, and `VDD`.
   `VDDIO12` and `VDD` are displayed after a 2x prescaler correction. Raw
   channel scan and voltage matrix diagnostics remain available from the
   sensor submenu.
6. Run `Start app-note MC3 mining test` to write the static version-rolling
   work vector from `local/MC3 Application Note - Mining Process.pdf`, or run
   `Start app-note mining with distinct chip ranges` to assign each chip a
   separate version range before broadcasting the work trigger. With the
   default 16-bit version mask and four chips, the V_BASE values are
   `0x20000000`, `0x20004000`, `0x20008000`, and `0x2000C000`.
   This assumes TPS core voltage is on, VDDIO 5V is on, 25 MHz CLKI is present,
   and the MC3 chain has already been enumerated with INIT.
7. Run `Read MC3 nonce buffer(s)` to optionally issue `NONCE_UPDATE` and read
   and validate the version-rolling nonce buffer for one chip or all chips in
   the chain.
8. Run the optional app-note mining smoke tests before integrating a full miner:
   `Poll app-note mining health` repeatedly starts fresh app-note work with a
   new note and validates all selected nonce buffers for a bounded duration,
   `App-note work note rollover test`
   confirms buffers follow new work notes, and `App-note target-rate sanity test`
   compares returned nonce counts between an easy and harder work target and
   prints an approximate hashrate when the nonce count is measurable.
9. Use `Set/verify MC3 hash frequency` to read back `PLL0_CFG`, `PLL0_EN`
   lock, and `ROLLTIME` for each chip. It skips PLL writes when the selected
   chips already match. Forced writes use the errata PLL sequence:
   disable PLL0, write `PLL0_CFG`, write `PLL0_EN=0x1`, write `PLL0_EN=0x3`,
   then update `ROLLTIME`.
10. Use `Cold-set MC3 hash frequency` immediately after ASIC reset/enumeration,
    before mining or SPDLOG, to try the app-note startup PLL order:
    `GLOBAL`, optional `PLL0_CFG`, `PLL0_EN=0x1`, `PLL0_EN=0x3`, then matching
    `ROLLTIME`.
11. Use `MC3 SPD logger hashrate test` to run the documented speed logger,
    read per-chip pass/fail counters from the confirmed `0x11000` SPDLOG base,
    and report measured GH/s.
12. Use `Fan` to set speed percent or raw active-low PWM byte and verify tach/RPM.
13. Use `bonanzaDisplay` to write individual identity/mining fields or enter and
    send a complete dashboard snapshot.

## Tests

Run the pure MC3 mining layout and fake-serial tests with:

```bash
python3 -m unittest discover -v
```
