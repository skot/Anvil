import serial
import time

PAGE_I2C = 0x05
PAGE_GPIO = 0x06
PAGE_ADC = 0x07
PAGE_FAN = 0x08
PAGE_DISP = 0x09

I2C_WRITE_CMD = 0x20

GPIO_HIGH = 0x01
GPIO_LOW = 0x00

GPIO_ASIC_RST = 0x00
GPIO_5V_EN = 0x01
GPIO_VDDIO_5V_EN = GPIO_5V_EN
GPIO_TPS546_EN = 0x02

ADC_DOMAIN1 = 0x50
ADC_DOMAIN2 = 0x51
ADC_DOMAIN3 = 0x52

FAN_SET_DUTY_CMD = 0x00
FAN_READ_RPM_CMD = 0x01
FAN_DUTY_MAX = 255

def prettyHex(data):
    return ' '.join(f'{byte:02X}' for byte in data)

def prettyHex9(data):
    """
    Convert a list of 8-bit bytes to 9-bit values and format as hex strings.
    Every two bytes are combined into one 9-bit value:
    - First byte: Lower 8 bits (bits 0-7)
    - Second byte: Bit 8 (only LSB is used, 0 or 1)
    
    Args:
        data: List of u8 bytes (pairs represent 9-bit values)
    
    Returns:
        String with formatted 9-bit hex values like "1FA 0F0 042"
    """
    result = []
    for i in range(0, len(data), 2):
        if i + 1 < len(data):
            lower_byte = data[i]
            upper_byte = data[i + 1] & 0x01  # Only bit 8 is used
            value = (upper_byte << 8) | lower_byte
            result.append(f'{value:03X}')
    return ' '.join(result)

def disp_write(ser, id, address, register, data, debug=False):
    """Write a register and payload through bitaxe-raw's DISP I2C page."""
    try:
        payload = bytes(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("display data must contain bytes in the range 0..255") from exc

    for label, value in (("command ID", id), ("I2C address", address), ("register", register)):
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{label} must be in the range 0..255")

    packet_len = 8 + len(payload)
    if packet_len > 0xFFFF:
        raise ValueError("display write is too large for a bitaxe-raw packet")

    packet = bytes([
        packet_len & 0xFF,
        packet_len >> 8,
        id,
        0x00,
        PAGE_DISP,
        I2C_WRITE_CMD,
        address,
        register,
    ]) + payload

    if debug:
        print("ctrl disp tx: [%s]" % prettyHex(packet))

    ser.write(packet)
    rxdata = ser.read(4)
    if len(rxdata) != 4:
        raise RuntimeError(f"display write expected a 4-byte response, got {len(rxdata)}")
    if debug:
        print("ctrl disp rx: [%s]" % prettyHex(rxdata))
    if rxdata[2] != id:
        raise RuntimeError(
            "display write command ID mismatch: expected %02X, got %02X"
            % (id, rxdata[2])
        )
    return rxdata

def fan_set_duty(ser, id, duty, debug=False):
    duty = max(0, min(FAN_DUTY_MAX, int(duty)))
    packet_len = 7
    packet = bytes([packet_len, 0x00, id, 0x00, PAGE_FAN, FAN_SET_DUTY_CMD, duty])

    print("ctrl fan tx: [%s]" % prettyHex(packet))

    ser.write(packet)

    # wait for the response
    rxdata = ser.read(4)
    if rxdata:
        bytes_read = len(rxdata)
        if bytes_read > 0:
            if debug:
                print("ctrl fan rx: [%s]" % prettyHex(rxdata))
            else:
                print("ctrl fan rx: [%s]" % prettyHex(rxdata))
            if rxdata[2] != id:
                print("Error: ID mismatch. Expected %02X, got %02X" % (id, rxdata[2]))
                return
        else:
            print("No data received")
            return
    else:
        print("No data received")
    return

def fan_set_speed(ser, id, speed_percent, debug=False):
    duty = fan_speed_percent_to_raw_duty(speed_percent)
    return fan_set_duty(ser, id, duty, debug=debug)

def fan_speed_percent_to_raw_duty(speed_percent):
    speed_percent = max(0, min(100, int(speed_percent)))
    return FAN_DUTY_MAX - round(speed_percent * FAN_DUTY_MAX / 100)

def get_fan_rpm(ser, id, debug=False):
    packet_len = 6
    packet = bytes([packet_len, 0x00, id, 0x00, PAGE_FAN, FAN_READ_RPM_CMD])

    print("ctrl fan rpm tx: [%s]" % prettyHex(packet))

    ser.write(packet)

    # wait for the response
    rxdata = ser.read(7)
    if rxdata:
        bytes_read = len(rxdata)
        if bytes_read >= 7:
            if debug:
                print("ctrl fan rpm rx: [%s]" % prettyHex(rxdata))
            else:
                print("ctrl fan rpm rx: [%s]" % prettyHex(rxdata))
            if rxdata[2] != id:
                print("Error: ID mismatch. Expected %02X, got %02X" % (id, rxdata[2]))
                return
            rpm = int.from_bytes(rxdata[3:7], "little")
            return rpm
        else:
            print(f"Error: Expected 7 bytes, got {bytes_read}")
            return
    else:
        print("No data received")
    return

def gpio_set(ser, id, gpio, value, debug=False):
    packet_len = 7
    packet = bytes([packet_len, 0x00, id, 0x00, PAGE_GPIO, gpio, value])

    if debug:
        print("ctrl gpio tx: [%s]" % prettyHex(packet))

    ser.write(packet)

    # wait for the response
    rxdata = ser.read(4)
    if rxdata:
        bytes_read = len(rxdata)
        if bytes_read > 0:
            if debug:
                print("ctrl gpio rx: [%s]" % prettyHex(rxdata))
            if rxdata[2] != id:
                print("Error: ID mismatch. Expected %02X, got %02X" % (id, rxdata[2]))
                return
        else:
            print("No data received")
            return
    else:
        print("No data received")
    return

#asic_write takes an list of u16 values and writes them as u8 bytes to the serial port
# Data is sent/received as pairs of bytes:
# - **First byte**: Lower 8 bits of the 9-bit word (bits 0-7)
# - **Second byte**: Bit 8 (only LSB is used, can be 0 or 1)
def asic_write(ser, data, debug=False):
    ser.reset_input_buffer()
    packet = []
    for value in data:
        lower_byte = value & 0xFF
        upper_byte = (value >> 8) & 0x01  # Only bit 8 is used
        packet.append(lower_byte)
        packet.append(upper_byte)

    if debug:
        print("asic tx: [%s]" % prettyHex(packet))
        print("asic tx9: [%s]" % prettyHex9(packet))

    ser.write(packet)
    return

def asic_read(ser, length, debug=False):
    expected_bytes = length * 2  # Each u16 is sent as 2 bytes
    rxdata = ser.read(expected_bytes)

    if len(rxdata) != expected_bytes:
        print(f"Error: Expected {expected_bytes} bytes, got {len(rxdata)} bytes")
        if debug:
            print("      asic rx: [%s]" % prettyHex9(rxdata))
        return []
    
    if debug:
        print("asic rx: [%s]" % prettyHex9(rxdata))

    data = []
    for i in range(0, len(rxdata), 2):
        lower_byte = rxdata[i]
        upper_byte = rxdata[i + 1] & 0x01  # Only bit 8 is used
        value = (upper_byte << 8) | lower_byte
        data.append(value)

    return data
