import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zlib

import bridge_loader as loader


def image_bytes(size=600):
    data = bytearray(b'\xA5' * size)
    struct.pack_into('<I', data, 252, loader.boot2_crc(data[:252]))
    struct.pack_into('<II', data, 256, 0x20042000, 0x10000109)
    return bytes(data)


def uf2_block(data, address, number, total, family=loader.RP2040_FAMILY):
    block = bytearray(512)
    struct.pack_into('<8I', block, 0, 0x0A324655, 0x9E5D5157, 0x2000,
                     address, 256, number, total, family)
    block[32:288] = data
    struct.pack_into('<I', block, 508, 0x0AB16F30)
    return bytes(block)


class SimulatedESP32:
    """Exercise real framing and host upload code against a flash-service model."""
    def __init__(self, mismatch_page=None, capability=True):
        self.timeout, self.write_timeout = 3, None
        self.reply = bytearray()
        self.commands = []
        self.closed = False
        self.capability = capability
        self.mismatch_page = mismatch_page
        self.flash = bytearray()
        self.total = 0
        self.crc = 0
        self.active = False

    def write(self, packet):
        packet = bytes(packet)
        length, = struct.unpack_from('<H', packet)
        assert length == len(packet)
        command_id, bus, page, command = packet[2:6]
        assert bus == 0
        payload = packet[6:]
        self.commands.append((page, command, payload))
        response = b''
        if page == loader.PAGE_SWD:
            if not self.capability:
                response = b'\x11'
            elif command == 0:
                response = bytes([1, 1]) + struct.pack('<HI', 256, loader.FLASH_CAPACITY) + bytes([14, 15])
            elif command == 1:
                response = struct.pack('<I', 0x0BC12477)
            elif command == 0x10:
                self.total, self.crc = struct.unpack_from('<II', payload)
                self.active = True
                self.flash = bytearray()
                response = b'\x01' + struct.pack('<II', 0, 0)
            elif command == 0x20:
                offset, = struct.unpack_from('<I', payload)
                assert self.active and offset == len(self.flash)
                self.flash.extend(payload[4:])
                # Readback CRC model intentionally uses stored flash bytes.
                crc = zlib.crc32(self.flash)
                if self.mismatch_page == offset:
                    crc ^= 1
                response = b'\x01' + struct.pack('<II', len(self.flash), crc)
            elif command == 0x30:
                assert self.active and len(self.flash) == self.total and zlib.crc32(self.flash) == self.crc
                self.active = False
                response = b'\x01' + struct.pack('<II', self.total, self.crc)
            elif command == 0x7F:
                self.active = False
                response = b'\0'
            else:
                raise AssertionError(command)
        elif page == 5:
            if command == 0x20:
                response = bytes([len(payload) - 1])
            elif command == 0x40:
                assert payload == bytes([0x24, 1, 1])
                response = b'\0'
            else:
                raise AssertionError(command)
        elif page == 6:
            response = payload if payload else b'\0'
        elif page == 8:
            assert command == 0 and payload == b'\0'
            response = payload
        else:
            raise AssertionError(page)
        self.reply.extend(struct.pack('<HB', 3 + len(response), command_id) + response)
        return len(packet)

    def read(self, size):
        size = min(size, 2)  # Deliberately fragmented transport.
        data = bytes(self.reply[:size])
        del self.reply[:size]
        return data

    def reset_input_buffer(self):
        self.reply.clear()

    def close(self):
        self.closed = True


class BridgeImageTests(unittest.TestCase):
    def test_known_crc_vectors(self):
        self.assertEqual(loader.boot2_crc(b'123456789'), 0x0376E6E7)
        self.assertEqual(zlib.crc32(b'123456789'), 0xCBF43926)

    def test_boot2_corruption_and_invalid_vectors_rejected(self):
        valid = image_bytes()
        loader.validate_binary(valid)
        for offset, value in ((0, 0), (256, 1), (260, 0)):
            invalid = bytearray(valid)
            invalid[offset] = value
            with self.assertRaises(ValueError):
                loader.validate_binary(invalid)
        with self.assertRaises(ValueError):
            loader.validate_binary(valid[:263])

    def test_board_1002_manifest_rejected(self):
        image = bytearray(image_bytes())
        image[400:416] = b'BZM-BRIDGE-FW\0\0\0'
        struct.pack_into('<H', image, 418, 1002)
        with self.assertRaisesRegex(ValueError, 'targets board 1002'):
            loader.validate_binary(image)
        struct.pack_into('<H', image, 418, 1004)
        loader.validate_binary(image)

    def test_bin_file_load_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.bin'
            path.write_bytes(image_bytes())
            image = loader.FirmwareImage.load(path)
        self.assertEqual(image.data, image_bytes())
        self.assertEqual(image.crc32, zlib.crc32(image.data))
        self.assertEqual(len(image.sha256), 64)

    def test_uf2_out_of_order_blocks_and_gaps(self):
        data = image_bytes(768)
        encoded = uf2_block(data[512:768], loader.FLASH_BASE + 512, 2, 3)
        encoded += uf2_block(data[:256], loader.FLASH_BASE, 0, 3)
        encoded += uf2_block(data[256:512], loader.FLASH_BASE + 256, 1, 3)
        self.assertEqual(loader.decode_uf2(encoded), data)
        # A sparse UF2 fills the omitted flash page with FF.
        sparse = uf2_block(data[:256], loader.FLASH_BASE, 0, 2)
        sparse += uf2_block(data[512:768], loader.FLASH_BASE + 512, 1, 2)
        self.assertEqual(loader.decode_uf2(sparse)[256:512], b'\xff' * 256)

    def test_uf2_bad_family_duplicates_and_out_of_range_rejected(self):
        page = image_bytes()[:256]
        cases = [b'x', uf2_block(page, loader.FLASH_BASE, 0, 1, family=1),
                 uf2_block(page, 0x20000000, 0, 1),
                 uf2_block(page, loader.FLASH_BASE, 0, 2) * 2]
        for encoded in cases:
            with self.assertRaises(ValueError):
                loader.decode_uf2(encoded)


class BridgeProgrammingTests(unittest.TestCase):
    def test_probe_does_not_write_power_or_start_programming(self):
        serial = SimulatedESP32()
        self.assertEqual(loader.probe(serial), 0x0BC12477)
        self.assertEqual([(p, c) for p, c, _ in serial.commands], [(10, 0), (10, 1)])

    def test_old_esp32_rejected_before_any_power_change(self):
        serial = SimulatedESP32(capability=False)
        with self.assertRaisesRegex(RuntimeError, '0.0.2'):
            loader.program(serial, loader.FirmwareImage(Path('bridge.bin'), image_bytes()))
        self.assertEqual([(p, c) for p, c, _ in serial.commands], [(10, 0)])

    def test_stream_verify_and_commit_with_tail_and_timeout_restore(self):
        serial = SimulatedESP32()
        image = loader.FirmwareImage(Path('bridge.bin'), image_bytes())
        progress = []
        loader.program(serial, image, lambda done, total: progress.append((done, total)))
        self.assertEqual(serial.flash, image.data)
        self.assertEqual(progress, [(256, 600), (512, 600), (600, 600)])
        self.assertEqual(serial.timeout, 3)
        self.assertIsNone(serial.write_timeout)
        self.assertEqual(serial.commands[-1][:2], (10, 0x30))
        self.assertFalse(serial.active)
        self.assertFalse(any(p == 6 and payload == b'\1' for p, _, payload in serial.commands))

    def test_bad_flash_readback_aborts_without_commit(self):
        serial = SimulatedESP32(mismatch_page=256)
        with self.assertRaisesRegex(RuntimeError, 'readback mismatch'):
            loader.program(serial, loader.FirmwareImage(Path('bridge.bin'), image_bytes()))
        self.assertFalse(any(p == 10 and c == 0x30 for p, c, _ in serial.commands))
        self.assertEqual(serial.commands[-1][:2], (10, 0x7F))
        self.assertEqual(serial.timeout, 3)

    def test_interruption_aborts_and_keeps_target_uncommitted(self):
        serial = SimulatedESP32()
        def interrupt(*_):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            loader.program(serial, loader.FirmwareImage(Path('bridge.bin'), image_bytes()), interrupt)
        self.assertEqual(serial.commands[-1][:2], (10, 0x7F))
        self.assertFalse(any(p == 10 and c == 0x30 for p, c, _ in serial.commands))

    def test_invalid_image_sends_no_commands(self):
        serial = SimulatedESP32()
        with self.assertRaises(ValueError):
            loader.program(serial, loader.FirmwareImage(Path('bad.bin'), b'not an image'))
        self.assertEqual(serial.commands, [])


if __name__ == '__main__':
    unittest.main()
