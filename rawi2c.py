"""Board I2C transactions through bitaxe-raw-bonanza control framing."""

import bitaxeraw

prettyHex = bitaxeraw.prettyHex


def i2c_write_addr(ser, id, address, register, debug=False):
    return i2c_send_bytes(ser, id, address, register, [], debug)


def i2c_send_bytes(ser, id, address, register, data, debug=False):
    payload = bytes(data) if isinstance(data, (list, tuple, bytes, bytearray)) else bytes([data])
    response = bitaxeraw.control_command(
        ser, id, bitaxeraw.PAGE_I2C, 0x20, bytes([address, register]) + payload,
        debug=debug, decode_errors=False)
    if response != bytes([len(payload) + 1]):
        raise RuntimeError(f'I2C write failed: {prettyHex(response)}')
    return response


def i2c_read_bytes(ser, id, address, register, size, debug=False):
    if not 1 <= size <= 255:
        raise ValueError('I2C read size must be 1..255')
    response = bitaxeraw.control_command(
        ser, id, bitaxeraw.PAGE_I2C, 0x40, bytes([address, register, size]),
        debug=debug, decode_errors=False)
    if len(response) != size:
        raise RuntimeError(f'I2C read expected {size} bytes, received {prettyHex(response)}')
    return response
