import unittest

import bitaxeraw
import bonanza_display


class FakeSerial:
    def __init__(self, response=b"\x04\x00\xAE\x00"):
        self.response = response
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def read(self, _size):
        return self.response


class FanDutyTests(unittest.TestCase):
    def test_fan_speed_percent_maps_to_active_low_raw_duty(self):
        self.assertEqual(bitaxeraw.fan_speed_percent_to_raw_duty(0), 255)
        self.assertEqual(bitaxeraw.fan_speed_percent_to_raw_duty(50), 127)
        self.assertEqual(bitaxeraw.fan_speed_percent_to_raw_duty(100), 0)


class BonanzaDisplayTests(unittest.TestCase):
    def test_hashrate_write_uses_disp_page_and_little_endian_u32(self):
        serial = FakeSerial()

        bonanza_display.write_field(serial, 0xAE, "hashrate_ghs", 1200)

        self.assertEqual(
            serial.writes,
            [bytes([0x0C, 0x00, 0xAE, 0x00, 0x09, 0x20, 0x3C, 0x60, 0xB0, 0x04, 0x00, 0x00])],
        )

    def test_string_write_is_nul_terminated(self):
        serial = FakeSerial()

        bonanza_display.write_field(serial, 0xAE, "best_share", "123T")

        self.assertEqual(
            serial.writes[0],
            bytes([0x0D, 0x00, 0xAE, 0x00, 0x09, 0x20, 0x3C, 0x48]) + b"123T\x00",
        )

    def test_string_rejects_values_that_do_not_leave_room_for_nul(self):
        with self.assertRaisesRegex(ValueError, "maximum is 7"):
            bonanza_display.encode_field("device_model", "12345678")

    def test_write_rejects_wrong_response_id(self):
        serial = FakeSerial(response=b"\x04\x00\xAF\x00")

        with self.assertRaisesRegex(RuntimeError, "ID mismatch"):
            bonanza_display.write_field(serial, 0xAE, "fan_percent", 66)


if __name__ == "__main__":
    unittest.main()
