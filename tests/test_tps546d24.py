import unittest
from unittest import mock

import TPS546D24
from pmbusconst import (
    PMBUS_READ_IOUT,
    PMBUS_READ_TEMPERATURE_1,
    PMBUS_READ_VIN,
    PMBUS_READ_VOUT,
)


class TPS546TelemetryTests(unittest.TestCase):
    @mock.patch("TPS546D24.smb_read_word")
    def test_read_telemetry_sample_reads_and_decodes_all_values(self, read_word):
        raw_by_command = {
            PMBUS_READ_VIN: 0xD300,             # 12.0, Linear11
            PMBUS_READ_VOUT: 0x0480,            # 2.25, ULinear16 (2^-9)
            PMBUS_READ_IOUT: 0xCA00,            # 4.0, Linear11
            PMBUS_READ_TEMPERATURE_1: 0xE320,   # 50.0, Linear11
        }
        read_word.side_effect = lambda _ser, command, debug=False: raw_by_command[command]

        sample = TPS546D24.read_telemetry_sample(object(), debug=True)

        self.assertEqual(
            [call.args[1] for call in read_word.call_args_list],
            [PMBUS_READ_VIN, PMBUS_READ_VOUT, PMBUS_READ_IOUT, PMBUS_READ_TEMPERATURE_1],
        )
        self.assertAlmostEqual(sample["vin"], 12.0)
        self.assertAlmostEqual(sample["vout"], 2.25)
        self.assertAlmostEqual(sample["iout"], 4.0)
        self.assertAlmostEqual(sample["vr_temp"], 50.0)

    def test_average_telemetry(self):
        samples = [
            {"vin": 12.0, "vout": 2.0, "iout": 1.5, "vr_temp": 40.0},
            {"vin": 12.2, "vout": 2.2, "iout": 2.5, "vr_temp": 42.0},
        ]

        averages = TPS546D24.average_telemetry(samples)

        self.assertEqual(
            averages,
            {"vin": 12.1, "vout": 2.1, "iout": 2.0, "vr_temp": 41.0},
        )

    def test_average_telemetry_rejects_empty_samples(self):
        with self.assertRaises(ValueError):
            TPS546D24.average_telemetry([])


if __name__ == "__main__":
    unittest.main()
