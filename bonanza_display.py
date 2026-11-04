"""BonanzaDisplay-v3 BAP host, matching bonanzaDisplay-fw/src/control/bap_client.c."""

from decimal import Decimal, InvalidOperation
import math
import re
import sys
import time

import bitaxeraw


BAUDRATE = 115200
MAX_FRAME = 256
PAGE_DISPLAY = 0x0B

# device_model is the ASIC model; fan_speed subscription telemetry is RPM.
FIELD_SPECS = {
    'device_family': {'label': 'Device family', 'parameter': 'deviceModel', 'size': 32, 'default': 'BONANZA'},
    'device_model': {'label': 'ASIC model', 'parameter': 'asicModel', 'size': 16, 'default': 'BZM2'},
    'ip_address': {'label': 'Host IPv4 address', 'parameter': 'wifi_ip', 'size': 16, 'default': '192.168.1.234'},
    'best_share': {'label': 'Best share', 'parameter': 'best_difficulty', 'size': 32, 'default': '123T'},
    'hashrate_ghs': {'label': 'Hashrate (GH/s)', 'parameter': 'hashrate', 'default': '1200.55'},
    'temperature_c': {'label': 'Temperature (C)', 'parameter': 'chipTemp', 'default': '58.25'},
    'power_w': {'label': 'Power (W)', 'parameter': 'power', 'default': '17.60'},
    'frequency_mhz': {'label': 'Hash frequency (MHz)', 'parameter': 'frequency', 'default': '800'},
    'fan_rpm': {'label': 'Fan speed (RPM)', 'parameter': 'fan_speed', 'default': '4200'},
}
GROUPS = {
    'systemInfo': ('device_family', 'device_model'),
    'hashrate': ('hashrate_ghs',),
    'temperature': ('temperature_c',),
    'power': ('power_w',),
    'fan_speed': ('fan_rpm',),
    'best_difficulty': ('best_share',),
    'wifi': ('ip_address',),
}
IDENTITY = {'device_family': 'BONANZA', 'device_model': 'BZM2'}


def ascii_text(value):
    value = str(value)
    if any(not 0x20 <= ord(c) <= 0x7E or c in '$*' for c in value):
        raise ValueError('BAP values must be printable ASCII without $, *, CR or LF')
    return value


def bap_frame(command, parameter, value=None):
    if not command or not parameter or any(c in ', ' for c in command + parameter):
        raise ValueError('Invalid BAP command or parameter')
    body = f'BAP,{ascii_text(command)},{ascii_text(parameter)}'
    if value is not None:
        body += ',' + ascii_text(value)
    checksum = 0
    for byte in body.encode('ascii'):
        checksum ^= byte
    frame = f'${body}*{checksum:02X}\r\n'.encode('ascii')
    if len(frame) > MAX_FRAME:
        raise ValueError('BAP frame exceeds 256 bytes')
    return frame


def encode_field(field_name, value):
    try:
        spec = FIELD_SPECS[field_name]
    except KeyError as exc:
        raise ValueError(f'Unknown bonanzaDisplay field: {field_name}') from exc
    text = ascii_text(value)
    if 'size' in spec:
        if not text or len(text) >= spec['size']:
            raise ValueError(f'{spec["label"]} requires 1..{spec["size"] - 1} ASCII characters')
    else:
        # Match the client's nonnegative parser and reserve UINT32_MAX for
        # unknown metrics. The display rounds to the nearest integer.
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?', text):
            raise ValueError(f'{spec["label"]} must be a nonnegative number without units')
        try:
            number = Decimal(text)
            floating = float(text)
            valid = (number.is_finite() and math.isfinite(floating)
                     and 0 <= floating < 4294967294.5
                     and (number == 0 or floating >= sys.float_info.min))
        except InvalidOperation:
            valid = False
        if not valid:
            raise ValueError(f'{spec["label"]} exceeds the display numeric range')
    return bap_frame('RES', spec['parameter'], text)


class BAPParser:
    """Bounded streaming parser; recover on a new $, bad checksum, or overrun."""
    def __init__(self):
        self.buffer = bytearray()

    def reset(self):
        self.buffer.clear()

    def feed(self, data):
        messages = []
        for byte in data:
            if byte == ord('$'):
                self.buffer = bytearray(b'$')
            elif self.buffer:
                if byte == 10:
                    sentence = bytes(self.buffer).removesuffix(b'\r')
                    self.reset()
                    message = self.parse(sentence)
                    if message:
                        messages.append(message)
                elif len(self.buffer) >= MAX_FRAME - 1 or self.buffer[-1] == 13 or (byte != 13 and not 32 <= byte <= 126):
                    self.reset()
                else:
                    self.buffer.append(byte)
        return messages

    @staticmethod
    def parse(sentence):
        try:
            body, checksum = sentence[1:].split(b'*')
            if not re.fullmatch(rb'[0-9A-Fa-f]{2}', checksum):
                return None
            actual = 0
            for byte in body:
                actual ^= byte
            if actual != int(checksum, 16):
                return None
            parts = body.decode('ascii').split(',', 3)
            if len(parts) < 3 or parts[0] != 'BAP' or not parts[1] or not parts[2]:
                return None
            return parts[1], parts[2], parts[3] if len(parts) == 4 else None
        except (ValueError, UnicodeDecodeError):
            return None


class ControlUART:
    """BAP bytes over ESP32 control page 0x0B, independent of ASIC UART."""
    def __init__(self, serial, debug=False):
        self.serial = serial
        self.debug = debug
        try:
            caps = self.command(0x00)
        except RuntimeError as exc:
            raise RuntimeError('Display UART transport unavailable; build/flash bitaxe-raw-bonanza '
                               '1004x 0.0.4 or newer with display page 0x0B') from exc
        expected = bytes([1, 1]) + BAUDRATE.to_bytes(4, 'little') + bytes([39, 40]) + MAX_FRAME.to_bytes(2, 'little')
        if caps != expected:
            raise RuntimeError(f'Incompatible display UART capabilities: {caps.hex(" ")}')

    def command(self, command, data=b''):
        return bitaxeraw.control_command(self.serial, 0xB0, PAGE_DISPLAY, command, data, debug=self.debug)

    def write(self, frame):
        if not 1 <= len(frame) <= MAX_FRAME:
            raise ValueError('Display UART write must be 1..256 bytes')
        ack = self.command(0x20, frame)
        if ack != b'\x01' + len(frame).to_bytes(2, 'little'):
            raise RuntimeError('Invalid display UART transmit acknowledgement')

    def read(self):
        response = self.command(0x30)
        if len(response) < 2 or response[0] != 1 or response[1] & ~1:
            raise RuntimeError('Invalid display UART receive response')
        return response[2:], bool(response[1] & 1)


class BAPHost:
    def __init__(self, transport, values=None):
        self.transport = transport
        self.values = dict(IDENTITY)
        self.values.update(values or {})
        self.frames = {name: encode_field(name, value) for name, value in self.values.items()}
        self.parser = BAPParser()
        self.subscriptions = {}
        self.requests = 0
        self.sent = 0

    def send(self, frame):
        self.transport.write(frame)
        self.sent += 1

    def publish(self, names=None):
        for name in self.frames if names is None else names:
            if name in self.frames:
                self.send(self.frames[name])

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        data, overflow = self.transport.read()
        if overflow:
            self.parser.reset()
        messages = self.parser.feed(data)
        for command, group, value in messages:
            if command not in ('REQ', 'SUB'):
                continue
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', group):
                continue
            self.requests += 1
            if group not in GROUPS:
                self.send(bap_frame('ERR', group, 'unknown_parameter'))
            elif command == 'REQ' and value is None:
                self.publish(GROUPS[group])
            elif command == 'SUB' and value and re.fullmatch(r'[0-9]{1,8}', value) and 100 <= int(value) <= 60000:
                interval = int(value) / 1000
                self.send(bap_frame('ACK', group, 'subscribed'))
                self.publish(GROUPS[group])
                self.subscriptions[group] = (interval, now + interval, now + 300)
            else:
                self.send(bap_frame('ERR', group, 'invalid_request'))
        for group, (interval, due, expires) in list(self.subscriptions.items()):
            if now >= expires:
                del self.subscriptions[group]
                self.send(bap_frame('STA', group, 'subscription_timeout'))
            elif now >= due:
                self.publish(GROUPS[group])
                self.subscriptions[group] = (interval, now + interval, expires)
        return messages


def probe(transport, seconds=15):
    """Observe an accessory request; BAP has no metric readback or RES ACK."""
    parser = BAPParser()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data, overflow = transport.read()
        if overflow:
            parser.reset()
        for command, parameter, value in parser.feed(data):
            if (command == 'REQ' and parameter == 'systemInfo' and value is None) or (
                    command == 'SUB' and parameter in GROUPS and value == '1000'):
                return command, parameter, value
        time.sleep(0.05)
    raise TimeoutError('No valid bonanzaDisplay BAP request received; check display firmware, power and UART wiring')


def serve(transport, values, seconds=0):
    host = BAPHost(transport, values)
    host.publish()
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while deadline is None or time.monotonic() < deadline:
            host.poll()
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    return host
