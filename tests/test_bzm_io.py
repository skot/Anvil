"""Power sequencing and failure cleanup for VDD-off UART bench tests."""
from contextlib import ExitStack
import unittest
from unittest.mock import Mock, patch

import Anvil
import bitaxeraw as raw
import bzm2
from pmbusconst import PMBUS_OPERATION


class BZM2IoTests(unittest.TestCase):
    def setUp(self):
        self.app = Anvil.Anvil('ctrl', 'asic', 115200, 2000000, 3)
        self.app.ctrl = Mock(is_open=True)
        self.app.asic = Mock(is_open=True)
        self.app.board_info = Mock()
        self.app.bzm_chip_ids = [10]
        self.app.bzm_clocks_verified = self.app.bzm_sensors_configured = True
        self.state = {raw.GPIO_ASIC_RST: 1, raw.GPIO_5V_EN: 1,
                      raw.GPIO_TPS546_EN: 1, raw.GPIO_TPS546_PGOOD: 1,
                      raw.GPIO_ASIC_TRIP: 0, 'operation': 0x80}
        self.events = []
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.gpio = stack.enter_context(patch('bitaxeraw.gpio_set', side_effect=self.set_gpio))
        stack.enter_context(patch('bitaxeraw.gpio_get', side_effect=lambda ser, ident, pin, *a: self.state[pin]))
        stack.enter_context(patch('bitaxeraw.fan_set_speed'))
        self.taps = stack.enter_context(patch('bitaxeraw.read_domain_voltages', return_value=(0., 0., 0.)))
        self.rail = stack.enter_context(patch('TPS546D24.read_telemetry_sample', return_value={'vout': .04}))
        self.operation = stack.enter_context(patch('TPS546D24.smb_write_byte', side_effect=self.set_operation))
        stack.enter_context(patch('TPS546D24.smb_read_byte', side_effect=lambda *a: self.state['operation']))
        self.enable = stack.enter_context(patch('TPS546D24.enable_pin', side_effect=self.set_enable))
        self.noop = stack.enter_context(patch('bzm2.noop', side_effect=lambda ser, asic=0xFA, **kw: bytes([asic, 15])+b'2ZB'))
        self.enum = stack.enter_context(patch('bzm2.enumerate_chain', side_effect=lambda ser, ids, debug: list(ids)))
        self.read = stack.enter_context(patch('bzm2.read_u32', side_effect=lambda ser, address, *a: address | 0x100))
        stack.enter_context(patch('bzm2.time.sleep'))
        stack.enter_context(patch('builtins.print'))

    def set_gpio(self, ser, ident, pin, value, *a):
        if pin == raw.GPIO_5V_EN and value:
            self.assertEqual(self.state['operation'], 0)
            self.assertEqual(self.state[raw.GPIO_TPS546_EN], 0)
            self.assertEqual(self.state[raw.GPIO_ASIC_RST], 0)
        self.events.append((pin, value))
        self.state[pin] = value

    def set_operation(self, ser, command, value):
        self.assertEqual(command, PMBUS_OPERATION)
        self.state['operation'] = value

    def set_enable(self, ser, enabled, **kw):
        self.state[raw.GPIO_TPS546_EN] = int(enabled)
        self.state[raw.GPIO_TPS546_PGOOD] = int(enabled)

    def assert_off(self):
        self.assertEqual(self.state[raw.GPIO_ASIC_RST], 0)
        self.assertEqual(self.state[raw.GPIO_5V_EN], 0)
        self.assertEqual(self.state[raw.GPIO_TPS546_EN], 0)
        self.assertEqual(self.state['operation'], 0)
        self.assertEqual(self.app.bzm_chip_ids, [])
        self.assertFalse(self.app.bzm_clocks_verified or self.app.bzm_sensors_configured)

    def test_noop_runs_three_default_address_queries_without_core_power(self):
        result = self.app.bzm_io_test('noop', assume_yes=True)
        self.assertEqual(result['noop_responses'], ['fa 0f 32 5a 42'] * 3)
        self.assertEqual(self.noop.call_count, 3)
        self.enum.assert_not_called()
        self.read.assert_not_called()
        self.operation.assert_called_once_with(self.app.ctrl, PMBUS_OPERATION, 0)
        self.enable.assert_called_once_with(self.app.ctrl, False, debug=False)
        self.assertIn((raw.GPIO_5V_EN, 1), self.events)
        self.assert_off()

    def test_address_assignment_proves_ids_then_resets(self):
        result = self.app.bzm_io_test('assign', count=4, assume_yes=True)
        self.assertEqual(result['chip_ids'], [10, 20, 30, 40])
        self.assertEqual(result['id_registers'], {10: 266, 20: 276, 30: 286, 40: 296})
        self.noop.assert_not_called()  # Enumeration owns the default-address NOOPs.
        self.assertEqual([c.args[1] for c in self.read.call_args_list], [10, 20, 30, 40])
        self.assert_off()

    def test_live_core_rail_prevents_five_volt_enable_and_uart_commands(self):
        self.rail.return_value = {'vout': 2.8}
        with patch('Anvil.time.monotonic', side_effect=[0, 4]):
            with self.assertRaisesRegex(RuntimeError, 'did not turn off'):
                self.app.bzm_io_test('noop', assume_yes=True)
        self.assertNotIn((raw.GPIO_5V_EN, 1), self.events)
        self.noop.assert_not_called()
        self.assert_off()

    def test_live_or_invalid_domain_tap_cannot_pass_core_off_check(self):
        self.state.update({raw.GPIO_TPS546_EN: 0, raw.GPIO_TPS546_PGOOD: 0, 'operation': 0})
        for value in (.4, float('nan'), -.1):
            self.taps.return_value = (0., value, 0.)
            self.assertFalse(self.app.bzm_io_power_sample(self.app.ctrl)['core_off'])

    def test_low_voltage_alone_is_insufficient_if_core_controls_are_enabled(self):
        baseline = {raw.GPIO_TPS546_EN: 0, raw.GPIO_TPS546_PGOOD: 0, 'operation': 0}
        for signal, value in ((raw.GPIO_TPS546_EN, 1), (raw.GPIO_TPS546_PGOOD, 1), ('operation', 0x80)):
            self.state.update(baseline)
            self.state[signal] = value
            self.assertFalse(self.app.bzm_io_power_sample(self.app.ctrl)['core_off'])

    def test_timeout_malformed_response_or_interrupt_always_removes_five_volts(self):
        for error in (TimeoutError('no UART reply'), RuntimeError('bad signature'), KeyboardInterrupt()):
            self.noop.side_effect = error
            with self.assertRaises(type(error)):
                self.app.bzm_io_test('noop', assume_yes=True)
            self.assert_off()

    def test_rail_change_after_five_volt_enable_aborts_before_uart(self):
        self.rail.side_effect = [{'vout': .04}, {'vout': .9}]
        with self.assertRaisesRegex(RuntimeError, 'changed after enabling'):
            self.app.bzm_io_test('noop', assume_yes=True)
        self.noop.assert_not_called()
        self.assert_off()

    def test_wrong_assigned_register_fails_and_discards_managed_chain(self):
        self.read.return_value = 0xFA
        self.read.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'ID changed'):
            self.app.bzm_io_test('assign', count=4, assume_yes=True)
        self.assert_off()

    def test_missing_second_chip_cannot_publish_a_healthy_single_chip_chain(self):
        self.enum.side_effect = RuntimeError('No unassigned BZM2 for chip 2; found [10]')
        with self.assertRaisesRegex(RuntimeError, 'chip 2.*enable core VDD.*ASIC menu 1'):
            self.app.bzm_io_test('assign', count=4, assume_yes=True)
        self.assert_off()

    def test_cancel_preserves_existing_state_without_power_writes(self):
        with patch('Anvil.confirm', return_value=False):
            self.assertFalse(self.app.bzm_io_test('noop'))
        self.gpio.assert_not_called()
        self.operation.assert_not_called()
        self.enable.assert_not_called()
        self.assertEqual(self.app.bzm_chip_ids, [10])

    def test_cli_requires_a_selected_action_for_yes_and_valid_chip_count(self):
        with patch('Anvil.bitaxeraw.discover_ports', return_value=(None, None)), patch('sys.stderr'):
            args = Anvil.parse_args(['--bzm-io-test', 'assign', '--chips', '4', '--yes'])
            self.assertEqual(args.bzm_io_test, 'assign')
            self.assertTrue(args.yes)
            for arguments in (['--yes'], ['--bzm-io-test', 'assign', '--chips', '5'],
                              ['--probe', '--bzm-io-test', 'noop']):
                with self.assertRaises(SystemExit):
                    Anvil.parse_args(arguments)
