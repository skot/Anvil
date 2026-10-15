import hashlib
import struct
import unittest
from unittest.mock import patch

import bzm2
from tests.test_bitaxeraw import FakeSerial


class BZM2Tests(unittest.TestCase):
    def test_noop_matches_birds_wire_signature(self):
        serial = FakeSerial(bytes.fromhex('fa 0f 32 5a 42'), fragment=1)
        bzm2.noop(serial)
        self.assertEqual(serial.writes, [bytes.fromhex('fa 01 f0 00')])

    def test_noop_rejects_wrong_signature(self):
        with self.assertRaisesRegex(RuntimeError, 'Invalid BZM2'):
            bzm2.noop(FakeSerial(b'\xfa\x0fBZM'))

    def test_register_vectors_match_fork(self):
        serial = FakeSerial(bytes.fromhex('0a 03 0a 01 00 00'), fragment=1)
        self.assertEqual(bzm2.read_u32(serial, 0x0A, 0x0B), 0x10A)
        self.assertEqual(serial.writes[0], bytes.fromhex('0a 01 3f 00 ff 00 0b 00 03 00 00 00'))
        bzm2.write_u32(serial, 0xFA, 0x0B, 0x10A)
        self.assertEqual(serial.writes[1], bytes.fromhex('fa 01 2f 00 ff 00 0b 00 03 00 0a 00 01 00 00 00 00 00 00 00'))

    def test_read_register_rejects_wrong_chip_or_opcode(self):
        for response in (b'\x14\x03\0\0\0\0', b'\x0a\x01\0\0\0\0'):
            with self.assertRaisesRegex(RuntimeError, 'header'):
                bzm2.read_register(FakeSerial(response), 10, 11)

    def test_invalid_register_arguments_send_nothing(self):
        serial = FakeSerial()
        for args in ((256, 0, 1, 0), (10, 256, 1, 0), (10, 0, 0, 0), (10, 0, 257, 0), (10, 0, 4, 4096)):
            with self.assertRaises(ValueError):
                bzm2.read_register(serial, args[0], args[1], args[2], args[3])
        self.assertEqual(serial.writes, [])

    def test_enumeration_uses_default_noop_and_exact_assigned_id_proof(self):
        serial = FakeSerial()
        serial.reset_input_buffer = lambda: None
        with patch.object(bzm2, 'noop', side_effect=[b'2ZB'] * 4 + [TimeoutError()]) as noop, \
             patch.object(bzm2, 'write_u32') as write, \
             patch.object(bzm2, 'read_u32', side_effect=[0x10A, 0x114, 0x11E, 0x128]), \
             patch.object(bzm2.time, 'sleep'):
            self.assertEqual(bzm2.enumerate_chain(serial), [10, 20, 30, 40])
        self.assertEqual([c.args[3] for c in write.call_args_list], [0xA, 0x114, 0x11E, 0x128])
        self.assertTrue(all(c.kwargs == {'debug': False} for c in noop.call_args_list))

    def test_extra_chip_and_bad_readback_fail_enumeration(self):
        with patch.object(bzm2, 'noop'), patch.object(bzm2, 'write_u32'), \
             patch.object(bzm2, 'read_u32', return_value=0x10A), patch.object(bzm2.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Extra unassigned'):
                bzm2.enumerate_chain(FakeSerial(), [10])
        with patch.object(bzm2, 'noop'), patch.object(bzm2, 'write_u32'), \
             patch.object(bzm2, 'read_u32', return_value=0x0A), patch.object(bzm2.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'ID readback'):
                bzm2.enumerate_chain(FakeSerial(), [10])

    def test_loopback_reserved_tar_term_and_documented_dword_mask(self):
        serial = FakeSerial(bytes.fromhex('0a 0e 91 22 33 44'))
        bzm2.loopback(serial, 10)
        self.assertEqual(serial.writes[0], bytes.fromhex('0a 01 e0 00 00 00 03 00 00 00 11 00 22 00 33 00 44 00 00 00'))
        with self.assertRaises(ValueError):
            bzm2.loopback(FakeSerial(), 10, b'abc')

    def test_pll_reference_and_lock_status(self):
        self.assertEqual(bzm2.pll_config(800), {'feedback': 128, 'postdiv': 0x1242, 'actual_mhz': 800})
        for frequency in (float('nan'), 0, 3000):
            with self.assertRaises(ValueError):
                bzm2.pll_config(frequency)
        with patch.object(bzm2, 'read_u32', side_effect=[0x1242, 128, 5] * 2):
            states = bzm2.read_plls(None, 10)
        self.assertTrue(all(s['locked'] and s['frequency_mhz'] == 800 for s in states))

    def test_pll_failure_does_not_release_engine_reset(self):
        with patch.object(bzm2, 'write_u32') as write, patch.object(bzm2, 'write_verified') as verified, \
             patch.object(bzm2, 'read_plls', return_value=[{'locked': False}] * 2), patch.object(bzm2.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'PLL lock failed'):
                bzm2.set_frequency(None, [10], 800)
        self.assertFalse(any(c.args[2] == 0x16 for c in verified.call_args_list))
        self.assertEqual([c.args[2:4] for c in write.call_args_list], [(0x12, 0), (0x1C, 0), (0x12, 1), (0x1C, 1)])

    def test_sensor_decoding_preserves_faults_and_signed_ch2(self):
        with patch.object(bzm2, 'read_u32', side_effect=[2048 | 0x1000, 1, 10000 | (1 << 30), (2700 << 16) | 10000]):
            sample = bzm2.read_sensors(None, 10)
        self.assertAlmostEqual(sample['temperature_c'], 22.0228759765625)
        self.assertTrue(sample['thermal_fault'] and sample['thermal_trip'] and sample['voltage_fault'])
        self.assertLess(sample['ch2_v'], 0)

    def test_result_decode_and_genesis_double_sha_validation(self):
        nonce = bzm2.GENESIS_NONCE + 0x4C
        serial = FakeSerial(bytes.fromhex('0a 01 80 0a') + struct.pack('<I', nonce) + b'\x07\0')
        result = bzm2.read_result(serial, 10)
        self.assertEqual(serial.writes, [bytes.fromhex('0a 01 10 00')])
        self.assertEqual(result['engine'], 10)
        self.assertTrue(bzm2.validate_genesis_result(result, 7))
        self.assertFalse(bzm2.validate_genesis_result(result, 8))
        self.assertFalse(bzm2.validate_genesis_result(result, 7, nonce_offset=0x28))
        self.assertEqual(len(bzm2.GENESIS_HEADER), 80)
        self.assertEqual(hashlib.sha256(hashlib.sha256(bzm2.GENESIS_HEADER).digest()).digest()[::-1].hex(),
                         '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f')

    def test_genesis_work_wire_order_and_bounded_balanced_activation(self):
        with patch.object(bzm2, 'write_verified'), patch.object(bzm2, 'write_register') as write:
            bzm2.start_genesis_test(None, [10], 7)
        calls = [c.args for c in write.call_args_list]
        self.assertEqual([(c[2], c[3], c[4]) for c in calls[-2:]], [(0x39, b'\3', 10), (0x39, b'\3', 0)])
        for engine in (0, 10):
            values = {c[2]: c[3] for c in calls[:-2] if c[4] == engine}
            self.assertEqual(values[0x48], b'\0')  # looping disabled
            self.assertEqual(values[0x30], bytes.fromhex('4a5e1e4b'))
            self.assertEqual(values[0x34], bytes.fromhex('495fab29'))
            self.assertEqual(values[0x44], bytes.fromhex('1d00ffff'))
            self.assertLess(int.from_bytes(values[0x40], 'little') - int.from_bytes(values[0x3C], 'little'), 300)


if __name__ == '__main__':
    unittest.main()
