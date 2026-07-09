import unittest

import mc3


class FakeSerial:
    def __init__(self):
        self.port = "fake-asic"
        self.baudrate = 115200
        self.writes = []
        self.in_waiting = 0

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def read(self, size):
        return b""


def decode_write_packet(packet):
    fields = [
        mc3.decode_field(packet[index : index + mc3.ULINK_FIELD_BYTES])
        for index in range(0, len(packet), mc3.ULINK_FIELD_BYTES)
    ]
    header = fields[0]["word"]
    return {
        "chip_id": mc3.header_chip_id(header),
        "chip_num": (header >> 12) & 0x0F,
        "mode": mc3.header_mode(header),
        "data_length": mc3.header_data_length(header),
        "register": fields[1]["word"],
        "values": [field["word"] for field in fields[2:]],
    }


class MC3MiningWorkTests(unittest.TestCase):
    def test_app_note_vector_maps_to_v_work_registers(self):
        work = mc3.app_note_version_rolling_work()

        self.assertEqual(work.version, 0x00000020)
        self.assertEqual(mc3.v_base_value_for_work(work), 0x20000000)

        registers = dict(mc3.build_v_work_registers(work))
        self.assertEqual(registers[0x00000200], 0x00000000)
        self.assertEqual(registers[0x00000204], 0x33B1D465)
        self.assertEqual(registers[0x00000208], 0xFFFF7F20)

        self.assertEqual(registers[0x0000020C], 0xD9B7451C)
        self.assertEqual(registers[0x00000210], 0xD44D91EB)
        self.assertEqual(registers[0x00000214], 0x53CBB1A2)
        self.assertEqual(registers[0x00000218], 0x6BAAA858)
        self.assertEqual(registers[0x0000021C], 0x251373D4)
        self.assertEqual(registers[0x00000220], 0x02580B53)
        self.assertEqual(registers[0x00000224], 0x6551F3A8)
        self.assertEqual(registers[0x00000228], 0xF858E2B2)

        self.assertEqual(registers[0x0000022C], 0x00000000)
        self.assertEqual(registers[0x00000230], 0x0FBF250D)
        self.assertEqual(registers[0x00000234], 0xDE9EF4A6)
        self.assertEqual(registers[0x00000238], 0x59CB92B0)
        self.assertEqual(registers[0x0000023C], 0xE8DC7A13)
        self.assertEqual(registers[0x00000240], 0x83583DA3)
        self.assertEqual(registers[0x00000244], 0x0FB3044E)
        self.assertEqual(registers[0x00000248], 0x60F86A58)

        self.assertEqual(registers[0x0000024C], 0x00000001)
        self.assertEqual(registers[0x00000250], 0x00000000)
        self.assertEqual(registers[0x00000254], 0x00000000)
        self.assertEqual(registers[0x00000258], 0x00000000)

    def test_v_work_trigger_word_is_written_last(self):
        work = mc3.app_note_version_rolling_work()
        registers = mc3.build_v_work_registers(work)

        self.assertEqual(len(registers), 23)
        self.assertEqual(registers[-1], (mc3.V_WORK_TRIGGER, 0x00000000))

    def test_app_note_work_accepts_custom_note_and_target(self):
        work = mc3.app_note_version_rolling_work(
            note=(2, 0, 0, 0),
            work_target_h=0x0000FFFF,
            work_target_l=0x00FFFFFF,
        )

        registers = dict(mc3.build_v_work_registers(work))
        self.assertEqual(work.note, (2, 0, 0, 0))
        self.assertEqual(work.work_target_h, 0x0000FFFF)
        self.assertEqual(work.work_target_l, 0x00FFFFFF)
        self.assertEqual(registers[0x0000024C], 0x00000002)

    def test_recommended_pll_config_and_rolltime_for_200mhz(self):
        self.assertEqual(mc3.recommended_pll_config_for_mhz(200), (1, 160, 4, 3))
        self.assertEqual(mc3.pll_frequency_mhz(1, 160, 4, 3), 200)
        self.assertEqual(mc3.pll_config_value_for_mhz(200), 0x07010A08)
        self.assertEqual(mc3.rolltime_for_pll_mhz(200), 0x000FFFCE)
        self.assertAlmostEqual(mc3.expected_hashrate_ghs(200, chip_count=4), 998.4)

    def test_voltage_sensor_channel_map_matches_errata(self):
        self.assertEqual(mc3.VOLTAGE_CHANNELS[0], "VDDIO12")
        self.assertEqual(mc3.VOLTAGE_CHANNELS[13], "VDD")
        self.assertEqual(mc3.VOLTAGE_CHANNELS[15], "VSS")
        self.assertEqual(mc3.VOLTAGE_DOUT_REGISTERS[0], 0x00053240)
        self.assertEqual(mc3.VOLTAGE_DOUT_REGISTERS[13], 0x00053274)
        self.assertEqual(mc3.VOLTAGE_DOUT_REGISTERS[15], 0x0005327C)

    def test_voltage_rail_summary_uses_prescaler_corrections(self):
        self.assertEqual(mc3.rail_summary_channels(), (0, 2, 7, 8, 9, 10, 11, 12, 13, 14))
        self.assertEqual(mc3.VOLTAGE_RAIL_SUMMARY[0], ("VDDIO12", (0,), 2.0))
        self.assertEqual(mc3.VOLTAGE_RAIL_SUMMARY[-1], ("VDD", (13, 14), 2.0))
        self.assertAlmostEqual(mc3.scaled_voltage_for_rail(0.55, 2.0), 1.10)

    def test_hash_frequency_status_matches_expected_frequency(self):
        status = {
            "pll0_cfg": 0x07010A08,
            "pll0_en": 0x00000007,
            "pll0_locked": True,
            "rolltime": 0x000FFFCE,
        }

        self.assertTrue(mc3.hash_frequency_status_matches(status, 200))

        status["pll0_locked"] = False
        self.assertFalse(mc3.hash_frequency_status_matches(status, 200))

    def test_set_hash_frequency_writes_errata_live_reprogram_sequence(self):
        fake = FakeSerial()

        mc3.set_hash_frequency(fake, 200, start_chip_id=0, chip_num=mc3.CHIP_NUM_ALL)

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["chip_id"], entry["chip_num"], entry["register"], entry["values"][0])
            for entry in decoded
        ]
        self.assertEqual(
            register_writes,
            [
                (0, mc3.CHIP_NUM_ALL, 0x00011000, 0x80000570),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000000),
                (0, mc3.CHIP_NUM_ALL, 0x00040000, 0x07010A08),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000001),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000003),
                (0, mc3.CHIP_NUM_ALL, 0x00000410, 0x000FFFCE),
            ],
        )

    def test_cold_set_hash_frequency_writes_startup_pll_sequence(self):
        fake = FakeSerial()

        mc3.cold_set_hash_frequency(fake, 200, start_chip_id=0, chip_num=mc3.CHIP_NUM_ALL)

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["chip_id"], entry["chip_num"], entry["register"], entry["values"][0])
            for entry in decoded
        ]
        self.assertEqual(
            register_writes,
            [
                (0, mc3.CHIP_NUM_ALL, 0x00011000, 0x80000570),
                (0, mc3.CHIP_NUM_ALL, 0x00040000, 0x07010A08),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000001),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000003),
                (0, mc3.CHIP_NUM_ALL, 0x00000410, 0x000FFFCE),
            ],
        )

    def test_cold_set_hash_frequency_can_skip_pll_config_write(self):
        fake = FakeSerial()

        mc3.cold_set_hash_frequency(
            fake,
            200,
            start_chip_id=0,
            chip_num=mc3.CHIP_NUM_ALL,
            write_pll_config=False,
        )

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["chip_id"], entry["chip_num"], entry["register"], entry["values"][0])
            for entry in decoded
        ]
        self.assertEqual(
            register_writes,
            [
                (0, mc3.CHIP_NUM_ALL, 0x00011000, 0x80000570),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000001),
                (0, mc3.CHIP_NUM_ALL, 0x00040004, 0x00000003),
                (0, mc3.CHIP_NUM_ALL, 0x00000410, 0x000FFFCE),
            ],
        )

    def test_version_rolling_mining_config_sequence_matches_app_note(self):
        self.assertEqual(
            mc3.version_rolling_mining_config_registers(),
            [
                (0x00011000, 0x80000570),
                (0x00000410, 0x000FFFCE),
                (0x00000400, 0x8800D2FF),
                (0x00000400, 0x880058FF),
                (0x00000444, 0xFFFF0001),
                (0x00040004, 0x00000003),
            ],
        )

    def test_parse_app_note_version_rolling_nonce_buffer_example(self):
        words = [
            0x00000001,
            0x00000000,
            0x00000000,
            0x00000000,
            0x80000097,
            0x68FA4653,
            0x20000014,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
        ]

        parsed = mc3.parse_version_rolling_nonce_buffer(words)

        self.assertEqual(parsed["note"], (1, 0, 0, 0))
        self.assertEqual(
            parsed["nonces"][0],
            {
                "index": 0,
                "valid": True,
                "core_id": 0,
                "ntime_offset": 0x0097,
                "nonce": 0x68FA4653,
                "version": 0x20000014,
            },
        )
        self.assertFalse(parsed["nonces"][1]["valid"])

    def test_validate_app_note_nonce_example(self):
        work = mc3.app_note_version_rolling_work()
        nonce = {
            "index": 0,
            "valid": True,
            "core_id": 0,
            "ntime_offset": 0x0097,
            "nonce": 0x68FA4653,
            "version": 0x20000014,
        }

        result = mc3.validate_version_rolling_nonce(work, nonce)

        self.assertEqual(result["version"], 0x14000020)
        self.assertEqual(result["ntime"], 0xCAB1D465)
        self.assertEqual(result["nonce"], 0x68FA4653)
        self.assertEqual(
            result["hash_hex"],
            "00000000001CDA639A9BF98BA87FB765EA9D101CC51616A8D7CFF6167CF495AA",
        )
        self.assertTrue(result["meets_target"])

    def test_validate_hardware_returned_nonce_examples(self):
        work = mc3.app_note_version_rolling_work()
        nonces = [
            {"index": 0, "valid": True, "core_id": 3, "ntime_offset": 0x0001, "nonce": 0x0F974B35, "version": 0x20000003},
            {"index": 1, "valid": True, "core_id": 6, "ntime_offset": 0x0000, "nonce": 0x9DDCA200, "version": 0x20000006},
            {"index": 2, "valid": True, "core_id": 3, "ntime_offset": 0x0003, "nonce": 0xA328152C, "version": 0x20000003},
            {"index": 3, "valid": True, "core_id": 6, "ntime_offset": 0x0003, "nonce": 0x525BFA4C, "version": 0x20000006},
            {"index": 4, "valid": True, "core_id": 2, "ntime_offset": 0x0002, "nonce": 0xC0F01C35, "version": 0x20000002},
        ]

        results = [mc3.validate_version_rolling_nonce(work, nonce) for nonce in nonces]

        self.assertEqual(
            [result["hash_hex"] for result in results],
            [
                "00000000CB8E44BD3E722EB14D87B6953226125A96B557BB858DF11E3EE14309",
                "000000003FC94708D84D26B96D8647C44F6CBEC8B0A17BBD06E8B4AAD7BFE74E",
                "00000000D437E219B947E5DD3CF0F7732A7A3F3C1C6D824D7D379FCB76FAEB5D",
                "0000000013819C2E650BEE407A9169A69E569817A0346B2C0793470F8DE26FE0",
                "000000005DF67A2C8A0C3C038C7281E9A85946FC50EF7976235537F1A91F215C",
            ],
        )
        self.assertTrue(all(result["meets_target"] for result in results))

    def test_bulk_nonce_validation_keeps_original_nonce_record(self):
        work = mc3.app_note_version_rolling_work()
        parsed = {
            "note": (1, 0, 0, 0),
            "nonces": [
                {"index": 0, "valid": True, "core_id": 3, "ntime_offset": 0x0001, "nonce": 0x0F974B35, "version": 0x20000003},
                {"index": 1, "valid": False, "core_id": 0, "ntime_offset": 0x0000, "nonce": 0x00000000, "version": 0x00000000},
            ],
        }

        results = mc3.validate_version_rolling_nonces(work, parsed)

        self.assertEqual(results[0]["nonce_record"]["index"], 0)
        self.assertEqual(results[0]["nonce_record"]["nonce"], 0x0F974B35)
        self.assertEqual(results[0]["nonce"], 0x0F974B35)
        self.assertTrue(results[0]["meets_target"])
        self.assertEqual(results[1]["nonce_record"]["index"], 1)
        self.assertNotIn("meets_target", results[1])

    def test_hashrate_estimate_from_work_target(self):
        self.assertEqual(mc3.work_target_value(0x00000001, 0x00000000), 2**32)
        self.assertEqual(mc3.work_per_nonce(0x00000001, 0x00000000), 2**64)
        self.assertEqual(
            mc3.hashrate_from_nonce_count(2, 4.0, 0x00000001, 0x00000000),
            2**63,
        )

    def test_spdlog_timer_and_hashrate_helpers(self):
        self.assertEqual(mc3.SPDLOG_BASE_DEFAULT, mc3.SPDLOG_BASE_APP_NOTE)
        self.assertEqual(mc3.spdlog_work_cfg_value(0x00), 0x8C00DA00)
        self.assertEqual(mc3.spdlog_work_cfg_value(0xFF), 0x8C00DAFF)
        self.assertEqual(
            mc3.spdlog_registers(mc3.SPDLOG_BASE_DATASHEET),
            {
                "timer": 0x00010204,
                "rst": 0x00010208,
                "pass": 0x0001020C,
                "fail": 0x00010210,
            },
        )
        self.assertEqual(
            mc3.spdlog_registers(mc3.SPDLOG_BASE_APP_NOTE),
            {
                "timer": 0x00011004,
                "rst": 0x00011008,
                "pass": 0x0001100C,
                "fail": 0x00011010,
            },
        )
        self.assertAlmostEqual(mc3.spdlog_runtime_seconds(0x0030), 4.02653184)
        self.assertEqual(mc3.spdlog_timer_count_for_seconds(4.0), 0x0030)
        self.assertEqual(mc3.spdlog_timer_value(0x0030), 0x00010030)
        self.assertEqual(mc3.core_target_leading_zeros(0x00), 24)
        self.assertEqual(mc3.core_target_leading_zeros(0x01), 25)
        self.assertEqual(mc3.core_target_leading_zeros(0x03), 26)
        self.assertEqual(mc3.core_target_leading_zeros(0x05), 26)
        self.assertEqual(mc3.core_target_leading_zeros(0x7F), 31)
        self.assertEqual(mc3.core_target_leading_zeros(0xFF), 32)
        self.assertEqual(mc3.core_target_for_leading_zeros(24), 0x00)
        self.assertEqual(mc3.core_target_for_leading_zeros(26), 0x03)
        self.assertEqual(mc3.core_target_for_leading_zeros(32), 0xFF)
        self.assertEqual(mc3.spdlog_hashrate_hs(2, 4.0, 0x00), 2**23)
        self.assertEqual(mc3.spdlog_candidate_hashrate_hs(2, 3, 4.0, 0x00), 5 * 2**22)

    def test_start_spdlog_broadcast_matches_manufacturer_sequence(self):
        fake = FakeSerial()

        result = mc3.start_spdlog_broadcast(
            fake,
            start_chip_id=0,
            chip_num=mc3.CHIP_NUM_ALL,
            timer_count=0x0030,
            core_target=0x00,
            debug=False,
        )

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["chip_id"], entry["chip_num"], entry["register"], entry["values"][0])
            for entry in decoded
        ]
        self.assertEqual(result["work_cfg"], 0x8C00DA00)
        self.assertEqual(
            register_writes,
            [
                (0, mc3.CHIP_NUM_ALL, 0x00011000, 0x80000570),
                (0, mc3.CHIP_NUM_ALL, 0x00000400, 0x8C00DA00),
                (0, mc3.CHIP_NUM_ALL, 0x00011008, 0x00000001),
                (0, mc3.CHIP_NUM_ALL, 0x00011004, 0x00010030),
            ],
        )

    def test_32byte_fields_must_be_exactly_32_bytes(self):
        with self.assertRaises(ValueError):
            mc3.words_from_32byte_field_for_mc3(b"\x00" * 31)

    def test_start_app_note_mining_writes_expected_register_sequence(self):
        fake = FakeSerial()

        work = mc3.start_app_note_version_rolling_mining(fake, debug=False)

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["register"], entry["values"][0])
            for entry in decoded
        ]

        self.assertEqual(work, mc3.app_note_version_rolling_work())
        self.assertEqual(len(register_writes), 32)
        self.assertEqual(
            register_writes[:9],
            [
                (0x00011000, 0x80000570),
                (0x00000410, 0x000FFFCE),
                (0x00000400, 0x8800D2FF),
                (0x00000400, 0x880058FF),
                (0x00000444, 0xFFFF0001),
                (0x00040004, 0x00000003),
                (0x00000404, 0xFFFFFFFF),
                (0x00000408, 0xFFFFFFFF),
                (0x00000440, 0x20000000),
            ],
        )
        self.assertEqual(register_writes[-1], (0x00000258, 0x00000000))
        self.assertTrue(all(entry["mode"] == mc3.MODE_WRITE for entry in decoded))
        self.assertTrue(all(entry["chip_id"] == 0 for entry in decoded))
        self.assertTrue(all(entry["chip_num"] == mc3.CHIP_NUM_ALL for entry in decoded))

    def test_start_app_note_mining_can_use_non_default_rolltime(self):
        fake = FakeSerial()
        rolltime = mc3.rolltime_for_pll_mhz(300)

        mc3.start_app_note_version_rolling_mining(fake, rolltime=rolltime, debug=False)

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["register"], entry["values"][0])
            for entry in decoded
        ]
        self.assertEqual(register_writes[1], (0x00000410, 0x000AAA79))

    def test_distinct_range_v_base_values_for_four_chips(self):
        work = mc3.app_note_version_rolling_work()

        self.assertEqual(
            mc3.v_base_values_for_chip_range(work, first_chip_id=0, chip_count=4),
            [
                (0, 0x20000000),
                (1, 0x20004000),
                (2, 0x20008000),
                (3, 0x2000C000),
            ],
        )

    def test_start_app_note_mining_distinct_ranges_writes_per_chip_v_base(self):
        fake = FakeSerial()

        work = mc3.start_app_note_version_rolling_mining_distinct_ranges(
            fake,
            first_chip_id=0,
            chip_count=4,
            debug=False,
        )

        decoded = [decode_write_packet(packet) for packet in fake.writes]
        register_writes = [
            (entry["chip_id"], entry["chip_num"], entry["register"], entry["values"][0])
            for entry in decoded
        ]

        self.assertEqual(work, mc3.app_note_version_rolling_work())
        self.assertEqual(len(register_writes), 35)
        self.assertEqual(
            register_writes[8:12],
            [
                (0, 0, 0x00000440, 0x20000000),
                (1, 0, 0x00000440, 0x20004000),
                (2, 0, 0x00000440, 0x20008000),
                (3, 0, 0x00000440, 0x2000C000),
            ],
        )
        self.assertEqual(register_writes[-1], (0, mc3.CHIP_NUM_ALL, 0x00000258, 0x00000000))


if __name__ == "__main__":
    unittest.main()
