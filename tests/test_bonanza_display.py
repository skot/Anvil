import unittest
from unittest.mock import patch

import Anvil
import bonanza_display as display
from tests.test_bitaxeraw import FakeSerial, frame


def reply(payload):
    return frame(payload, 0xB0)


def capabilities():
    return bytes([1, 1]) + (115200).to_bytes(4, 'little') + bytes([39, 40, 0, 1])


class FakeUART:
    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.writes = []

    def read(self):
        return self.chunks.pop(0) if self.chunks else (b'', False)

    def write(self, data):
        self.writes.append(data)


def messages(frames):
    return display.BAPParser().feed(b''.join(frames))


class BAPProtocolTests(unittest.TestCase):
    def test_spec_checksum_examples(self):
        self.assertEqual(display.bap_frame('REQ', 'systemInfo'), b'$BAP,REQ,systemInfo*3E\r\n')
        self.assertEqual(display.bap_frame('SUB', 'temperature', '1000'), b'$BAP,SUB,temperature,1000*56\r\n')
        self.assertEqual(display.encode_field('temperature_c', '58.250000'), b'$BAP,RES,chipTemp,58.250000*21\r\n')
        self.assertEqual(display.encode_field('fan_rpm', 4200), b'$BAP,RES,fan_speed,4200*6C\r\n')

    def test_fields_match_client_names_and_units(self):
        fields = {name: spec['default'] for name, spec in display.FIELD_SPECS.items()}
        actual = {parameter: value for _, parameter, value in messages(
            [display.encode_field(name, value) for name, value in fields.items()])}
        self.assertEqual(actual, dict(deviceModel='BONANZA', asicModel='BZM2',
                                     wifi_ip='192.168.1.234', best_difficulty='123T',
                                     hashrate='1200.55', chipTemp='58.25', power='17.60',
                                     frequency='800', fan_speed='4200'))
        for removed in ('device_name', 'fan_percent'):
            with self.assertRaises(ValueError):
                display.encode_field(removed, 66)

    def test_invalid_values_are_rejected_before_transmission(self):
        cases = [('power_w', value) for value in
                 (-1, True, 'nan', 'inf', '1e100', '1e-9999', '1e-310', '4294967294.5',
                  '4294967294.499999999999', '42junk', '', ' 42', '+42', '2,3')]
        cases += [('device_family', value) for value in ('', 'x' * 32, 'café', 'x\x00', 'x\r', 'x\n', '$BAP', 'x*00')]
        for name, value in cases:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                display.encode_field(name, value)
        self.assertIn(b',4294967294*', display.encode_field('power_w', '4294967294'))
        self.assertIn(b',0.5*', display.encode_field('power_w', '0.5'))
        self.assertIn(b'family,with,commas', display.encode_field('device_family', 'family,with,commas'))

    def test_frame_size_and_delimiters(self):
        for command, parameter, value in [('R,ES', 'x', 'x'), ('RES', 'x y', 'x'),
                                           ('RES', 'x', 'x' * 256), ('RES', 'x', 'x\n')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                display.bap_frame(command, parameter, value)

    def test_fragmented_and_coalesced_sentences_lf_and_lowercase_checksum(self):
        parser = display.BAPParser()
        packet = b'noise$incomplete' + display.bap_frame('REQ', 'systemInfo')
        result = []
        for byte in packet:
            result.extend(parser.feed(bytes([byte])))
        self.assertEqual(result, [('REQ', 'systemInfo', None)])
        packet = b'$BAP,REQ,systemInfo*3e\n' + display.bap_frame('SUB', 'temperature', '1000')
        self.assertEqual(parser.feed(packet), [('REQ', 'systemInfo', None), ('SUB', 'temperature', '1000')])

    def test_bad_checksum_oversized_input_and_control_chars_recover(self):
        bad = [b'$BAP,REQ,systemInfo*00\n', b'$BAP,REQ,systemInfo*ZZ\n',
               b'$BAP,REQ,systemInfo*3Ex\n', b'$' + b'x' * 600 + b'\n',
               b'$BAP,REQ,sys\x00temInfo*3E\n', b'$BAP,REQ,sys\rtemInfo*3E\n']
        parser = display.BAPParser()
        for data in bad:
            self.assertEqual(parser.feed(data), [])
            self.assertEqual(parser.feed(display.bap_frame('REQ', 'systemInfo')), [('REQ', 'systemInfo', None)])
        parser.feed(b'$BAP,REQ,')
        parser.reset()
        self.assertEqual(parser.feed(b'systemInfo*3E\r\n'), [])


class DisplayTransportTests(unittest.TestCase):
    def test_capabilities_and_uart_tx_rx_use_only_page_0b(self):
        packet = display.encode_field('fan_rpm', 4200)
        request = display.bap_frame('REQ', 'systemInfo')
        serial = FakeSerial(reply(capabilities()) + reply(b'\x01' + len(packet).to_bytes(2, 'little'))
                            + reply(b'\x01\x01' + request), fragment=1)
        transport = display.ControlUART(serial)
        transport.write(packet)
        self.assertEqual(transport.read(), (request, True))
        self.assertEqual(serial.writes[0], bytes.fromhex('06 00 b0 00 0b 00'))
        self.assertEqual(serial.writes[1][4:], b'\x0b\x20' + packet)
        self.assertEqual(serial.writes[2], bytes.fromhex('06 00 b0 00 0b 30'))
        self.assertTrue(all(p[4] == 0x0B for p in serial.writes))

    def test_old_firmware_reports_required_update(self):
        serial = FakeSerial(reply(b'\x11'))
        with self.assertRaisesRegex(RuntimeError, '0.0.4'):
            display.ControlUART(serial)
        self.assertEqual(len(serial.writes), 1)

    def test_incompatible_capabilities_never_transmit(self):
        for cap in (b'', capabilities()[:8], capabilities().replace(b'\x27\x28', b'\x11\x12')):
            serial = FakeSerial(reply(cap))
            with self.subTest(cap=cap), self.assertRaisesRegex(RuntimeError, 'capabilities'):
                display.ControlUART(serial)
            self.assertEqual(len(serial.writes), 1)

    def test_bad_tx_ack_and_rx_header_are_rejected(self):
        for response in (b'', b'\x01\x00\x00', b'\xffDisplay UART TX timeout'):
            transport = display.ControlUART(FakeSerial(reply(capabilities()) + reply(response)))
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                transport.write(b'$test')
        for response in (b'', b'\x01', b'\x02\x00', b'\x01\x02'):
            transport = display.ControlUART(FakeSerial(reply(capabilities()) + reply(response)))
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                transport.read()

    def test_probe_requires_accessory_request_not_transport_ack(self):
        uart = FakeUART([(display.bap_frame('ACK', 'temperature', 'subscribed'), False),
                         (display.bap_frame('REQ', 'systemInfo'), False)])
        with patch('bonanza_display.time.sleep'):
            self.assertEqual(display.probe(uart), ('REQ', 'systemInfo', None))
        self.assertEqual(uart.writes, [])
        with patch('bonanza_display.time.monotonic', side_effect=[0, 16]), self.assertRaises(TimeoutError):
            display.probe(FakeUART())


class BAPHostTests(unittest.TestCase):
    def test_request_and_subscriptions_reply_with_correct_parameters(self):
        requests = (display.bap_frame('REQ', 'systemInfo') + display.bap_frame('SUB', 'temperature', 1000)
                    + display.bap_frame('SUB', 'fan_speed', 1000) + display.bap_frame('SUB', 'wifi', 1000))
        uart = FakeUART([(requests, False)])
        host = display.BAPHost(uart, {'temperature_c': '58.25', 'fan_rpm': 4200, 'ip_address': '192.168.1.2'})
        host.poll(now=0)
        self.assertEqual(messages(uart.writes), [
            ('RES', 'deviceModel', 'BONANZA'), ('RES', 'asicModel', 'BZM2'),
            ('ACK', 'temperature', 'subscribed'), ('RES', 'chipTemp', '58.25'),
            ('ACK', 'fan_speed', 'subscribed'), ('RES', 'fan_speed', '4200'),
            ('ACK', 'wifi', 'subscribed'), ('RES', 'wifi_ip', '192.168.1.2')])
        self.assertNotIn(b'wifi_password', b''.join(uart.writes))
        self.assertEqual(host.requests, 4)
        uart.writes.clear()
        host.poll(now=0.99)
        self.assertEqual(uart.writes, [])
        host.poll(now=1)
        self.assertEqual(messages(uart.writes), [('RES', 'chipTemp', '58.25'), ('RES', 'fan_speed', '4200'),
                                                ('RES', 'wifi_ip', '192.168.1.2')])

    def test_unconfigured_telemetry_is_not_invented(self):
        uart = FakeUART([(display.bap_frame('SUB', 'hashrate', 1000), False)])
        host = display.BAPHost(uart)
        host.poll(now=0)
        self.assertEqual(messages(uart.writes), [('ACK', 'hashrate', 'subscribed')])

    def test_subscription_renewal_expiration_and_no_power_commands(self):
        packet = display.bap_frame('SUB', 'power', 1000)
        uart = FakeUART([(packet, False)])
        host = display.BAPHost(uart, {'power_w': '17.60'})
        host.poll(now=0)
        uart.chunks.append((packet, False))
        host.poll(now=299)
        uart.writes.clear()
        host.poll(now=301)
        self.assertEqual(messages(uart.writes), [('RES', 'power', '17.60')])
        uart.writes.clear()
        host.poll(now=599)
        self.assertEqual(messages(uart.writes), [('STA', 'power', 'subscription_timeout')])
        self.assertEqual(host.subscriptions, {})

    def test_bad_requests_and_set_commands_cannot_control_board(self):
        uart = FakeUART([(b''.join([display.bap_frame('SUB', 'temperature', '0'),
                                    display.bap_frame('SUB', 'temperature', '1000junk'),
                                    display.bap_frame('REQ', 'unknown'),
                                    display.bap_frame('SET', 'fan_speed', '0')]), False)])
        host = display.BAPHost(uart)
        host.poll(now=0)
        self.assertEqual(messages(uart.writes), [('ERR', 'temperature', 'invalid_request'),
                                                ('ERR', 'temperature', 'invalid_request'),
                                                ('ERR', 'unknown', 'unknown_parameter')])
        self.assertEqual(host.subscriptions, {})

    def test_rx_overflow_drops_partial_frame_and_recovers(self):
        uart = FakeUART([(b'$BAP,REQ,', False), (b'systemInfo*3E\r\n', True),
                         (display.bap_frame('REQ', 'systemInfo'), False)])
        host = display.BAPHost(uart)
        host.poll(now=0)
        host.poll(now=1)
        self.assertEqual(uart.writes, [])
        host.poll(now=2)
        self.assertEqual(host.requests, 1)
        self.assertEqual(len(uart.writes), 2)

    def test_unknown_or_invalid_parameter_cannot_break_host_framing(self):
        uart = FakeUART([(display.bap_frame('REQ', 'x' * 220) +
                          b'$BAP,REQ,unknown group*00\r\n' +
                          display.bap_frame('REQ', 'systemInfo'), False)])
        host = display.BAPHost(uart)
        host.poll(now=0)
        self.assertEqual(messages(uart.writes), [('RES', 'deviceModel', 'BONANZA'), ('RES', 'asicModel', 'BZM2')])

    def test_serving_can_stop_on_duration_or_ctrl_c(self):
        uart = FakeUART()
        with patch('bonanza_display.time.monotonic', side_effect=[0, 2]):
            host = display.serve(uart, {}, seconds=1)
        self.assertEqual(host.sent, 2)
        with patch('bonanza_display.BAPHost.poll', side_effect=KeyboardInterrupt):
            self.assertEqual(display.serve(uart, {}).sent, 2)


class DisplayConsoleTests(unittest.TestCase):
    def test_cli_repeated_values_and_mode_constraints(self):
        with patch('Anvil.bitaxeraw.discover_ports', return_value=(None, None)):
            args = Anvil.parse_args(['--display-serve', '--display-set', 'device_model', 'BZM2',
                                     '--display-set', 'fan_rpm', '4200', '--display-seconds', '10'])
            self.assertEqual(args.display_set, [['device_model', 'BZM2'], ['fan_rpm', '4200']])
            self.assertEqual(args.display_seconds, 10)
            for flags in (['--display-serve', '--probe'], ['--display-demo', '--flash-bridge', 'x.bin'],
                          ['--display-set', 'fan_rpm', '50', '--probe'], ['--display-seconds', 'nan'],
                          ['--display-seconds', '-1'], ['--display-read']):
                with self.subTest(flags=flags), patch('sys.stderr'), self.assertRaises(SystemExit):
                    Anvil.parse_args(flags)

    def test_cli_probe_uses_only_control_port(self):
        with patch('Anvil.bitaxeraw.discover_ports', return_value=(None, None)), \
             patch.object(Anvil.Anvil, 'display_transport', return_value=FakeUART()) as transport, \
             patch.object(Anvil.Anvil, 'connect_asic') as asic, \
             patch('Anvil.bonanza_display.probe', return_value=('REQ', 'systemInfo', None)), \
             patch('builtins.print'):
            self.assertEqual(Anvil.main(['--display-probe']), 0)
            transport.assert_called_once()
            asic.assert_not_called()

    def test_invalid_field_never_connects_or_sends(self):
        with patch('Anvil.bitaxeraw.discover_ports', return_value=(None, None)), \
             patch.object(Anvil.Anvil, 'require_control') as control, patch('builtins.print'):
            self.assertEqual(Anvil.main(['--display-set', 'fan_percent', '66']), 1)
            self.assertEqual(Anvil.main(['--display-set', 'power_w', '17', '--display-set', 'fan_rpm', '-1']), 1)
            control.assert_not_called()

    def test_one_shot_sends_bap_and_caches_values_without_readback(self):
        app = Anvil.Anvil('ctrl', 'asic', 115200, 2000000, 3)
        uart = FakeUART()
        with patch.object(app, 'display_transport', return_value=uart), patch('builtins.print'):
            self.assertTrue(app.display_write({'fan_rpm': 4200}))
        self.assertEqual(messages(uart.writes), [('RES', 'fan_speed', '4200')])
        self.assertEqual(app.display_values['fan_rpm'], 4200)

    def test_demo_uses_correct_units_and_can_be_bounded(self):
        with patch('Anvil.bitaxeraw.discover_ports', return_value=(None, None)), \
             patch.object(Anvil.Anvil, 'display_serve', return_value=True) as serve, patch('builtins.print'):
            self.assertEqual(Anvil.main(['--display-demo', '--display-seconds', '10',
                                        '--display-set', 'fan_rpm', '5000']), 0)
        values, seconds = serve.call_args.args
        self.assertEqual(seconds, 10)
        self.assertEqual(values['device_model'], 'BZM2')
        self.assertEqual(values['fan_rpm'], '5000')
        self.assertNotIn('fan_percent', values)

    def test_menu_returns_after_display_error(self):
        app = Anvil.Anvil('ctrl', 'asic', 115200, 2000000, 3)
        with patch('builtins.input', side_effect=['1', 'b']), patch('builtins.print'), \
             patch.object(app, 'display_probe', side_effect=RuntimeError('not connected')):
            app.display_menu()


if __name__ == '__main__':
    unittest.main()
