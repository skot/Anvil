# Anvil

Anvil is an interactive Python bringup console for the bitaxeProto running
`bitaxe-raw` firmware on the ESP32. It is the main tool in this folder for
exercising board features during hardware bringup.

## Features

- Auto-connects to the bitaxe-raw control and ASIC serial ports.
- Configures, enables, disables, and monitors the TPS546D24S voltage regulator.
- Controls Proto MC3 VDDIO 5V enable.
- Enumerates the MC3 ASIC chain over the ULink UART interface.
- Sends raw ASIC UART test patterns for logic-analyzer debugging.
- Sets fan PWM duty and reads/polls fan RPM.
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

## Firmware Expectations

Anvil expects a bitaxe-raw firmware build with these control pages:

```text
GPIO page: 0x06
  0x00 = ASIC reset
  0x01 = VDDIO 5V enable, ESP32 GPIO21
  0x02 = TPS546 enable, ESP32 GPIO10

FAN page: 0x08
  0x00 = set duty, raw 0-255
  0x01 = read RPM, little-endian u32
```

The ASIC serial port is the second USB CDC interface and is bridged by
bitaxe-raw to ESP32 UART1:

```text
ASIC TX: ESP32 GPIO17
ASIC RX: ESP32 GPIO18
```

MC3 ULink starts at 115200 baud.

## Pin Mapping

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
3. Use `Proto MC3 ASICs` to enable VDDIO 5V.
4. Run `Enumerate MC3 chain`; a healthy four-chip chain reports:

```text
MC3 chain count: 4
```

5. Use `Fan` to set PWM duty and verify tach/RPM.
