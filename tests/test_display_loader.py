import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import Anvil
import display_loader as loader
from tests.test_bridge_loader import SimulatedESP32, uf2_block


def image_bytes(size=777):
    data = bytearray(b'\xa5' * size)
    struct.pack_into('<II', data, 0, 0x20082000, 0x10000151)
    struct.pack_into('<5I', data, 0x138, 0xFFFFDED3, 0x10210142, 0x1FF, 0, 0xAB123579)
    return bytes(data)


class DisplayESP32(SimulatedESP32):
    def write(self, packet):
        # Reuse the upload model while checking the actual display wire page.
        packet = bytearray(packet)
        if packet[4] != loader.PAGE_SWD:
            return super().write(packet)
        command = packet[5]
        packet[4] = 0x0A
        result = super().write(packet)
        self.commands[-1] = (loader.PAGE_SWD, command, bytes(packet[6:]))
        if command == 0 and self.capability:
            self.reply[-1] = 16
        elif command == 1:
            self.reply[-4:] = struct.pack('<I', loader.DPIDR)
        return result


class DisplayImageTests(unittest.TestCase):
    def test_real_sdk_layout_and_cross_family_rejection(self):
        valid = image_bytes()
        loader.validate_binary(valid)
        for offset, value in ((0, 1), (4, 0), (0x13E, 0x22), (0x148, 0)):
            invalid = bytearray(valid)
            invalid[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                loader.validate_binary(invalid)
        with self.assertRaises(ValueError):
            loader.validate_binary(valid[:511])

    def test_sdk_uf2_ignored_e10_block_never_becomes_flash_data(self):
        data = image_bytes(768)
        pages = [uf2_block(data[i:i+256], loader.FLASH_BASE+i, i//256, 3,
                           loader.RP2350_ARM_S_FAMILY) for i in range(0, 768, 256)]
        dummy = bytearray(uf2_block(b'\xff'*256, 0x10FFFF00, 0, 2, loader.RP2350_ABSOLUTE_FAMILY))
        struct.pack_into('<I', dummy, 8, 0xA000)
        self.assertEqual(loader.decode_uf2(bytes(dummy) + b''.join(reversed(pages))), data)
        for bad in (b''.join(pages[:-1]), pages[0]+pages[0]+pages[2],
                    bytes(dummy)*2+b''.join(pages),
                    uf2_block(data[:256], loader.FLASH_BASE, 0, 1)):
            with self.assertRaises(ValueError):
                loader.decode_uf2(bad)

    def test_complete_flash_file_validated_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'display.bin'
            path.write_bytes(image_bytes())
            self.assertEqual(loader.FirmwareImage.load(path).data, image_bytes())
            path.write_bytes(b'\0'*512)
            with self.assertRaises(ValueError):
                loader.FirmwareImage.load(path)


class DisplayUploadTests(unittest.TestCase):
    def test_probe_upload_and_verified_commit_use_display_page(self):
        serial = DisplayESP32()
        self.assertEqual(loader.probe(serial), loader.DPIDR)
        image = loader.FirmwareImage(Path('display.bin'), image_bytes())
        loader.program(serial, image)
        self.assertEqual(serial.flash, image.data)
        swd = [entry for entry in serial.commands if entry[0] == loader.PAGE_SWD]
        self.assertEqual(len(next(p for _, c, p in swd if c == 0x10)), 8 + 512)
        self.assertEqual(swd[-1][1], 0x30)
        self.assertFalse(any(page == 0x0A for page, _, _ in serial.commands))
        self.assertEqual((serial.timeout, serial.write_timeout), (3, None))

    def test_readback_failure_aborts_display_without_commit(self):
        serial = DisplayESP32(mismatch_page=256)
        with self.assertRaisesRegex(RuntimeError, 'readback mismatch'):
            loader.program(serial, loader.FirmwareImage(Path('display.bin'), image_bytes()))
        commands = [(p, c) for p, c, _ in serial.commands]
        self.assertEqual(commands[-1], (loader.PAGE_SWD, 0x7F))
        self.assertNotIn((loader.PAGE_SWD, 0x30), commands)

    def test_old_firmware_fails_before_power_or_begin(self):
        serial = DisplayESP32(capability=False)
        with self.assertRaisesRegex(RuntimeError, '0.0.5'):
            loader.program(serial, loader.FirmwareImage(Path('display.bin'), image_bytes()))
        self.assertEqual([(p, c) for p, c, _ in serial.commands], [(loader.PAGE_SWD, 0)])

    def test_cli_and_cancel_leave_asic_state_untouched(self):
        with patch('bitaxeraw.discover_ports', return_value=(None, None)):
            args = Anvil.parse_args(['--flash-display', 'display.uf2', '--yes'])
            self.assertEqual(args.flash_display, 'display.uf2')
        app = Anvil.Anvil('ctrl', 'asic', 115200, 2000000, 3)
        app.ctrl = unittest.mock.Mock(is_open=True)
        app.asic = unittest.mock.Mock(is_open=True)
        app.bzm_chip_ids = [10]
        image = loader.FirmwareImage(Path('display.bin'), image_bytes())
        with patch.object(loader.FirmwareImage, 'load', return_value=image), \
             patch.object(loader, 'probe', return_value=loader.DPIDR), \
             patch.object(loader, 'program') as program, \
             patch('Anvil.confirm', return_value=False), patch('builtins.print'):
            self.assertFalse(app.load_display_firmware('display.bin'))
        self.assertEqual(app.bzm_chip_ids, [10])
        app.asic.close.assert_not_called()
        program.assert_not_called()
