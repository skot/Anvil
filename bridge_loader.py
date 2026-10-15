"""Load an RP2040 flash image via bitaxe-raw-bonanza's ESP32 SWD service."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import time
import zlib

import bitaxeraw
import TPS546D24
from pmbusconst import PMBUS_OPERATION

PAGE_SWD = 0x0A
FLASH_BASE = 0x10000000
FLASH_CAPACITY = 2 * 1024 * 1024
PAGE_SIZE = 256
RP2040_FAMILY = 0xE48BFF56
HEADER_SIZE = 264


def boot2_crc(data):
    """RP2040 boot ROM's non-reflected CRC-32, initial FFFFFFFF, no final XOR."""
    crc = 0xFFFFFFFF
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
    return crc


def decode_uf2(encoded):
    if not encoded or len(encoded) % 512:
        raise ValueError('UF2 must contain complete 512-byte blocks')
    pages, block_numbers = {}, set()
    block_count = len(encoded) // 512
    for index in range(block_count):
        block = encoded[index * 512:(index + 1) * 512]
        magic0, magic1, flags, address, length, number, total, family = struct.unpack_from('<8I', block)
        if (magic0, magic1, struct.unpack_from('<I', block, 508)[0]) != (0x0A324655, 0x9E5D5157, 0x0AB16F30):
            raise ValueError('Invalid UF2 block magic')
        if flags != 0x2000 or family != RP2040_FAMILY:
            raise ValueError('UF2 must contain RP2040 main-flash blocks with a family ID')
        if length != PAGE_SIZE or address % PAGE_SIZE:
            raise ValueError('UF2 must use aligned 256-byte flash payloads')
        if not FLASH_BASE <= address <= FLASH_BASE + FLASH_CAPACITY - PAGE_SIZE:
            raise ValueError('UF2 address is outside the 2 MiB RP2040 flash')
        if total != block_count or number >= total or number in block_numbers or address in pages:
            raise ValueError('UF2 has inconsistent, duplicate or overlapping blocks')
        pages[address] = block[32:32 + length]
        block_numbers.add(number)
    if min(pages) != FLASH_BASE:
        raise ValueError('UF2 must include boot2 at flash offset zero')
    output = bytearray(b'\xff' * (max(pages) + PAGE_SIZE - FLASH_BASE))
    for address, data in pages.items():
        output[address - FLASH_BASE:address - FLASH_BASE + PAGE_SIZE] = data
    return bytes(output)


def validate_binary(image):
    if not HEADER_SIZE <= len(image) <= FLASH_CAPACITY:
        raise ValueError('RP2040 image must be 264 bytes..2 MiB, starting with boot2 at offset zero')
    if boot2_crc(image[:252]) != struct.unpack_from('<I', image, 252)[0]:
        raise ValueError('Invalid RP2040 boot2 checksum; provide a complete flash .bin or RP2040 .uf2')
    stack, reset = struct.unpack_from('<II', image, 256)
    if stack % 8 or not 0x20000000 < stack <= 0x20042000:
        raise ValueError('RP2040 initial stack pointer is invalid')
    if not reset & 1 or not FLASH_BASE + 0x100 <= (reset & ~1) < FLASH_BASE + len(image):
        raise ValueError('RP2040 reset vector is outside this image')
    # Production Bonanza images can identify the intended board in a manifest.
    magic = b'BZM-BRIDGE-FW\0\0\0'
    offset = image.find(magic)
    if offset >= 0:
        if len(image) < offset + 20:
            raise ValueError('Truncated Bonanza bridge manifest')
        board = struct.unpack_from('<H', image, offset + 18)[0]
        if board != 1004:
            raise ValueError(f'Bridge image manifest targets board {board}, expected 1004')


@dataclass(frozen=True)
class FirmwareImage:
    path: Path
    data: bytes

    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve()
        if path.stat().st_size > FLASH_CAPACITY * 2:
            raise ValueError('Firmware file is too large')
        encoded = path.read_bytes()
        if path.suffix.lower() == '.uf2':
            image = decode_uf2(encoded)
        elif path.suffix.lower() == '.bin':
            image = encoded
        else:
            raise ValueError('Choose a complete RP2040 .bin or .uf2 file')
        validate_binary(image)
        return cls(path, image)

    @property
    def crc32(self):
        return zlib.crc32(self.data)

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def capabilities(ser, debug=False):
    try:
        data = bitaxeraw.control_command(ser, 0xF0, PAGE_SWD, 0, debug=debug)
    except RuntimeError as exc:
        raise RuntimeError('ESP32 needs bitaxe-raw-bonanza 1004x firmware with SWD loader support (0.0.2 or newer)') from exc
    if len(data) != 10 or data[:2] != b'\x01\x01':
        raise RuntimeError('Unsupported ESP32 SWD loader protocol')
    chunk_size, capacity = struct.unpack_from('<HI', data, 2)
    if chunk_size != PAGE_SIZE or capacity != FLASH_CAPACITY or data[8:] != bytes([14, 15]):
        raise RuntimeError('ESP32 SWD loader does not match the 1004x wiring/flash layout')
    return {'chunk_size': chunk_size, 'capacity': capacity, 'swclk': data[8], 'swdio': data[9]}


def probe(ser, debug=False):
    capabilities(ser, debug)
    data = bitaxeraw.control_command(ser, 0xF1, PAGE_SWD, 1, debug=debug)
    if len(data) != 4 or int.from_bytes(data, 'little') != 0x0BC12477:
        raise RuntimeError(f'Unexpected RP2040 SWD DPIDR: {data.hex(" ")}')
    return int.from_bytes(data, 'little')


def _progress_reply(data, offset, crc):
    if len(data) != 9 or data[0] != 1:
        raise RuntimeError('Malformed SWD programming acknowledgement')
    actual_offset, actual_crc = struct.unpack_from('<II', data, 1)
    if (actual_offset, actual_crc) != (offset, crc):
        raise RuntimeError(f'SWD readback mismatch at offset {offset}: {actual_offset}, CRC {actual_crc:08X} != {crc:08X}')


def program(ser, image, progress=None, debug=False):
    """Program only after the caller has presented/confirmed this exact image.

    Acknowledgements include CRC-32 calculated from flash readback, not upload
    buffers. The target restarts only after every byte and the complete CRC pass.
    """
    validate_binary(image.data)
    capabilities(ser, debug)
    original_timeout = ser.timeout
    original_write_timeout = ser.write_timeout
    maintenance_started = False
    try:
        ser.timeout = max(original_timeout or 0, 15)
        ser.write_timeout = 15
        # Disable PMBus conversion as well as the enable pin (ON_OFF_CONFIG
        # can make that pin alone insufficient). Do not restore power afterward.
        TPS546D24.smb_write_byte(ser, PMBUS_OPERATION, 0)
        TPS546D24.enable_pin(ser, False, debug=debug)
        bitaxeraw.gpio_set(ser, 0xE0, bitaxeraw.GPIO_ASIC_RST, 0, debug)
        bitaxeraw.gpio_set(ser, 0xE1, bitaxeraw.GPIO_5V_EN, 0, debug)
        bitaxeraw.fan_set_speed(ser, 0xE2, 100, debug)
        if TPS546D24.smb_read_byte(ser, PMBUS_OPERATION) & 0x80:
            raise RuntimeError('TPS546 OPERATION is still enabled')
        deadline = time.monotonic() + 3
        while bitaxeraw.gpio_get(ser, 0xE3, bitaxeraw.GPIO_TPS546_PGOOD, debug):
            if time.monotonic() >= deadline:
                raise RuntimeError('TPS546 PGOOD is still high; wait for the rail to discharge')
            time.sleep(0.05)
        payload = struct.pack('<II', len(image.data), image.crc32) + image.data[:HEADER_SIZE]
        maintenance_started = True  # BEGIN might reach the ESP32 even if its reply is lost.
        data = bitaxeraw.control_command(ser, 0xF2, PAGE_SWD, 0x10, payload, debug)
        _progress_reply(data, 0, 0)
        crc = 0
        for offset in range(0, len(image.data), PAGE_SIZE):
            chunk = image.data[offset:offset + PAGE_SIZE]
            crc = zlib.crc32(chunk, crc)
            data = bitaxeraw.control_command(ser, 0xF3, PAGE_SWD, 0x20,
                                             struct.pack('<I', offset) + chunk, debug)
            _progress_reply(data, offset + len(chunk), crc)
            if progress:
                progress(offset + len(chunk), len(image.data))
        data = bitaxeraw.control_command(ser, 0xF4, PAGE_SWD, 0x30, debug=debug)
        _progress_reply(data, len(image.data), image.crc32)
        maintenance_started = False
    finally:
        if maintenance_started:
            # Drain a timed-out reply before ABORT; never resend a page/commit
            # after an uncertain outcome. Disconnect also cancels maintenance.
            try:
                ser.reset_input_buffer()
                bitaxeraw.control_command(ser, 0xF5, PAGE_SWD, 0x7F, debug=debug)
            except (OSError, RuntimeError):
                ser.close()
        ser.timeout = original_timeout
        ser.write_timeout = original_write_timeout
