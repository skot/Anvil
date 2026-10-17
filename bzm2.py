"""BZM2 bringup over bitaxe-raw-bonanza's asymmetric 9-bit bridge.

Register offsets/commands: Intel Blockscale 1000 Series datasheet v1.3,
sections 8.1.7 and 8.1.11. Sensor/PLL sequences and wire byte ordering
follow ESP-miner-bonanza components/asic/{bzm_transport,bzm_bringup}.c.
All transactions here use polled, non-TDM mode. No unsolicited TX is enabled.
"""

import hashlib
import math
import struct
import time

import bitaxeraw

DEFAULT_ADDRESS = 0xFA  # next unassigned ASIC, NOT all-ASIC broadcast
ALL_ASICS = 0xFF
CONTROL_ENGINE = 0xFFF
DEFAULT_CHIP_IDS = (0x0A, 0x14, 0x1E, 0x28)
REG_ASIC_ID = 0x0B
REG_TDM_CONTROL = 0x07
REG_ENGINE_RESET = 0x16
PLL_REGISTERS = ((0x10, 0x11, 0x12), (0x1A, 0x1B, 0x1C))


def _range(name, value, low, high):
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be {low}..{high}')
    return value


def _header(asic, opcode, engine, offset, count):
    _range('ASIC address', asic, 0, 255)
    _range('engine ID', engine, 0, 0xFFF)
    _range('register offset', offset, 0, 255)
    _range('byte count', count, 1, 256)
    return [0x100 | asic, opcode | (engine >> 8), engine & 255, offset, count - 1]


def read_register(ser, asic, offset, count=4, engine=CONTROL_ENGINE, debug=False):
    packet = _header(asic, 0x30, engine, offset, count) + [0]
    bitaxeraw.asic_write(ser, packet, debug)
    reply = bitaxeraw.asic_read(ser, count + 2, debug)
    if reply[:2] != bytes([asic, 0x03]):
        raise RuntimeError(f'Unexpected register reply header: {reply.hex(" ")}; reset/re-enumerate chain')
    return reply[2:]


def write_register(ser, asic, offset, data, engine=CONTROL_ENGINE, debug=False):
    data = bytes(data)
    packet = _header(asic, 0x20, engine, offset, len(data)) + list(data) + [0]
    bitaxeraw.asic_write(ser, packet, debug)


def read_u32(ser, asic, offset, debug=False):
    return int.from_bytes(read_register(ser, asic, offset, debug=debug), 'little')


def write_u32(ser, asic, offset, value, debug=False):
    _range('register value', value, 0, 0xFFFFFFFF)
    write_register(ser, asic, offset, value.to_bytes(4, 'little'), debug=debug)


def write_verified(ser, asic, offset, value, debug=False):
    write_u32(ser, asic, offset, value, debug)
    actual = read_u32(ser, asic, offset, debug)
    if actual != value:
        raise RuntimeError(f'ASIC {asic:02X} reg {offset:02X}: wrote {value:08X}, read {actual:08X}')


def noop(ser, asic=DEFAULT_ADDRESS, debug=False):
    _range('ASIC address', asic, 0, 255)
    bitaxeraw.asic_write(ser, [0x100 | asic, 0xF0], debug)
    reply = bitaxeraw.asic_read(ser, 5, debug)
    # Actual wire signature is 2ZB, despite the datasheet prose calling it BZM.
    if reply != bytes([asic, 0x0F]) + b'2ZB':
        raise RuntimeError(f'Invalid BZM2 NOOP response: {reply.hex(" ")}')
    time.sleep(0.001)  # datasheet requires a gap of at least three byte periods
    return reply


def reset(ctrl, asic, debug=False):
    bitaxeraw.gpio_set(ctrl, 0xA1, bitaxeraw.GPIO_ASIC_RST, 0, debug)
    time.sleep(0.1)
    bitaxeraw.gpio_set(ctrl, 0xA2, bitaxeraw.GPIO_5V_EN, 1, debug)
    time.sleep(0.1)
    bitaxeraw.gpio_set(ctrl, 0xA3, bitaxeraw.GPIO_ASIC_RST, 1, debug)
    time.sleep(0.2)
    asic.reset_input_buffer()  # reset invalidates old frames and work


def enumerate_chain(ser, chip_ids=DEFAULT_CHIP_IDS, debug=False):
    chip_ids = tuple(chip_ids)
    if not chip_ids or len(set(chip_ids)) != len(chip_ids):
        raise ValueError('Chip IDs must be nonempty and unique')
    for address in chip_ids:
        _range('assigned ASIC ID', address, 0, 0xF9)
    found = []
    for address in chip_ids:
        for attempt in range(5):
            try:
                noop(ser, debug=debug)
                break
            except TimeoutError:
                if attempt == 4:
                    raise RuntimeError(f'No unassigned BZM2 for chip {len(found) + 1}; found {found}')
                time.sleep(0.2)
                ser.reset_input_buffer()
        write_u32(ser, DEFAULT_ADDRESS, REG_ASIC_ID, address | (0x100 if found else 0), debug)
        time.sleep(0.2)
        expected = address | 0x100  # chain enable is set by the ASIC on ID write
        actual = read_u32(ser, address, REG_ASIC_ID, debug)
        if actual != expected:
            raise RuntimeError(f'ASIC ID readback expected {expected:08X}, got {actual:08X}')
        found.append(address)
    # An extra default-address chip is a topology mismatch, not a healthy chain.
    try:
        noop(ser, debug=debug)
    except TimeoutError:
        ser.reset_input_buffer()
        return found
    raise RuntimeError('Extra unassigned BZM2 after expected chain; reset and specify the correct chip count')


def loopback(ser, asic, data=b'\x11\x22\x33\x44', debug=False):
    data = bytes(data)
    _range('loopback count', len(data), 4, 256)
    if len(data) % 4:
        raise ValueError('Loopback requires complete four-byte words')
    _range('ASIC address', asic, 0, 255)
    # Figure 8-10 includes one TAR word before the looped payload.
    bitaxeraw.asic_write(ser, [0x100 | asic, 0xE0, 0, len(data) - 1, 0] + list(data) + [0], debug)
    reply = bitaxeraw.asic_read(ser, len(data) + 2, debug)
    # Section 8.1.7.6: ignore bit 7 of the first byte in each DWORD.
    expected = bytes([value & 0x7F if i % 4 == 0 else value for i, value in enumerate(data)])
    actual = bytes([value & 0x7F if i % 4 == 0 else value for i, value in enumerate(reply[2:])])
    if reply[:2] != bytes([asic, 0x0E]) or actual != expected:
        raise RuntimeError(f'Loopback mismatch: {reply.hex(" ")}')
    return reply[2:]


def configure_sensors(ser, chip_ids, debug=False):
    """Reference sensor settings with TDM disabled, for addressed polling."""
    for address in chip_ids:
        bandgap = read_u32(ser, address, 0x45, debug)
        values = ((0x07, 0), (0x0A, 0x0F), (0x08, 2), (0x09, 1),
                  (0x3D, (8 << 5) | 8), (0x2E, 0x100), (0x2D, 1),
                  (0x2F, 0), (0x3C, (10 << 16) | 10),
                  (0x30, 0x8001 | (2650 << 1)),
                  (0x45, (bandgap & ~0xF) | 3), (0x3E, 0x100),
                  (0x3F, (8 << 28) | (1 << 24)),
                  (0x40, (7561 << 16) | (7561 << 1) | 1))
        for offset, value in values:
            write_verified(ser, address, offset, value, debug)
    time.sleep(0.02)


def voltage_from_code(code):
    return 0.4 * 0.7067 * (6 * (code & 0x3FFF) / 16384 - 3 / 16384 - 1)


def read_sensors(ser, address, debug=False):
    temp = read_u32(ser, address, 0x32, debug)
    trip = read_u32(ser, address, 0x31, debug)
    ch0 = read_u32(ser, address, 0x41, debug)
    ch12 = read_u32(ser, address, 0x44, debug)
    return {'asic': address, 'temperature_c': -293.8 + 631.8 * ((temp & 0xFFF) - 0.5) / 4096,
            'ch0_v': voltage_from_code(ch0), 'ch1_v': voltage_from_code(ch12),
            'ch2_v': voltage_from_code(ch12 >> 16),
            'thermal_fault': bool(temp & 0x1000), 'thermal_trip': bool(trip & 1),
            'voltage_fault': bool(ch0 & (1 << 30)),
            'voltage_trip': bool(ch0 & ((1 << 31) | (1 << 29))),
            'raw': (temp, trip, ch0, ch12)}


def pll_config(frequency_mhz):
    if not math.isfinite(frequency_mhz) or not 800 <= frequency_mhz <= 2000:
        raise ValueError('BZM2 PLL frequency must be 800..2000 MHz')
    feedback = round(frequency_mhz * 8 / 50)
    return {'feedback': feedback, 'postdiv': 0x1242, 'actual_mhz': 50 * feedback / 8}


def read_plls(ser, address, debug=False):
    statuses = []
    for post_reg, fb_reg, en_reg in PLL_REGISTERS:
        post, feedback, enable = (read_u32(ser, address, r, debug) for r in (post_reg, fb_reg, en_reg))
        ref = post & 63
        div1, div2 = ((post >> 6) & 7) + 1, ((post >> 9) & 7) + 1
        frequency = 50 * feedback / (ref * div1 * div2) if ref and post & 0x1000 else None
        statuses.append({'postdiv': post, 'feedback': feedback, 'enable': enable,
                         'locked': enable & 7 == 5, 'frequency_mhz': frequency})
    return statuses


def set_frequency(ser, chip_ids, frequency_mhz, debug=False):
    config = pll_config(frequency_mhz)
    for address in chip_ids:
        for _, _, enable in PLL_REGISTERS:
            write_u32(ser, address, enable, 0, debug)
        for post, fb, _ in PLL_REGISTERS:
            write_verified(ser, address, fb, config['feedback'], debug)
            write_verified(ser, address, post, config['postdiv'], debug)
        for _, _, enable in PLL_REGISTERS:
            write_u32(ser, address, enable, 1, debug)
        for attempt in range(30):
            statuses = read_plls(ser, address, debug)
            if all(p['locked'] for p in statuses):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f'ASIC {address:02X}: PLL lock failed: {statuses}')
        # BIRDS does not enable DLL in the reference 800 MHz startup.
        write_verified(ser, address, 0x54, 0, debug)
        write_verified(ser, address, 0x5C, 0, debug)
        write_verified(ser, address, REG_ENGINE_RESET, 1, debug)
    return config


# Genesis block, serialized exactly as an 80-byte Bitcoin header.
GENESIS_HEADER = bytes.fromhex(
    '01000000' + '00' * 32 +
    '3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a'
    '29ab5f49ffff001d1dac2b7c')
# SHA256 state after compressing the first 64 bytes. Native LE h0..h7 order.
GENESIS_MIDSTATE = bytes.fromhex(
    '339a90bcf0bf58637daccc90a8ca591ee9d8c8c3c803014f3687b1961bf91947')
GENESIS_NONCE = 2083236893
# BZM counters use the per-word-swapped header order; Bitcoin uses LE nonce.
GENESIS_COUNTER_NONCE = int.from_bytes(GENESIS_HEADER[76:80], 'big')
SMOKE_ENGINES = (0, 10)  # column 0, row 0 (bottom) and row 10 (top)
GENESIS_VARIANTS = 4  # Enhanced mode requires four FIFO entries before activation.


def start_genesis_test(ser, chip_ids, sequence=1, debug=False):
    """Bounded known-answer work on one engine in each voltage domain.

    No version/timestamp rolling, continuous looping, or full-chip activation.
    Returns results around the known genesis nonce; no pool connection needed.
    """
    _range('sequence', sequence, 0, 63)
    for address in chip_ids:
        # Freeze autonomous collection: this smoke test owns the selected
        # engine FIFOs and reads/pops them directly (datasheet 8.1.9.2).
        write_verified(ser, address, 0x00, 1, debug)
        write_verified(ser, address, 0x0A, 0x0F, debug)
        for engine in SMOKE_ENGINES:
            write_register(ser, address, 1, b'\x04', engine, debug)
            write_register(ser, address, 0x39, b'\x02', engine, debug)
            values = ((0x49, b'\0'), (0x48, b'\0'),
                      (0x3C, struct.pack('<I', (GENESIS_COUNTER_NONCE - 128) & ~1)),
                      (0x40, struct.pack('<I', (GENESIS_COUNTER_NONCE + 128) & ~1)),
                      (0x30, GENESIS_HEADER[64:68][::-1]),
                      (0x34, GENESIS_HEADER[68:72][::-1]),
                      (0x44, GENESIS_HEADER[72:76][::-1]))
            for offset, data in values:
                write_register(ser, address, offset, data, engine, debug)
            # Datasheet 8.1.9.1: starting before all four enhanced-mode jobs
            # have been loaded drops the job. Keep the header identical and
            # tag each copy with its two-bit variant; no version rolling.
            for _ in range(GENESIS_VARIANTS):
                write_register(ser, address, 0x10, GENESIS_MIDSTATE, engine, debug)
            for variant in range(GENESIS_VARIANTS):
                write_register(ser, address, 0x38, bytes([(sequence << 2) | variant]), engine, debug)
        # Program both domains before activating the pair.
        for engine in (10, 0):
            write_register(ser, address, 0x39, b'\x03', engine, debug)


def stop_genesis_test(ser, chip_ids, debug=False):
    for address in chip_ids:
        for engine in SMOKE_ENGINES:
            write_register(ser, address, 0x39, b'\x02', engine, debug)
            write_register(ser, address, 1, b'\x63', engine, debug)


def read_result(ser, address, debug=False):
    _range('ASIC address', address, 0, 255)
    bitaxeraw.asic_write(ser, [0x100 | address, 0x10], debug)
    response = bitaxeraw.asic_read(ser, 10, debug)
    if response[:2] != bytes([address, 1]):
        raise RuntimeError(f'Invalid result header: {response.hex(" ")}')
    engine_status = int.from_bytes(response[2:4], 'big')
    return {'asic': address, 'engine': engine_status & 0xFFF, 'status': engine_status >> 12,
            'valid': bool(engine_status & 0x8000),
            'nonce': int.from_bytes(response[4:8], 'little'),
            'sequence': response[8], 'time': response[9]}


def read_engine_result(ser, address, engine, debug=False):
    """Read a stable engine result and pop it last, with autonomous reads frozen.

    Engine offsets 0x70..0x77 contain valid, sequence, time, LE nonce, and
    read-to-pop. The nonce fields stay stable until the final pop byte.
    """
    _range('engine ID', engine, 0, 0xEFF)
    data = read_register(ser, address, 0x70, 8, engine, debug)
    valid = bool(data[0] & 1)
    if valid and not data[7] & 1:
        raise RuntimeError(f'ASIC {address:02X} engine {engine}: valid result was not popped')
    return {'asic': address, 'engine': engine,
            'status': (8 if valid else 0) | (1 if data[0] & 8 else 0),
            'valid': valid, 'nonce': int.from_bytes(data[3:7], 'little'),
            'sequence': data[1], 'time': data[2]}


def validate_genesis_result(result, sequence, nonce_offset=0x4C):
    """0x4C from the reference fork is verified on unit #2's 800 MHz smoke test."""
    counter_nonce = (result['nonce'] - nonce_offset) & 0xFFFFFFFF
    nonce = int.from_bytes(counter_nonce.to_bytes(4, 'little'), 'big')
    header = GENESIS_HEADER[:76] + struct.pack('<I', nonce)
    digest = hashlib.sha256(hashlib.sha256(header).digest()).digest()
    return (result['valid'] and result['sequence'] >> 2 == sequence and result['time'] == 0 and
            result['engine'] in SMOKE_ENGINES and nonce == GENESIS_NONCE and
            digest[::-1].hex() == '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f')
