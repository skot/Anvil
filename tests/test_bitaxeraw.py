import unittest

import bitaxeraw


class FanDutyTests(unittest.TestCase):
    def test_fan_speed_percent_maps_to_active_low_raw_duty(self):
        self.assertEqual(bitaxeraw.fan_speed_percent_to_raw_duty(0), 255)
        self.assertEqual(bitaxeraw.fan_speed_percent_to_raw_duty(50), 127)
        self.assertEqual(bitaxeraw.fan_speed_percent_to_raw_duty(100), 0)


if __name__ == "__main__":
    unittest.main()
