"""bonanzaDisplay register protocol over the bitaxe-raw DISP page."""

import bitaxeraw


I2C_ADDRESS = 0x3C

FIELD_SPECS = {
    "device_family": {
        "label": "Device family",
        "register": 0x10,
        "kind": "string",
        "size": 16,
        "default": "BONANZA",
    },
    "device_model": {
        "label": "Device model",
        "register": 0x20,
        "kind": "string",
        "size": 8,
        "default": "1002",
    },
    "device_name": {
        "label": "Device name",
        "register": 0x28,
        "kind": "string",
        "size": 16,
        "default": "battleaxe",
    },
    "ip_address": {
        "label": "IPv4 address",
        "register": 0x38,
        "kind": "string",
        "size": 16,
        "default": "192.168.1.234",
    },
    "best_share": {
        "label": "Best share",
        "register": 0x48,
        "kind": "string",
        "size": 16,
        "default": "123T",
    },
    "hashrate_ghs": {
        "label": "Hashrate (GH/s)",
        "register": 0x60,
        "kind": "u32",
        "default": 1200,
    },
    "temperature_c": {
        "label": "Temperature (C)",
        "register": 0x64,
        "kind": "u32",
        "default": 58,
    },
    "power_w": {
        "label": "Power (W)",
        "register": 0x68,
        "kind": "u32",
        "default": 17,
    },
    "frequency_mhz": {
        "label": "Hash frequency (MHz)",
        "register": 0x6C,
        "kind": "u32",
        "default": 621,
    },
    "fan_percent": {
        "label": "Fan speed (%)",
        "register": 0x70,
        "kind": "u32",
        "default": 66,
    },
}


def encode_string(value, field_size):
    """Encode a fixed-field string, reserving one byte for its NUL terminator."""
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("display strings must contain ASCII characters only") from exc
    maximum = field_size - 1
    if len(encoded) > maximum:
        raise ValueError(f"display string is too long; maximum is {maximum} ASCII characters")
    return encoded + b"\x00"


def encode_u32(value):
    value = int(value)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("display number must be in the range 0..4294967295")
    return value.to_bytes(4, "little")


def encode_field(field_name, value):
    try:
        spec = FIELD_SPECS[field_name]
    except KeyError as exc:
        raise ValueError(f"unknown bonanzaDisplay field: {field_name}") from exc
    if spec["kind"] == "string":
        return encode_string(value, spec["size"])
    return encode_u32(value)


def write_field(ser, command_id, field_name, value, debug=False):
    spec = FIELD_SPECS[field_name]
    payload = encode_field(field_name, value)
    return bitaxeraw.disp_write(
        ser,
        command_id,
        I2C_ADDRESS,
        spec["register"],
        payload,
        debug=debug,
    )
