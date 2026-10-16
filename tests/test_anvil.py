import unittest
from unittest.mock import patch

import Anvil
from tests.test_bitaxeraw import FakeSerial, frame


class AnvilBoardTests(unittest.TestCase):
    def make_app(self, response):
        app = Anvil.Anvil('ctrl', 'asic', 115200, 2000000, 3)
        app.ctrl = FakeSerial(response)
        app.ctrl.is_open = True
        return app

    def test_reject_old_rp2040_info_before_any_power_write(self):
        old = bytes([1, 1, 0, 5]) + b'1.2.3'
        app = self.make_app(frame(old, 0xD0))
        with self.assertRaisesRegex(RuntimeError, 'updated 1004x'):
            app.board_info()
        self.assertEqual(app.ctrl.writes, [bytes.fromhex('06 00 d0 00 00 01')])

    def test_accepts_1004x_esp32_identity(self):
        identity = b'bitaxe-raw-bonanza/1004x/0.0.1'
        data = bytes([1, 1, 0, len(identity)]) + identity
        app = self.make_app(frame(data, 0xD0))
        with patch('builtins.print'):
            self.assertEqual(app.board_info(), data)

    def test_disconnect_invalidates_managed_chip_state(self):
        app = self.make_app(b'')
        app.bzm_chip_ids = [10, 20, 30, 40]
        app.bzm_clocks_verified = True
        app.bzm_sensors_configured = True
        app.ctrl.close = lambda: None
        serial_module = unittest.mock.Mock()
        with patch('builtins.print'):
            app.connect_control(serial_module)
        self.assertEqual(app.bzm_chip_ids, [])
        self.assertFalse(app.bzm_clocks_verified or app.bzm_sensors_configured)

    def test_bridge_cancel_leaves_asic_state_and_port_untouched(self):
        import bridge_loader
        from pathlib import Path
        app = self.make_app(b'')
        app.bzm_chip_ids = [10]
        app.asic = unittest.mock.Mock(is_open=True)
        image = bridge_loader.FirmwareImage(Path('bridge.bin'), b'example')
        with patch.object(bridge_loader.FirmwareImage, 'load', return_value=image), \
             patch.object(bridge_loader, 'probe', return_value=0x0BC12477), \
             patch.object(bridge_loader, 'program') as program, \
             patch('Anvil.confirm', return_value=False), patch('builtins.print'):
            self.assertFalse(app.load_bridge_firmware('bridge.bin'))
        self.assertEqual(app.bzm_chip_ids, [10])
        app.asic.close.assert_not_called()
        program.assert_not_called()

    def test_bridge_cli_requires_explicit_image_for_yes(self):
        with patch('Anvil.bitaxeraw.discover_ports', return_value=(None, None)), \
             patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                Anvil.parse_args(['--yes'])
            args = Anvil.parse_args(['--flash-bridge', 'bridge.uf2', '--yes'])
            self.assertEqual(args.flash_bridge, 'bridge.uf2')
            self.assertTrue(args.yes)

    def manual_5v_app(self, response):
        identity = b'bitaxe-raw-bonanza/1004x/0.0.2'
        app = self.make_app(frame(bytes([1, 1, 0, len(identity)]) + identity, 0xD0) + response)
        app.bzm_chip_ids = [10, 20, 30, 40]
        app.bzm_clocks_verified = app.bzm_sensors_configured = True
        return app

    def test_manual_5v_on_asserts_reset_before_enable_and_verifies_readback(self):
        app = self.manual_5v_app(frame(b'\0', 0xA4) + frame(b'\1', 0xA5) + frame(b'\1', 0xA8))
        with patch('builtins.print'):
            self.assertEqual(app.bzm_set_5v(True), 1)
        self.assertEqual(app.ctrl.writes[1:], [bytes.fromhex('07 00 a4 00 06 02 00'),
                                               bytes.fromhex('07 00 a5 00 06 01 01'),
                                               bytes.fromhex('06 00 a8 00 06 01')])
        self.assertEqual(app.bzm_chip_ids, [])
        self.assertFalse(app.bzm_clocks_verified or app.bzm_sensors_configured)

    def test_manual_5v_off_asserts_reset_before_removing_power(self):
        app = self.manual_5v_app(frame(b'\0', 0xA4) + frame(b'\0', 0xA5) + frame(b'\0', 0xA8))
        with patch('builtins.print'):
            self.assertEqual(app.bzm_set_5v(False), 0)
        self.assertEqual(app.ctrl.writes[1:], [bytes.fromhex('07 00 a4 00 06 02 00'),
                                               bytes.fromhex('07 00 a5 00 06 01 00'),
                                               bytes.fromhex('06 00 a8 00 06 01')])

    def test_manual_5v_on_readback_failure_restores_reset_and_power_off(self):
        response = (frame(b'\0', 0xA4) + frame(b'\1', 0xA5) + frame(b'\0', 0xA8) +
                    frame(b'\0', 0xA4) + frame(b'\0', 0xA5))
        app = self.manual_5v_app(response)
        with patch('builtins.print'), self.assertRaisesRegex(RuntimeError, 'readback'):
            app.bzm_set_5v(True)
        self.assertEqual(app.ctrl.writes[-2:], [bytes.fromhex('07 00 a4 00 06 02 00'),
                                               bytes.fromhex('07 00 a5 00 06 01 00')])


if __name__ == '__main__':
    unittest.main()
