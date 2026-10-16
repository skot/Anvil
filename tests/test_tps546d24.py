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
    @mock.patch("TPS546D24.smb_read_byte", return_value=0x97)
    @mock.patch("TPS546D24.smb_read_word")
    def test_read_telemetry_sample_reads_and_decodes_all_values(self, read_word, read_byte):
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


class BonanzaProfileTests(unittest.TestCase):
    def test_profile_emits_bonanza_register_values(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from tps546D24_values import TPS546_CONFIG_BONANZA
        import pmbusconst as p

        with mock.patch.object(TPS546D24, 'smb_read_byte', return_value=0x97), \
             mock.patch.object(TPS546D24, 'smb_write_byte') as byte, \
             mock.patch.object(TPS546D24, 'smb_write_word') as word, \
             mock.patch.object(TPS546D24, 'smb_write_block') as block, \
             redirect_stdout(StringIO()):
            TPS546D24.write_settings(None, TPS546_CONFIG_BONANZA)
        words = {c.args[1]: c.args[2] for c in word.call_args_list}
        self.assertEqual(words[p.PMBUS_FREQUENCY_SWITCH], 325)
        self.assertEqual(words[p.PMBUS_VOUT_COMMAND], 0x0599)
        self.assertEqual(words[p.PMBUS_VOUT_MIN], 0x0433)
        self.assertEqual(words[p.PMBUS_VOUT_MAX], 0x0666)
        self.assertEqual(words[p.PMBUS_IOUT_CAL_GAIN], 0xC880)
        self.assertEqual(words[p.PMBUS_IOUT_CAL_OFFSET], 0xE000)
        self.assertIn(mock.call(None, p.PMBUS_ON_OFF_CONFIG, 0x1B), byte.call_args_list)
        self.assertIn(mock.call(None, p.PMBUS_COMPENSATION_CONFIG, [0x13, 0x11, 0x8C, 0x1D, 0x08], 5), block.call_args_list)
        self.assertIn(mock.call(None, p.PMBUS_TELEMETRY_CONFIG, [3, 3, 3, 3, 3, 0], 6), block.call_args_list)

    def test_vout_uses_regulator_exponent(self):
        import TPS546helpers
        from contextlib import redirect_stdout
        from io import StringIO
        from pmbusconst import PMBUS_VOUT_COMMAND

        with mock.patch.object(TPS546helpers, 'VOUTMODE', 0x97), \
             mock.patch.object(TPS546D24, 'smb_read_byte', return_value=0x96), \
             mock.patch.object(TPS546D24, 'smb_write_word') as write, redirect_stdout(StringIO()):
            TPS546D24.set_vout_command(None, 2.8)
            write.assert_called_once_with(None, PMBUS_VOUT_COMMAND, 0x0B33, debug=False)

    def test_unknown_regulator_aborts_initialization(self):
        with mock.patch.object(TPS546D24, 'get_device_id', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Expected a TPS546'):
                TPS546D24.Init(None, {})


if __name__ == "__main__":
    unittest.main()
