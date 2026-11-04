#!/usr/bin/env python3
"""Check Anvil against the actual portable C client in a bonanzaDisplay-fw checkout."""
import argparse
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bonanza_display as display


WRAPPER = r'''
#include "bap_client.h"
static bonanza_bap_client_t client;
void test_init(void) { bonanza_bap_client_init(&client, 0); }
void test_receive(const char *data, size_t n, uint32_t now) {
    bonanza_bap_client_receive(&client, (const uint8_t *)data, n, now);
}
size_t test_next(uint32_t now, char *data, size_t n) {
    return bonanza_bap_client_next_message(&client, now, data, n);
}
const char *test_text(unsigned index) {
    const char *texts[] = {client.metrics.device_family, client.metrics.device_model,
        client.metrics.ip_address, client.metrics.best_share, client.metrics.device_name};
    return index < 5 ? texts[index] : "";
}
uint32_t test_number(unsigned index) {
    uint32_t numbers[] = {client.metrics.hashrate_ghs, client.metrics.temperature_c,
        client.metrics.power_w, client.metrics.frequency_mhz, client.metrics.fan_rpm};
    return index < 5 ? numbers[index] : 0;
}
'''


def check(firmware):
    source = firmware / 'src' / 'control'
    with tempfile.TemporaryDirectory(prefix='anvil-bap-check-') as tmp:
        wrapper = Path(tmp) / 'wrapper.c'
        library = Path(tmp) / 'bap_client.so'
        wrapper.write_text(WRAPPER)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(source), str(wrapper), str(source / 'bap_client.c'),
                        '-o', str(library)], check=True)
        client = ctypes.CDLL(str(library))
        client.test_init.argtypes = []
        client.test_init.restype = None
        client.test_receive.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32]
        client.test_receive.restype = None
        client.test_next.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t]
        client.test_next.restype = ctypes.c_size_t
        client.test_text.argtypes = [ctypes.c_uint]
        client.test_text.restype = ctypes.c_char_p
        client.test_number.argtypes = [ctypes.c_uint]
        client.test_number.restype = ctypes.c_uint32
        client.test_init()

        class ClientTransport:
            now = 0

            def read(self):
                data = ctypes.create_string_buffer(256)
                size = client.test_next(self.now, data, len(data))
                return data.raw[:size], False

            def write(self, frame):
                # Exercise the actual accessory's fragmented streaming parser.
                for byte in frame:
                    client.test_receive(bytes([byte]), 1, self.now)

        transport = ClientTransport()
        values = {name: spec['default'] for name, spec in display.FIELD_SPECS.items()}
        host = display.BAPHost(transport, values)
        assert client.test_text(4) == b'Waiting for BAP'
        assert client.test_number(0) == 0xFFFFFFFF
        for now in range(0, 1800, 100):
            transport.now = now
            host.poll(now=now / 1000)
        assert host.requests == 7, host.requests
        assert [client.test_text(i) for i in range(5)] == [
            b'BONANZA', b'BZM2', b'192.168.1.234', b'123T', b'BAP connected']
        # Frequency is an optional unsolicited RES, outside current subscriptions.
        host.publish(['frequency_mhz'])
        assert [client.test_number(i) for i in range(5)] == [1201, 58, 18, 800, 4200]
        for now in range(1800, 65000, 100):
            transport.now = now
            host.poll(now=now / 1000)
        assert host.requests >= 14, host.requests
        assert client.test_text(4) == b'BAP connected'
        assert len(host.subscriptions) == 6
        print('Anvil ↔ display C client passed: startup, checksums, decimal rounding, RPM, '
              'all fields, keepalive, and 60-second subscription renewal.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path, help='bonanzaDisplay-fw checkout directory')
    args = parser.parse_args()
    check(args.firmware.expanduser().resolve())
