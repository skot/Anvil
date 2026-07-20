import unittest

import Calibrator


class FakeSocket:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = []
        self.timeout = None
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _size):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class CalibratorTests(unittest.TestCase):
    def test_inclusive_range_includes_non_aligned_stop(self):
        self.assertEqual(Calibrator.inclusive_range(0.0, 2.5, 1.0), [0.0, 1.0, 2.0, 2.5])

    def test_both_sweep_includes_up_and_down_endpoints(self):
        self.assertEqual(
            Calibrator.build_sweep(0.0, 2.0, 1.0, "both"),
            [
                ("up", 0.0),
                ("up", 1.0),
                ("up", 2.0),
                ("down", 2.0),
                ("down", 1.0),
                ("down", 0.0),
            ],
        )

    def test_scpi_query_handles_fragmented_and_buffered_responses(self):
        fake_socket = FakeSocket([b"RIGOL TECHNO", b"LOGIES,DL3021A\n1.25\n"])
        load = Calibrator.RigolDL3021("example", sock=fake_socket).connect()

        self.assertEqual(load.identify(), "RIGOL TECHNOLOGIES,DL3021A")
        self.assertEqual(load.query_float(":MEASURE:CURRENT?"), 1.25)
        self.assertEqual(fake_socket.sent, [b"*IDN?\n", b":MEASURE:CURRENT?\n"])

    def test_configure_cc_starts_with_input_off_and_zero_current(self):
        fake_socket = FakeSocket()
        load = Calibrator.RigolDL3021("example", sock=fake_socket).connect()

        load.configure_cc()

        self.assertEqual(
            fake_socket.sent,
            [
                b":SOURCE:INPUT:STATE OFF\n",
                b":SOURCE:FUNCTION:MODE FIXED\n",
                b":SOURCE:FUNCTION CURRENT\n",
                b":SOURCE:TRANSIENT:STATE OFF\n",
                b":SOURCE:CURRENT:RANGE 40\n",
                b":SOURCE:CURRENT:VON MINIMUM\n",
                b":SOURCE:CURRENT:ILIM 40\n",
                b":SOURCE:CURRENT:LEVEL:IMMEDIATE 0\n",
            ],
        )

    def test_verify_cc_allows_waveform_front_panel_display(self):
        fake_socket = FakeSocket([b"WAV\n", b"CC\n", b"0\n", b"40\n", b'0,"No error"\n'])
        load = Calibrator.RigolDL3021("example", sock=fake_socket).connect()

        load.verify_cc_configuration()

    def test_validate_args_rejects_current_above_dl3021_limit(self):
        args = Calibrator.parse_args(["--stop-current", "40.1"])
        with self.assertRaisesRegex(ValueError, "40 A"):
            Calibrator.validate_args(args)

    def test_safety_check_rejects_excessive_vr_temperature(self):
        args = Calibrator.parse_args(["--max-vr-temp", "90"])
        measurement = {
            "vr_temp_c": 91.0,
            "load_current_a": 20.0,
            "tps_vout_v": 2.2,
            "load_power_w": 44.0,
        }
        with self.assertRaisesRegex(RuntimeError, "temperature"):
            Calibrator.check_safety(measurement, 20.0, args)


if __name__ == "__main__":
    unittest.main()
