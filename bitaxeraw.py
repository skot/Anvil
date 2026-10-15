"""Host protocol for bitaxe-raw-bonanza (ESP32 + RP2040 bridge)."""

PAGE_SYSTEM = 0x00
PAGE_I2C = 0x05
PAGE_GPIO = 0x06
PAGE_ADC = 0x07
PAGE_FAN = 0x08

GPIO_HIGH = 1
GPIO_LOW = 0
GPIO_ASIC_RST = 0x02  # active-low level; 0 asserts reset
GPIO_5V_EN = 0x01
GPIO_VDDIO_5V_EN = GPIO_5V_EN
GPIO_ASIC_TRIP = 0x03
GPIO_TPS546_EN = 0x04
GPIO_TPS546_PGOOD = 0x05
FAN_SET_DUTY_CMD = 0x00
FAN_READ_RPM_CMD = 0x01
FAN_DUTY_MAX = 255


def prettyHex(data):
    return ' '.join(f'{byte:02X}' for byte in data)


def prettyHex9(data):
    return ' '.join(f'{data[i] | (data[i + 1] << 8):03X}' for i in range(0, len(data) - 1, 2))


def read_exact(ser, size):
    """Accumulate fragmented reads; pyserial's configured timeout bounds a stall."""
    result = bytearray()
    while len(result) < size:
        chunk = ser.read(size - len(result))
        if not chunk:
            raise TimeoutError(f'Expected {size} bytes, received {len(result)}: {prettyHex(result)}')
        result.extend(chunk)
    return bytes(result)


def control_command(ser, command_id, page, command, data=b'', debug=False, decode_errors=True):
    """Read a complete length-prefixed reply, including firmware error replies."""
    payload = bytes(data)
    length = 6 + len(payload)
    packet = length.to_bytes(2, 'little') + bytes([command_id, 0, page, command]) + payload
    if debug:
        print(f'ctrl tx: [{prettyHex(packet)}]')
    ser.write(packet)
    header = read_exact(ser, 3)
    response_length = int.from_bytes(header[:2], 'little')
    if not 3 <= response_length <= 260:
        raise RuntimeError(f'Invalid control response length: {response_length}')
    response = read_exact(ser, response_length - 3)
    if debug:
        print(f'ctrl rx: [{prettyHex(header + response)}]')
    if header[2] != command_id:
        raise RuntimeError(f'Control ID mismatch: expected {command_id:02X}, got {header[2]:02X}; reconnect ports')
    errors = {0x10: 'firmware timeout (check that 1004x ESP32 firmware is loaded)',
              0x11: 'invalid command', 0x12: 'denied by ESP32 board control', 0x13: 'ESP32 board trip/fault'}
    if decode_errors and len(response) == 1 and response[0] in errors:
        raise RuntimeError(errors[response[0]])
    if decode_errors and response[:1] == b'\xff':
        raise RuntimeError(f'Firmware error: {response[1:].decode("ascii", errors="replace")}')
    return response


def gpio_set(ser, id, gpio, value, debug=False):
    if value not in (0, 1):
        raise ValueError('GPIO level must be 0 or 1')
    response = control_command(ser, id, PAGE_GPIO, gpio, bytes([value]), debug)
    if response != bytes([value]):
        raise RuntimeError(f'GPIO {gpio:02X} did not acknowledge level {value}')
    return response


def gpio_get(ser, id, gpio, debug=False):
    response = control_command(ser, id, PAGE_GPIO, gpio, debug=debug)
    if response not in (b'\x00', b'\x01'):
        raise RuntimeError('Invalid GPIO response')
    return response[0]


def fan_speed_percent_to_raw_duty(speed_percent):
    speed_percent = max(0, min(100, int(speed_percent)))
    return 255 - round(speed_percent * 255 / 100)


def fan_set_speed(ser, id, speed_percent, debug=False):
    speed_percent = int(speed_percent)
    if not 0 <= speed_percent <= 100:
        raise ValueError('Fan speed must be 0..100 percent')
    return fan_set_duty(ser, id, fan_speed_percent_to_raw_duty(speed_percent), debug)


def fan_set_duty(ser, id, duty, debug=False):
    """Native Proto/1004x active-low byte, with no percent quantization."""
    duty = max(0, min(255, int(duty)))
    response = control_command(ser, id, PAGE_FAN, FAN_SET_DUTY_CMD,
                               bytes([duty]), debug=debug, decode_errors=False)
    if response != bytes([duty]):
        raise RuntimeError('Invalid fan duty acknowledgement')
    if duty in (0x10, 0x11, 0x12, 0x13, 0xFF):
        # Raw duty acknowledgements overlap the firmware error-byte values.
        # The ESP32 status read distinguishes success from a latched fault.
        status = control_command(ser, (id + 1) & 255, PAGE_SYSTEM, 0x10, debug=debug)
        if len(status) != 3 or status[0] != 1 or status[2] != duty:
            raise RuntimeError('Fan duty was not applied; inspect ESP32 trip/status')
    return response


def get_fan_rpm(ser, id, debug=False):
    response = control_command(ser, id, PAGE_FAN, FAN_READ_RPM_CMD, debug=debug)
    if len(response) != 4:
        raise RuntimeError(f'Fan RPM requires 4 payload bytes, got {len(response)}')
    return int.from_bytes(response, 'little')



def read_domain_voltages(ser, id=0xD4, debug=False):
    """Calibrated cumulative D1/D2/D3 taps, in volts (GPIO5/4/3)."""
    data = control_command(ser, id, PAGE_ADC, 0x53, debug=debug)
    if len(data) != 6:
        raise RuntimeError(f'Domain ADC reply requires 6 payload bytes, got {len(data)}')
    return tuple(int.from_bytes(data[i:i + 2], 'little') / 1000 for i in range(0, 6, 2))


def chip_voltages_from_taps(taps, total_vout):
    """Bottom-to-top ASIC VDD; preserve negative differences for diagnosis."""
    if len(taps) != 3:
        raise ValueError('Three cumulative stack taps are required')
    return taps[0], taps[1] - taps[0], taps[2] - taps[1], total_vout - taps[2]


def disp_write(ser, id, address, register, data, debug=False):
    raise RuntimeError('bitaxe-raw-bonanza has no dedicated DISP page; page 0x09 is a fan compatibility page')


def asic_write(ser, data, debug=False):
    """Bridge TX accepts [low 8 bits, bit 8] for each 9-bit UART word."""
    words = tuple(data)
    if any(not 0 <= value <= 0x1ff for value in words):
        raise ValueError('ASIC UART words must be in 0..0x1FF')
    packet = bytes(byte for word in words for byte in (word & 255, word >> 8))
    if debug:
        print(f'asic tx9: [{prettyHex9(packet)}]')
    written = ser.write(packet)
    if written != len(packet):
        raise RuntimeError(f'Short ASIC write: {written}/{len(packet)} bytes')
    ser.flush()


def asic_read(ser, length, debug=False):
    """Bridge RX forwards raw eight-bit bytes, without ninth-bit pairs."""
    response = read_exact(ser, length)
    if debug:
        print(f'asic rx: [{prettyHex(response)}]')
    return response


def discover_ports():
    """Choose only an unambiguous Bonanza; never silently pick between boards."""
    from serial.tools import list_ports
    ports = [p for p in list_ports.comports() if 'bitaxebonanza' in p.description.lower()]
    # macOS exposes the first and second CDC interfaces with suffixes 1 and 3.
    control = [p.device for p in ports if p.device.startswith('/dev/cu.') and p.device.endswith('1')]
    asic = [p.device for p in ports if p.device.startswith('/dev/cu.') and p.device.endswith('3')]
    if len(control) == len(asic) == 1 and control[0][:-1] == asic[0][:-1]:
        return control[0], asic[0]
    return None, None
