import time

import bitaxeraw


START_FLAG = 0x55
CHIP_NUM_ALL = 0x8
MODE_WRITE = 0x1
MODE_READ = 0x2
MODE_INIT = 0x4

ECC_TB_0 = bytes.fromhex(
    "0c465e1458120a405b1109430f455d17541e064c004a52180349511b571d054f"
    "571d054f0349511b004a5218541e064c0f455d175b11094358120a400c465e14"
    "511b0349054f571d064c541e5218004a09435b115d170f455e140c460a405812"
    "0a4058125e140c465d170f4509435b115218004a064c541e054f571d511b0349"
    "2f657d377b31296378322a602c667e34773d256f2369713b206a7238743e266c"
    "743e266c206a72382369713b773d256f2c667e3478322a607b3129632f657d37"
    "7238206a266c743e256f773d713b23692a6078327e342c667d372f6529637b31"
    "29637b317d372f657e342c662a607832713b2369256f773d266c743e7238206a"
)
ECC_TB_1 = bytes.fromhex(
    "0c292a0f25000326260300250f2a290c20050623092c2f0a0a2f2c0923060520"
    "3d181b3e14313217173231143e1b183d11343712381d1e3b3b1e1d3812373411"
    "381d1e3b11343712123734113b1e1d38143132173d181b3e3e1b183d17323114"
    "092c2f0a20050623230605200a2f2c09250003260c292a0f0f2a290c26030025"
    "022724012b0e0d28280d0e2b012427022e0b082d07222104042122072d080b2e"
    "331615301a3f3c19193c3f1a301516331f3a391c36131035351013361c393a1f"
    "361310351f3a391c1c393a1f351013361a3f3c193316153030151633193c3f1a"
    "072221042e0b082d2d080b2e042122072b0e0d280227240101242702280d0e2b"
)
ECC_TB_2 = bytes.fromhex(
    "0c071f1419120a011a1109020f041c17151e060d000b13180308101b161d050e"
    "161d050e0308101b000b1318151e060d0f041c171a11090219120a010c071f14"
    "101b0308050e161d060d151e1318000b09021a111c170f041f140c070a011912"
    "0a0119121f140c071c170f0409021a111318000b060d151e050e161d101b0308"
    "6e657d767b70686378736b606d667e75777c646f6269717a616a7279747f676c"
    "747f676c616a72796269717a777c646f6d667e7578736b607b7068636e657d76"
    "7279616a676c747f646f777c717a62696b6078737e756d667d766e6568637b70"
    "68637b707d766e657e756d666b607873717a6269646f777c676c747f7279616a"
)
ECC_TB_3 = bytes.fromhex(
    "0c686b0f64000367670300640f6b680c61050662096d6e0a0a6e6d0962060561"
    "7c181b7f14707317177370147f1b187c11757612791d1e7a7a1e1d7912767511"
    "791d1e7a11757612127675117a1e1d79147073177c181b7f7f1b187c17737014"
    "096d6e0a61050662620605610a6e6d09640003670c686b0f0f6b680c67030064"
    "523635513a5e5d39395d5e3a513536523f5b583c57333054543033573c585b3f"
    "224645214a2e2d49492d2e4a214546224f2b284c27434024244043274c282b4f"
    "274340244f2b284c4c282b4f244043274a2e2d492246452121454622492d2e4a"
    "573330543f5b583c3c585b3f543033573a5e5d395236355151353652395d5e3a"
)


def pretty_hex(data):
    return " ".join(f"{byte:02X}" for byte in data)


def calculate_ecc(word, is_tail):
    ecc = (
        ECC_TB_0[word & 0xFF]
        ^ ECC_TB_1[(word >> 8) & 0xFF]
        ^ ECC_TB_2[(word >> 16) & 0xFF]
        ^ ECC_TB_3[(word >> 24) & 0xFF]
    )
    ecc ^= 0xC3 if is_tail else 0x0C
    return ecc & 0x7F


def encode_field(word, is_tail=False):
    ecc = calculate_ecc(word, is_tail)
    return word.to_bytes(4, "big") + bytes([((1 if is_tail else 0) << 7) | ecc])


def decode_field(field):
    if len(field) != 5:
        raise ValueError("ULink fields are 5 bytes")

    word = int.from_bytes(field[:4], "big")
    tag = bool(field[4] & 0x80)
    ecc = field[4] & 0x7F
    expected = calculate_ecc(word, tag)
    return {
        "word": word,
        "tag": tag,
        "ecc": ecc,
        "expected_ecc": expected,
        "ecc_ok": ecc == expected,
    }


def build_header(chip_id, chip_num, mode, data_length):
    return (
        (START_FLAG << 24)
        | ((chip_id & 0xFF) << 16)
        | ((chip_num & 0x0F) << 12)
        | ((mode & 0x0F) << 8)
        | (data_length & 0xFF)
    )


def build_init_packet(first_chip_id=0):
    header = build_header(chip_id=0, chip_num=CHIP_NUM_ALL, mode=MODE_INIT, data_length=1)
    first_chip_id_word = (first_chip_id & 0xFF) << 24
    return b"".join(
        [
            encode_field(header, is_tail=False),
            encode_field(0x00000000, is_tail=False),
            encode_field(first_chip_id_word, is_tail=True),
        ]
    )


def init_id_from_data_word(word):
    return (word >> 24) & 0xFF


def parse_init_response(response):
    if len(response) < 15:
        return None

    for offset in range(0, len(response) - 14):
        fields = [decode_field(response[offset + idx : offset + idx + 5]) for idx in (0, 5, 10)]
        header = fields[0]["word"]
        if (header >> 24) == START_FLAG and ((header >> 8) & 0x0F) == MODE_INIT:
            next_chip_id = init_id_from_data_word(fields[2]["word"])
            return {
                "offset": offset,
                "fields": fields,
                "next_chip_id": next_chip_id,
            }
    return None


def reset_chain(control_serial, debug=False):
    print("Resetting MC3 chain...")
    bitaxeraw.gpio_set(control_serial, 0xAB, bitaxeraw.GPIO_ASIC_RST, bitaxeraw.GPIO_LOW, debug=debug)
    time.sleep(0.1)
    bitaxeraw.gpio_set(control_serial, 0xAB, bitaxeraw.GPIO_ASIC_RST, bitaxeraw.GPIO_HIGH, debug=debug)
    time.sleep(0.1)


def enumerate_chain(control_serial, asic_serial, first_chip_id=0, debug=False):
    reset_chain(control_serial, debug=debug)
    asic_serial.reset_input_buffer()
    asic_serial.reset_output_buffer()

    # A break condition would be ideal, but repeated zero bytes also give the ULink FSM a quiet line.
    asic_serial.write(b"\x00" * 8)
    asic_serial.flush()
    time.sleep(0.05)

    packet = build_init_packet(first_chip_id=first_chip_id)
    print(f"Sending MC3 ULink INIT packet on {asic_serial.port} ({len(packet)} bytes)...")
    print(f"mc3 init tx: [{pretty_hex(packet)}]")

    bytes_written = asic_serial.write(packet)
    asic_serial.flush()
    print(f"Wrote {bytes_written} byte(s) to ASIC serial.")
    time.sleep(0.5)

    response = asic_serial.read(max(64, asic_serial.in_waiting))
    print(f"MC3 response bytes ({len(response)}): [{pretty_hex(response)}]")

    parsed = parse_init_response(response)
    if parsed:
        print(f"ULink INIT response at offset {parsed['offset']}")
        for index, field in enumerate(parsed["fields"]):
            ecc_note = ""
            if index == 2 and not field["ecc_ok"]:
                ecc_note = " (normal for INIT data response)"
            print(
                f"  field {index}: 0x{field['word']:08X}, "
                f"tag={int(field['tag'])}, ecc=0x{field['ecc']:02X}, "
                f"ecc_ok={field['ecc_ok']}{ecc_note}"
            )
        print(f"MC3 chain count: {parsed['next_chip_id'] - first_chip_id}")
    else:
        print("No valid ULink INIT response found.")

    return response
