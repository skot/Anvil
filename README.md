# Anvil for bitaxeBonanza-1004x

Interactive Python bringup console for four BZM2 (Intel Blockscale) ASICs on
bitaxeBonanza-1004x. Requires the matching **1004x version** of
`bitaxe-raw-bonanza` on the ESP32 and a programmed RP2040 ASIC UART bridge.
Board I2C, fan, reset, trip, 5 V enable and domain ADCs are handled by the ESP32.
The RP2040 is used for the ASIC 9-bit UART data path.

```bash
python3 -m pip install pyserial
./Anvil.py
```

A single connected `BitaxeBonanza` is discovered automatically on macOS. The
fallback ports for the current board are `/dev/cu.usbmodem2553f62b1` (control)
and `/dev/cu.usbmodem2553f62b3` (ASIC). Override either when needed:

```bash
./Anvil.py --ctrl-port /dev/cu.usbmodemXXXX1 --asic-port /dev/cu.usbmodemXXXX3
./Anvil.py --probe --debug
```

`--probe` reads local ESP32 GPIO, fan, ADC and firmware status without enabling
power. It does not prove that the RP2040 is programmed or that ASICs respond.
The older firmware that forwards board control to the RP2040 is incompatible;
Anvil checks the ESP32's `bitaxe-raw-bonanza/1004x/` identity before power-on or
enumeration. The firmware checkout is
`~/Bitcoin/bitaxe-raw/bitaxe-raw-bonanza`.

## 1004x pin mapping

| Function | ESP32 GPIO |
| --- | --- |
| ASIC reset (active-low) | 1 |
| ASIC trip (active-high) | 2 |
| D3 cumulative voltage tap | 3 |
| D2 cumulative voltage tap | 4 |
| D1 cumulative voltage tap | 5 |
| Fan PWM (25 kHz, active-low) | 8 |
| Fan tach (2 pulses/revolution) | 9 |
| TPS546 enable | 10 |
| TPS546 PGOOD | 11 |
| ASIC UART TX/RX to RP2040 | 17 / 18 |
| 5 V enable | 21 |
| Board I2C SDA/SCL | 47 / 48 |

The domain mapping was checked against a netlist exported from the saved
1004x KiCad schematic: GPIO5/R53/TP58 is D1, GPIO4/R32/TP59 is D2, and
GPIO3/R31/TP60 is D3. Each input uses a 5.1 kΩ series resistor and 100 nF
filter capacitor, without a voltage divider. Firmware returns 16-sample averaged,
curve-calibrated millivolts at 11 dB attenuation. These are cumulative taps
relative to board ground; Anvil calculates individual ASIC voltages, bottom to
top, as `D1`, `D2-D1`, `D3-D2`, and `TPS VOUT-D3`. The 0.0.2 ESP firmware
was found to use the HAL's ADC2 eFuse data for ADC1 and omit ADC reference setup.
The 0.0.3 ESP build backports [the upstream calibration fix](https://github.com/esp-rs/esp-hal/pull/4286).
The user measured taps 0.694/1.398/2.104 V and total VDD 2.802 V with a DMM,
versus earlier ESP readings 0.467/1.175/1.897 V. After flashing 0.0.3, a powered
probe read taps 0.669/1.373/2.086 V and TPS VOUT 2.789 V, giving individual ASIC
drops of 0.669/0.704/0.713/0.703 V. The large under-reading is substantially
corrected. Anvil applies no guessed offset to make readings match.

A fresh DMM comparison after the update gave taps 0.6987/1.3915/2.0986 V and
VDD 2.8030 V; the following Anvil probe read 0.667/1.371/2.085 V and TPS VOUT
2.789 V. Tap errors were -31.7/-20.5/-13.6 mV, within the calibrated ATTEN3
±50 mV range in the [ESP32-S3 datasheet, table 5-6](https://documentation.espressif.com/esp32-s3_datasheet_en.pdf).
These were sequential readings, not simultaneous acquisition. The DMM-derived
chip supplies were 0.6987/0.6928/0.7071/0.7044 V (14.3 mV spread). Thus the
remaining low-looking first-chip supply in Anvil is a measurement artifact;
this comparison does not establish another calibration software defect.

## Bringup

1. Load the updated ESP32 firmware; program the RP2040 UART bridge before
   attempting ASIC communication. Local fan/TPS/ADC functions work independently
   of the RP2040.
   For NOOP/address tests without core VDD, use the I/O-only tests below.
2. Use `TPS546 voltage regulator` → `Initialize`. This installs the Bonanza
   profile and leaves PMBus `OPERATION` off.
3. Turn the regulator on. Anvil forces the fan to full speed, asserts reset,
   disables 5 V, then enables the core rail. Default aggregate voltage is 2.8 V,
   averaging 0.7 V per ASIC across four series chips.
4. Use `Read domain/chip voltages` to inspect stack balance.
5. Use `Bonanza BZM2 ASICs` → `Reset and enumerate`. This checks PGOOD/trip,
   asserts reset, enables 5 V and releases reset, then assigns IDs
   `0x0A, 0x14, 0x1E, 0x28`. Each ID is proved by exact register readback;
   missing or extra chips fail enumeration.
6. Configure/read BZM2 voltage and temperature sensors. This uses addressed
   polling with TDM disabled. Inspect raw values and fault/trip flags.
7. Initialize/verify both PLL domains at the reference 800 MHz startup setting.
8. Run the bounded genesis test. It programs one bottom/top engine pair per
   ASIC over a small nonce range containing the known genesis solution, then
   checks the sequence, engine, timestamp and double-SHA256 result. Engines
   are stopped and clock-gated afterward, including on failure or interruption.
9. Fan percent and raw-duty controls retain Proto's active-low behavior:
   raw `0` is full speed and `255` is stopped.

The ESP32 monitors ASIC trip independently of USB requests. A trip latches
reset asserted, 5 V disabled and fan full speed. After the trip input clears,
an explicit reset assertion while 5 V is off acknowledges the latch. The
`Assert ASIC reset and disable 5V` action establishes this state; reset/enumerate
can then be retried. Disconnecting control USB also asserts reset, disables
5 V and forces full fan speed. The TPS output is controlled separately by
PMBus and may remain enabled after quitting, so the current calibrator can run.

## I/O-only tests with ASIC VDD off

ASIC menu action **15** opens manual `5V_EN` controls: **1** turns it on,
**2** turns it off, and **3** reads its GPIO command state. Both power actions
assert ASIC reset and invalidate cached ASIC addresses/clocks/sensors. TPS/core
settings are unchanged. The selected 5 V state remains when returning to the
ASIC menu; turn it off explicitly when finished. Control USB disconnect also
turns 5 V off. An unsuccessful ON operation attempts to restore reset/5 V off.

ASIC menu actions **13** (first-chip NOOP) and **14** (core-off address assignment
diagnostic) exercise the ASIC UART with TPS/core VDD disabled and `5V_EN` on
only during the test. The first chip can respond in this state. **Full four-chip
enumeration requires core VDD on this board**; enable the TPS output and use
ASIC menu **1: Reset and enumerate** for that path. Menu 14 and the command below
remain available to reproduce the core-off behavior, with the requested chip
count enforced even when fewer chips respond.
Equivalent command-line actions are:

```bash
./Anvil.py --bzm-io-test noop --yes
./Anvil.py --bzm-io-test assign --chips 4 --yes
```

Omit `--yes` for a confirmation prompt. Each test asserts reset, turns 5 V off,
disables PMBus `OPERATION` and TPS enable, then waits for PGOOD low and measured
VOUT/domain taps at or below 0.2 V. The 0.2 V threshold checks discharge; it is
not an ASIC VDD operating setting. Anvil enables 5 V, releases reset, clears
old ASIC replies and checks core-off conditions again before sending commands.

The NOOP test checks three exact `FA 0F 32 5A 42` replies from the first
unassigned ASIC. Assignment tests enumerate the requested number of chips
(default four), using IDs `0x0A, 0x14, 0x1E, 0x28`, verify each `ASIC_ID`
including its chain-enable bit, and reject an extra default-address responder.
Identity after assignment is proved by register readback. NOOPs are used at the
default address during discovery, following the reference bringup sequence.
The datasheet describes enumeration in sections 6.3/8.1.4 and NOOP in 8.1.7.7;
its page-46 sample specifies the `2ZB` reply despite different prose/figure
labels on page 45.

Success, failure and Ctrl-C all assert reset and turn 5 V off. Core power is
never enabled. Assigned IDs are discarded afterward, so these tests do not
establish the managed powered chain needed by PLL/sensor/mining operations.
The normal reset/enumerate path retains its PGOOD/core-voltage requirements.

On the connected board, all three NOOP queries passed with core output off,
PGOOD low and zero domain taps. The four-chip assignment test assigned/read
`ASIC_ID=0x0000010A` on the first ASIC but failed because chip two did not answer
at `0xFA`, despite all four ASICs being populated. After those timeouts the first
ASIC still returned its ID, `UART_LINE_CTL=0x24` and `SLOW_CLK_DIV=2`. The user
subsequently enabled VDD and reported responses from all four ASICs, establishing
the core-power requirement for full-chain access on this board. Cleanup after
the core-off test confirmed reset asserted, 5 V/TPS off, fan full and no trip.

## Protocol and implementation sources

The TPS546 profile was initially based on `ESP-miner-bonanza` commit `8c15195`,
`components/asic/bzm_power.c`, `include/bzm_power.h` and the extended-config
writer in `main/power/TPS546.c`. That fork labels its profile **1002**; the
profile is used here for 1004x as requested. The current 1004x settings use
325 kHz switching, 2.8 V default, 2.1–3.2 V bounds, and current calibration
`C880/E000`. Compensation is `13 11 8C 1D 08`, updated from the fork's last
byte `06` using the user's TPS546D24S calculator results. Proto's current
calibration is not reused. VOUT encoding uses the regulator's actual
`VOUT_MODE` exponent.

BZM2 commands follow the local Intel Blockscale datasheet v1.3 and the fork's
`bzm_transport.c` / `bzm_bringup.c` implementations. ASIC TX encodes each 9-bit
word as `[low byte, bit 8]`; ASIC RX is **raw bytes**, not byte pairs. USB CDC
baudrate requests do not change physical links: ESP32↔RP2040 is 2 Mbaud and
RP2040↔BZM2 is 5 Mbaud. `0xFA` addresses the next unassigned ASIC; `0xFF`
is the all-ASIC write address. NOOP returns `2ZB` on the wire.

This is a bringup console, not a full pool miner. MC3-specific mining/PLL/SPDLOG
menus are replaced with BZM2 operations. The genesis nonce correction defaults
to `0x4C` from the fork's 1002 profile, now verified on 1004x unit #2 at 800 MHz. Startup
PLL programming and sensor reads are implemented; full-chip ramping, sustained
hashrate measurement, TDM mining and version rolling are not implemented.
Legacy `mc3.py` and its isolated tests remain as reference and are not imported
by Anvil. The old dedicated bonanzaDisplay page is not exposed by this firmware;
its helper rejects writes rather than accidentally sending fan commands.

## Powered PLL and genesis qualification

After enabling the 2.8 V core rail, use ASIC menu **1** to enumerate, **3** to
configure/read sensors, **4** to program both PLL domains at 800 MHz, then **9**
for the bounded genesis test. Sensor CH0/CH1 each measure an internal
half-domain (nominally about 0.355 V); the hashing precheck accepts
0.25–0.425 V per channel, alongside temperature and fault/trip checks.

The genesis test activates only physical engine groups 0 and 10 on each ASIC,
one in each internal voltage domain. It loads four identical genesis midstates
and four distinct sequence tags before activation, as required by the enhanced
mode sequence in datasheet 8.1.9.1. Timestamp rolling and continuous looping
remain disabled. Its counter window is within 128 counts of `0x1DAC2B7C`, the
word-swapped representation of the Bitcoin genesis nonce.

Results are read directly from each selected engine's offsets `0x70..0x77`,
with the FIFO pop read last and autonomous collection frozen, following
datasheet 8.1.9.2. Each result must have a valid flag, matching logical sequence,
zero timestamp offset, and a corrected nonce that reproduces the genesis
double-SHA256 hash. Correction subtracts `0x4C` in ASIC counter order, then swaps
the bytes to obtain Bitcoin nonce `0x7C2BAC1D` (2083236893).

On 2026-10-16, unit **#2** (USB serial `72dfdc12`, ESP firmware 0.0.3) passed
all eight PLL lock/readback checks at 800 MHz and produced a verified genesis
result from all eight selected engine groups. Each raw nonce was `0x1DAC2BC8`;
returned subjob tags were recorded. Post-test ASIC temperatures were
27.1–27.7 °C, with no sensor faults or trips. Cleanup verified core VDD and 5 V
off, reset asserted, PGOOD low, and zero stack taps.

This establishes the selected engine groups' bounded known-answer operation.
It does not qualify every TCE/subjob, the full chip, sustained hashrate, or TDM
result delivery. The ASIC-level `ReadResult` opcode returned no packet during
these checks; its collection path remains unqualified. The smoke test uses the
verified direct engine-FIFO path instead.

## Load RP2040 bridge firmware from Anvil

First flash/restart the ESP32 with the SWD-enabled `bitaxe-raw-bonanza` build,
version **0.0.2 or newer**, from `~/Bitcoin/bitaxe-raw/bitaxe-raw-bonanza`.
The 1004x wiring is SWCLK on GPIO14 and bridge SWDIO on GPIO15. GPIO16 is the
separate display SWDIO line and is not driven by this loader.

Use main menu `8) RP2040 bridge firmware` to probe the link or select a complete
RP2040 `.bin` or `.uf2` file. Equivalent command-line operations are:

```bash
./Anvil.py --bridge-probe
./Anvil.py --flash-bridge /absolute/path/to/bonanza-bridge-fw.bin
./Anvil.py --flash-bridge /absolute/path/to/bonanza-bridge-fw.uf2 --yes
```

The adapted source is `~/Bitcoin/ESP-Miner/bonanza-bridge-fw`. Run its
`scripts/build-images.sh` to create `build/bonanza-bridge-fw-1004x.bin` and `.uf2`.
This 1004x build retains the 2 Mbaud host link, 5 Mbaud 9N1 ASIC link and raw RX,
and moves all power/reset/fan/trip responsibility to the ESP32. UART0 is now
read-only diagnostics (protocol 2.0); no RP2040 board-control lease is needed.

The loader displays the normalized flash-image size, CRC32 and SHA256 before
confirmation. `--yes` confirms only the explicitly selected image. UF2 blocks
must identify the RP2040 family, use aligned 256-byte payloads within the board's
2 MiB flash, and include boot2 at offset zero. Images must have a valid boot2
checksum and Cortex-M0+ vectors. A Bonanza manifest explicitly targeting another
board (for example 1002) is rejected. Select a 1004x-compatible UART bridge image;
the loader does not transform an older bridge's UART or safety behavior.

After confirmation, Anvil closes its ASIC data port, disables PMBus conversion
and TPS enable, asserts ASIC reset, disables 5 V, and waits for PGOOD to fall.
The ESP32 prevents board-power changes/I2C operations and discards ASIC data
traffic during programming. It halts both RP2040 cores, disables DMA/watchdog,
loads a small ROM-call trampoline into SRAM, and erases/programs flash in
ordered pages. Each page is byte-compared against flash readback; progress
replies include CRC32 calculated from the verified flash bytes. The target is
reset only after the full byte count and whole-image CRC match.

Programming does not enable ASIC power afterward. Initialize/enable the TPS and
reset/enumerate the BZM2 chain before using it again. On interruption, timeout,
or verification failure the loader aborts without deliberately resetting a
partial image. Retry the complete upload from offset zero; pages are not
retried automatically after a lost reply. Control USB disconnect also releases
the SWD pins and cancels the session. SWD recovery remains possible even when
the bridge image is blank or incomplete.

The programmer API uses control page `0x0A`: capabilities `0x00`, probe `0x01`,
begin `0x10`, page `0x20`, verified commit/reset `0x30`, abort `0x7F`.
Bench checks on the connected 1004x confirmed capabilities, RP2040 DPIDR
`0x0BC12477`, halting both cores, and SRAM algorithm upload/readback. A BEGIN
followed by ABORT also confirmed that 5 V enable is denied during programming
and leaves ASIC reset asserted, 5 V/TPS off, and fan output full. This check
issued no page/erase/program/commit commands. A subsequent full Anvil upload of
`bonanza-bridge-fw/build/bonanza-bridge-fw-1004x.bin` programmed and read back
30,808 bytes, verified CRC32 `FDBF2C9D`, and completed target reset successfully.
The SHA256 of that normalized BIN was
`e305990d370fac6485a89510f0ebc446de6baf60aa6920709d9592095df7d719`.
Afterward the board reported TPS enable/PGOOD low, 5 V off, reset asserted,
no trip, full fan command and zero domain taps. The later I/O-only checks above
verified NOOP and first-chip register access with core power off; full-chain
assignment, PLLs and mining remain unverified. SWD availability alone is not a
firmware startup or UART health check.
SWD follows the [RP2040 debug/ROM interface](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf);
UF2 parsing follows the [UF2 format specification](https://github.com/microsoft/uf2).

## ESP32 control pages

All packets retain `[length LE16, ID, bus=0, page, command, payload...]` framing.
Replies are `[length LE16, ID, payload...]`.

| Page | Command | Meaning / reply payload |
| --- | --- | --- |
| `0x00` | `0x01` | ESP32 firmware info: schema, protocol major/minor, string length, identity string |
| `0x00` | `0x10` | Local status: schema `1`, flags, requested raw fan duty |
| `0x05` | `0x20/0x40` | Board I2C write / register write-read |
| `0x06` | `0x00` or `0x02` | Get/set ASIC reset pin level (`0` asserts reset) |
| `0x06` | `0x01` | Get/set 5 V enable |
| `0x06` | `0x03` | Read ASIC trip |
| `0x06` | `0x04` | Get/set TPS546 enable |
| `0x06` | `0x05` | Read TPS546 PGOOD |
| `0x07` | `0x50/0x51/0x52` | Read D1/D2/D3 respectively, LE16 millivolts |
| `0x07` | `0x53` | Read all taps: D1, D2, D3, each LE16 millivolts |
| `0x08` | `0x00` | Set active-low PWM byte; echoes duty |
| `0x08` | `0x01` | Read fan RPM, LE32 |
| `0x09` | `0x10` | Fan compatibility API: set integer percent, returns `0` |
| `0x09` | `0x20` | Fan compatibility API: read RPM, LE16 |

Status flags, low bit first: 5 V enabled, reset asserted, trip input high,
trip latched, TPS enable high, PGOOD high. There are no RP2040 safety lease
commands in the 1004x ESP32 firmware. `GPIO2` is exclusively the trip input.

## TPS546 current calibrator

`Calibrator.py` retains the Rigol DL3021 LAN sweep workflow:

```bash
./Calibrator.py
./Calibrator.py --stop-current 40 --sweep both --top-soak-seconds 300 --max-vr-temp 100
```

Initialize/enable the TPS in Anvil, quit to release the control port, then run
the calibrator with the electronic load connected. Default load address is
`192.168.1.176:5555`; default sweep is 0–20 A in 1 A steps. It averages ten
samples and writes timestamped CSV output under `local/`. Voltage collapse,
VR temperature, load power and measured current are checked during the sweep;
the load is set to 0 A and its input is turned off on completion or failure.

## Validation

```bash
python3 -m unittest discover -v
```

The ESP32 board-control build `bitaxe-raw-bonanza/1004x/0.0.1` passed native and
compatibility fan-command readback, local GPIO/status reads, rejection of reset
release with 5 V off, and individual/snapshot ADC bench checks. D1/D2/D3 read 0 V with
the stack off. No fan is attached, so fan rotation/tach accuracy is untested;
ADC voltage accuracy and a physically asserted trip also remain untested.

The restart returned TPS546 settings to power-on defaults. The Bonanza profile
was reapplied and read back with `OPERATION=OFF` and TPS enable low. Run TPS
initialization again after a board power cycle; these writes do not program
TPS546 nonvolatile memory. The board was left with ASIC reset asserted, 5 V off,
TPS output off, and the fan output set to full speed.

The RP2040 has now been programmed with the adapted 1004x UART-only build from
`~/Bitcoin/ESP-Miner/bonanza-bridge-fw`, as described above. Core-off NOOP and
first-chip address/register access passed bench checks. Core-off enumeration
stops after the first chip; the user confirmed all four respond with VDD on.
Subsequent unit #2 clocking, telemetry and bounded hashing checks passed as
described above. Full-chip and sustained mining still need powered qualification;
unit tests and flash readback alone do not establish those paths work.
