"""RP2354A display programming over ESP32 GPIO14/GPIO16, control page 0x0C.

Supports complete, unpartitioned Pico SDK Arm Secure flash images with vectors
at offset zero and a simple IMAGE_DEF in the first 512 bytes. No OTP writes.
"""

from pathlib import Path
import struct

import bitaxeraw
import bridge_loader

PAGE_SWD = 0x0C
FLASH_BASE = 0x10000000
FLASH_CAPACITY = 2 * 1024 * 1024
PAGE_SIZE = 256
HEADER_SIZE = 512
RP2350_ARM_S_FAMILY = 0xE48BFF59
RP2350_ABSOLUTE_FAMILY = 0xE48BFF57
DPIDR = 0x4C013477


def decode_uf2(encoded):
    if not encoded or len(encoded) % 512:
        raise ValueError('UF2 must contain complete 512-byte blocks')
    pages, numbers, counts = {}, set(), set()
    ignored = 0
    for index in range(0, len(encoded), 512):
        block = encoded[index:index + 512]
        magic0, magic1, flags, address, length, number, total, family = struct.unpack_from('<8I', block)
        if (magic0, magic1, struct.unpack_from('<I', block, 508)[0]) != (0x0A324655, 0x9E5D5157, 0x0AB16F30):
            raise ValueError('Invalid UF2 block magic')
        # Pico SDK prepends this non-main-flash RP2350 E10 compatibility block.
        # It is explicitly ignored by family-aware downloaders, never programmed.
        if (flags, family, address, length, number, total) == (0xA000, RP2350_ABSOLUTE_FAMILY, 0x10FFFF00, 256, 0, 2):
            ignored += 1
            if ignored > 1:
                raise ValueError('Duplicate UF2 compatibility block')
            continue
        if flags != 0x2000 or family != RP2350_ARM_S_FAMILY:
            raise ValueError('Display UF2 must target RP2350 Arm Secure main flash')
        if length != PAGE_SIZE or address % PAGE_SIZE:
            raise ValueError('UF2 must use aligned 256-byte flash payloads')
        if not FLASH_BASE <= address <= FLASH_BASE + FLASH_CAPACITY - PAGE_SIZE:
            raise ValueError('UF2 exceeds the RP2354A 2 MiB flash')
        if not total or number >= total or number in numbers or address in pages:
            raise ValueError('UF2 has duplicate, overlapping or invalid blocks')
        counts.add(total)
        numbers.add(number)
        pages[address] = block[32:288]
    if not pages or counts != {len(pages)} or numbers != set(range(len(pages))):
        raise ValueError('UF2 has missing or inconsistent main-flash blocks')
    if min(pages) != FLASH_BASE:
        raise ValueError('Display UF2 must start at flash offset zero')
    image = bytearray(b'\xff' * (max(pages) + PAGE_SIZE - FLASH_BASE))
    for address, data in pages.items():
        image[address - FLASH_BASE:address - FLASH_BASE + PAGE_SIZE] = data
    return bytes(image)


def validate_binary(image):
    if not HEADER_SIZE <= len(image) <= FLASH_CAPACITY:
        raise ValueError('Display image must be 512 bytes..2 MiB, starting at flash offset zero')
    stack, reset = struct.unpack_from('<II', image)
    if stack % 8 or not 0x20000000 < stack <= 0x20082000:
        raise ValueError('Invalid RP2354A stack pointer at flash offset zero')
    if not reset & 1 or not FLASH_BASE <= (reset & ~1) < FLASH_BASE + len(image):
        raise ValueError('RP2354A reset vector is outside this image')
    # Accept the SDK's simple IMAGE_DEF, not signed/partitioned/load-map images.
    # LAST encodes one item word; the next-block link must stay within the image.
    for offset in range(0, HEADER_SIZE - 19, 4):
        start, kind, last, link, end = struct.unpack_from('<5I', image, offset)
        if (start, kind, last, end) == (0xFFFFDED3, 0x10210142, 0x1FF, 0xAB123579):
            destination = offset + struct.unpack('<i', struct.pack('<I', link))[0]
            if link == 0 or 0 <= destination <= len(image) - 20:
                return
    raise ValueError('Expected a simple RP2350 Arm Secure IMAGE_DEF in the first 512 bytes')


class FirmwareImage(bridge_loader.FirmwareImage):
    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve()
        if path.stat().st_size > FLASH_CAPACITY * 2 + 512:
            raise ValueError('Display firmware file is too large')
        encoded = path.read_bytes()
        if path.suffix.lower() == '.uf2':
            image = decode_uf2(encoded)
        elif path.suffix.lower() == '.bin':
            image = encoded
        else:
            raise ValueError('Choose a complete RP2354A display .bin or .uf2')
        validate_binary(image)
        return cls(path, image)


def capabilities(ser, debug=False):
    try:
        data = bitaxeraw.control_command(ser, 0xF0, PAGE_SWD, 0, debug=debug)
    except RuntimeError as exc:
        raise RuntimeError('ESP32 needs bitaxe-raw-bonanza/1004x/0.0.5 or newer with display SWD support') from exc
    expected = b'\x01\x01' + struct.pack('<HI', PAGE_SIZE, FLASH_CAPACITY) + bytes([14, 16])
    if data != expected:
        raise RuntimeError('Unsupported display SWD capabilities/wiring/flash layout')
    return {'chunk_size': PAGE_SIZE, 'capacity': FLASH_CAPACITY, 'swclk': 14, 'swdio': 16}


def probe(ser, debug=False):
    capabilities(ser, debug)
    data = bitaxeraw.control_command(ser, 0xF1, PAGE_SWD, 1, debug=debug)
    if data != struct.pack('<I', DPIDR):
        raise RuntimeError(f'Unexpected RP2354A SWD DPIDR: {data.hex(" ")}')
    return DPIDR


def program(ser, image, progress=None, debug=False):
    validate_binary(image.data)
    capabilities(ser, debug)
    bridge_loader._program(ser, image, PAGE_SWD, HEADER_SIZE, progress, debug)
