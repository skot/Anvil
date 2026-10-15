import unittest
from unittest.mock import patch

import bitaxeraw
import bonanza_display
import rawi2c


class FakeSerial:
    def __init__(self, response=b'', fragment=4096):
        self.response = bytearray(response)
        self.writes = []
        self.fragment = fragment

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, size):
        size = min(size, self.fragment)
        data = self.response[:size]
        del self.response[:size]
        return bytes(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        raise AssertionError('Transactions must not silently discard queued replies')


def frame(data, command_id=0xAE):
    return (len(data) + 3).to_bytes(2, 'little') + bytes([command_id]) + data


class BonanzaControlTests(unittest.TestCase):
    def test_fan_speed_uses_native_active_low_command(self):
        serial = FakeSerial(frame(b'\xd6'), fragment=1)
        bitaxeraw.fan_set_speed(serial, 0xAE, 16)
        self.assertEqual(serial.writes, [bytes.fromhex('07 00 ae 00 08 00 d6')])

    def test_raw_duty_preserves_all_eight_bits(self):
        for duty in (0, 127, 179, 255):
            serial = FakeSerial(frame(bytes([duty])) + (frame(bytes([1, 2, duty]), 0xAF) if duty == 255 else b''))
            bitaxeraw.fan_set_duty(serial, 0xAE, duty)
            self.assertEqual(serial.writes[0][-1], duty)
            self.assertEqual(serial.writes[0][4:6], bytes([8, 0]))

    def test_fan_fault_cannot_be_mistaken_for_raw_duty_ack(self):
        serial = FakeSerial(frame(b'\x13') + frame(bytes([1, 0x0E, 0]), 0xAF))
        with self.assertRaisesRegex(RuntimeError, 'not applied'):
            bitaxeraw.fan_set_duty(serial, 0xAE, 19)

    def test_rpm_is_u32_with_fragmented_response(self):
        serial = FakeSerial(frame((3060).to_bytes(4, 'little')), fragment=1)
        self.assertEqual(bitaxeraw.get_fan_rpm(serial, 0xAE), 3060)
        self.assertEqual(serial.writes[0], bytes.fromhex('06 00 ae 00 08 01'))

    def test_tps_enable_cannot_toggle_asic_reset(self):
        serial = FakeSerial(frame(b'\1'))
        bitaxeraw.gpio_set(serial, 0xAE, bitaxeraw.GPIO_TPS546_EN, 1)
        self.assertEqual(serial.writes[0], bytes.fromhex('07 00 ae 00 06 04 01'))

    def test_wrong_id_rejected_after_consuming_frame(self):
        serial = FakeSerial(frame(b'\0', 0xAF))
        with self.assertRaisesRegex(RuntimeError, 'ID mismatch'):
            bitaxeraw.fan_set_speed(serial, 0xAE, 50)
        self.assertEqual(serial.response, b'')

    def test_bridge_timeout_and_fault_are_errors(self):
        for status in (0x10, 0x11, 0x12, 0x13):
            with self.assertRaises(RuntimeError):
                bitaxeraw.control_command(FakeSerial(frame(bytes([status]))), 0xAE, 0, 1)

    def test_short_frame_and_invalid_length_rejected(self):
        with self.assertRaises(TimeoutError):
            bitaxeraw.get_fan_rpm(FakeSerial(bytes.fromhex('05 00 ae 12')), 0xAE)
        with self.assertRaisesRegex(RuntimeError, 'response length'):
            bitaxeraw.control_command(FakeSerial(bytes.fromhex('02 00 ae')), 0xAE, 0, 1)

    def test_fan_bad_rpm_length_is_not_an_rpm(self):
        with self.assertRaisesRegex(RuntimeError, 'requires 4'):
            bitaxeraw.get_fan_rpm(FakeSerial(frame(b'\0')), 0xAE)

    def test_raw_i2c_read_checks_length_and_write_ack(self):
        self.assertEqual(rawi2c.i2c_read_bytes(FakeSerial(frame(b'\x97')), 0xAE, 0x24, 0x20, 1), b'\x97')
        # A successful one-byte register read can equal a firmware error code.
        self.assertEqual(rawi2c.i2c_read_bytes(FakeSerial(frame(b'\x10')), 0xAE, 0x24, 0x20, 1), b'\x10')
        with self.assertRaisesRegex(RuntimeError, 'expected 2'):
            rawi2c.i2c_read_bytes(FakeSerial(frame(b'\x10')), 0xAE, 0x24, 0x20, 2)
        serial = FakeSerial(frame(b'\3'))
        rawi2c.i2c_send_bytes(serial, 0xAE, 0x24, 0x21, [0x99, 0x05])
        self.assertEqual(serial.writes[0], bytes.fromhex('0a 00 ae 00 05 20 24 21 99 05'))

    def test_domain_snapshot_is_calibrated_mv_in_d1_d2_d3_order(self):
        serial = FakeSerial(frame(bytes.fromhex('bc 02 78 05 34 08')), fragment=1)
        taps = bitaxeraw.read_domain_voltages(serial, 0xAE)
        self.assertEqual(taps, (0.7, 1.4, 2.1))
        self.assertEqual(serial.writes, [bytes.fromhex('06 00 ae 00 07 53')])
        for voltage in bitaxeraw.chip_voltages_from_taps(taps, 2.8):
            self.assertAlmostEqual(voltage, 0.7)

    def test_invalid_adc_length_and_negative_domain_differences(self):
        with self.assertRaisesRegex(RuntimeError, 'requires 6'):
            bitaxeraw.read_domain_voltages(FakeSerial(frame(b'\0\0')), 0xAE)
        self.assertLess(bitaxeraw.chip_voltages_from_taps((0.8, 0.7, 2.1), 2.8)[1], 0)

    def test_display_cannot_accidentally_send_fan_commands(self):
        serial = FakeSerial()
        with self.assertRaisesRegex(RuntimeError, 'no dedicated DISP'):
            bonanza_display.write_field(serial, 0xAE, 'hashrate_ghs', 1200)
        self.assertEqual(serial.writes, [])
        self.assertEqual(bonanza_display.encode_field('best_share', '123T'), b'123T\0')

    def test_asymmetric_asic_transport(self):
        serial = FakeSerial(b'\xfa\x0f2ZB', fragment=1)
        bitaxeraw.asic_write(serial, [0x1FA, 0xF0])
        self.assertEqual(serial.writes[0], bytes.fromhex('fa 01 f0 00'))
        self.assertEqual(bitaxeraw.asic_read(serial, 5), b'\xfa\x0f2ZB')


if __name__ == '__main__':
    unittest.main()
