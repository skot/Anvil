import hashlib
import time
from dataclasses import dataclass, replace

import bitaxeraw


START_FLAG = 0x55
CHIP_NUM_ALL = 0x8
MODE_WRITE = 0x1
MODE_READ = 0x2
MODE_INIT = 0x4

THERMAL_SDIF_ENABLE = 0x00051020
THERMAL_CLOCK = 0x00051010
THERMAL_COMMAND = 0x00051028
THERMAL_STATUS = 0x00051024
THERMAL_DONE = 0x00051238
THERMAL_DOUT = 0x00051240

VOLTAGE_SDIF_ENABLE = 0x00053020
VOLTAGE_CLOCK = 0x00053010
VOLTAGE_COMMAND = 0x00053028
VOLTAGE_STATUS = 0x00053024
VOLTAGE_DONE = 0x00053238
VOLTAGE_DOUT_BASE = 0x00053240
VOLTAGE_CLOCK_DEFAULT = 0x01010000

THERMAL_RESOLUTION_BITS = 12
VOLTAGE_RESOLUTION_BITS = 14
VOLTAGE_VREF = 0.5945
VOLTAGE_CHANNELS = {
    0: "VDDIO12",
    1: "VEFS",
    2: "VDDH",
    3: "VDDA",
    4: "VSS",
    5: "VSS",
    6: "VSS",
    7: "VDDI1",
    8: "VDDI1",
    9: "VDDI2",
    10: "VDDI2",
    11: "VDDI3",
    12: "VDDI3",
    13: "VDD",
    14: "VDD",
    15: "VSS",
}
CONNECTED_VOLTAGE_CHANNELS = tuple(
    channel for channel, name in VOLTAGE_CHANNELS.items() if name != "VSS"
)
ALL_VOLTAGE_CHANNELS = tuple(range(16))
VOLTAGE_DOUT_REGISTERS = {
    channel: VOLTAGE_DOUT_BASE + channel * 4
    for channel in ALL_VOLTAGE_CHANNELS
}
VOLTAGE_RAIL_SUMMARY = (
    ("VDDIO12", (0,), 2.0),
    ("VDDH", (2,), 1.0),
    ("VDDI1", (7, 8), 1.0),
    ("VDDI2", (9, 10), 1.0),
    ("VDDI3", (11, 12), 1.0),
    ("VDD", (13, 14), 2.0),
)

GLOBAL_SPD = 0x00011000
SPDLOG_BASE_DATASHEET = 0x00010200
SPDLOG_BASE_APP_NOTE = 0x00011000
SPDLOG_BASE_DEFAULT = SPDLOG_BASE_APP_NOTE
SPDLOG_TIMER_OFFSET = 0x04
SPDLOG_RST_OFFSET = 0x08
SPDLOG_PASS_OFFSET = 0x0C
SPDLOG_FAIL_OFFSET = 0x10
SPDLOG_TIMER = SPDLOG_BASE_DEFAULT + SPDLOG_TIMER_OFFSET
SPDLOG_RST = SPDLOG_BASE_DEFAULT + SPDLOG_RST_OFFSET
SPDLOG_PASS = SPDLOG_BASE_DEFAULT + SPDLOG_PASS_OFFSET
SPDLOG_FAIL = SPDLOG_BASE_DEFAULT + SPDLOG_FAIL_OFFSET
PLL0_CFG = 0x00040000
PLL0_EN = 0x00040004

WORK_CFG = 0x00000400
WORK_TARGET_L = 0x00000404
WORK_TARGET_H = 0x00000408
TBASE = 0x0000040C
ROLLTIME = 0x00000410
NONCE_UPDATE = 0x00000424
V_BASE = 0x00000440
V_CTRL = 0x00000444

V_WORK_BASE = 0x00000200
V_WORK_INIT = 0x00000200
V_WORK_NTIME = 0x00000204
V_WORK_NBITS = 0x00000208
V_WORK_MERKLE_ROOT = 0x0000020C
V_WORK_PREVIOUS_HASH = 0x0000022C
V_WORK_NOTE = 0x0000024C
V_WORK_TRIGGER = 0x00000258

NONCE_BUFFER = 0x00000300
NONCE_BUFFER_NOTE_WORDS = 4
VERSION_ROLLING_NONCE_COUNT = 5

DEFAULT_GLOBAL_SPD_VALUE = 0x80000570
DEFAULT_ROLLTIME_200MHZ = 0x000FFFCE
DEFAULT_WORK_CFG_APPLY_AND_RESET = 0x8800D2FF
DEFAULT_WORK_CFG_MINING = 0x880058FF
DEFAULT_WORK_CFG_SPDLOG = 0x8C00DA00
DEFAULT_V_CTRL_VERSION_ROLLING = 0xFFFF0001
DEFAULT_PLL0_ENABLE = 0x00000003
DEFAULT_WORK_TARGET_L = 0xFFFFFFFF
DEFAULT_WORK_TARGET_H = 0xFFFFFFFF
DEFAULT_VERSION_MASK_BITS = 16
PLL_REFCLK_MHZ = 25
PLL_LOCK_BIT = 0x00000004
ROLLTIME_OFFSET = 50
SPDLOG_TIMER_ENABLE = 0x00010000
SPDLOG_XCLK_HZ = 12_500_000

PLL_RECOMMENDED_CONFIGS = {
    100: (1, 160, 7, 4),
    125: (1, 160, 7, 3),
    150: (1, 150, 4, 4),
    175: (1, 147, 6, 2),
    200: (1, 160, 4, 3),
    225: (1, 144, 7, 1),
    250: (1, 160, 7, 1),
    275: (1, 154, 6, 1),
    300: (1, 144, 5, 1),
    325: (1, 156, 5, 1),
    350: (1, 140, 4, 1),
    375: (1, 150, 4, 1),
    400: (1, 160, 4, 1),
    425: (1, 153, 2, 2),
    450: (1, 144, 7, 0),
    475: (1, 152, 7, 0),
    500: (1, 160, 7, 0),
    525: (1, 147, 6, 0),
    550: (1, 154, 6, 0),
    575: (1, 138, 5, 0),
    600: (1, 144, 5, 0),
    625: (1, 150, 5, 0),
    650: (1, 156, 5, 0),
    675: (1, 135, 4, 0),
    700: (1, 140, 4, 0),
    725: (1, 145, 4, 0),
    750: (1, 150, 4, 0),
    775: (1, 155, 4, 0),
    800: (1, 160, 4, 0),
    825: (1, 132, 3, 0),
    850: (1, 136, 3, 0),
    875: (1, 140, 3, 0),
    900: (1, 144, 3, 0),
    925: (1, 148, 3, 0),
    950: (1, 152, 3, 0),
    975: (1, 156, 3, 0),
    1000: (1, 160, 3, 0),
}

APP_NOTE_VERSION_ROLLING_HEADER_HEX = (
    "00000020"
    "60F86A580FB3044E83583DA3E8DC7A1359CB92B0DE9EF4A60FBF250D"
    "00000000"
    "F858E2B26551F3A802580B53251373D46BAAA85853CBB1A2D44D91EB"
    "D9B7451C"
    "33B1D465"
    "FFFF7F20"
    "F355C106"
)

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


@dataclass(frozen=True)
class MC3MiningWork:
    version: int
    previous_hash: bytes
    merkle_root: bytes
    ntime: int
    nbits: int
    work_target_l: int = DEFAULT_WORK_TARGET_L
    work_target_h: int = DEFAULT_WORK_TARGET_H
    note: tuple = (1, 0, 0, 0)
    work_init: int = 0

    def __post_init__(self):
        _validate_u32("version", self.version)
        _validate_u32("ntime", self.ntime)
        _validate_u32("nbits", self.nbits)
        _validate_u32("work_target_l", self.work_target_l)
        _validate_u32("work_target_h", self.work_target_h)
        _validate_u32("work_init", self.work_init)
        if len(self.previous_hash) != 32:
            raise ValueError("previous_hash must be 32 bytes")
        if len(self.merkle_root) != 32:
            raise ValueError("merkle_root must be 32 bytes")
        if len(self.note) != 4:
            raise ValueError("note must contain exactly four 32-bit words")
        for index, word in enumerate(self.note):
            _validate_u32(f"note[{index}]", word)


def _validate_u32(name, value):
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be a 32-bit unsigned integer")


def _hex_bytes(value, expected_len):
    if isinstance(value, bytes):
        data = value
    else:
        data = bytes.fromhex(value)
    if len(data) != expected_len:
        raise ValueError(f"expected {expected_len} bytes, got {len(data)}")
    return data


def app_note_version_rolling_work(
    note=(1, 0, 0, 0),
    work_target_l=DEFAULT_WORK_TARGET_L,
    work_target_h=DEFAULT_WORK_TARGET_H,
):
    header = _hex_bytes(APP_NOTE_VERSION_ROLLING_HEADER_HEX, 80)
    return MC3MiningWork(
        version=int.from_bytes(header[0:4], "big"),
        previous_hash=header[4:36],
        merkle_root=header[36:68],
        ntime=int.from_bytes(header[68:72], "big"),
        nbits=int.from_bytes(header[72:76], "big"),
        work_target_l=work_target_l,
        work_target_h=work_target_h,
        note=note,
    )


def mining_work_with(work, **changes):
    return replace(work, **changes)


def byte_swap_u32(word):
    _validate_u32("word", word)
    return int.from_bytes(word.to_bytes(4, "big"), "little")


def words_from_32byte_field_for_mc3(data):
    data = _hex_bytes(data, 32)
    words = [
        int.from_bytes(data[index : index + 4], "big")
        for index in range(0, len(data), 4)
    ]
    return tuple(reversed(words))


def v_base_value_for_work(work):
    return byte_swap_u32(work.version)


def version_range_stride(chip_count, version_mask_bits=DEFAULT_VERSION_MASK_BITS):
    if not 1 <= chip_count <= 256:
        raise ValueError("chip_count must be 1-256")
    if not 1 <= version_mask_bits <= 32:
        raise ValueError("version_mask_bits must be 1-32")
    version_space = 1 << version_mask_bits
    if chip_count > version_space or version_space % chip_count:
        raise ValueError("chip_count must divide the version rolling space")
    return version_space // chip_count


def v_base_values_for_chip_range(work, first_chip_id=0, chip_count=4, version_mask_bits=DEFAULT_VERSION_MASK_BITS):
    base = v_base_value_for_work(work)
    stride = version_range_stride(chip_count, version_mask_bits=version_mask_bits)
    return [
        (first_chip_id + index, (base + index * stride) & 0xFFFFFFFF)
        for index in range(chip_count)
    ]


def build_v_work_registers(work):
    merkle_words = words_from_32byte_field_for_mc3(work.merkle_root)
    previous_hash_words = words_from_32byte_field_for_mc3(work.previous_hash)
    registers = [
        (V_WORK_INIT, work.work_init),
        (V_WORK_NTIME, work.ntime),
        (V_WORK_NBITS, work.nbits),
    ]
    registers.extend(
        (V_WORK_MERKLE_ROOT + index * 4, word)
        for index, word in enumerate(merkle_words)
    )
    registers.extend(
        (V_WORK_PREVIOUS_HASH + index * 4, word)
        for index, word in enumerate(previous_hash_words)
    )
    registers.extend((V_WORK_NOTE + index * 4, word) for index, word in enumerate(work.note))
    return registers


def version_rolling_mining_config_registers(
    rolltime=DEFAULT_ROLLTIME_200MHZ,
    work_cfg_apply_and_reset=DEFAULT_WORK_CFG_APPLY_AND_RESET,
    work_cfg_mining=DEFAULT_WORK_CFG_MINING,
    v_ctrl=DEFAULT_V_CTRL_VERSION_ROLLING,
    pll0_enable=DEFAULT_PLL0_ENABLE,
):
    return [
        (GLOBAL_SPD, DEFAULT_GLOBAL_SPD_VALUE),
        (ROLLTIME, rolltime),
        (WORK_CFG, work_cfg_apply_and_reset),
        (WORK_CFG, work_cfg_mining),
        (V_CTRL, v_ctrl),
        (PLL0_EN, pll0_enable),
    ]


def pll_config_value(refdiv, fbdiv, postdiv1, postdiv2):
    if not 1 <= refdiv <= 0x40:
        raise ValueError("refdiv must encode into 6 bits")
    if not 0 <= fbdiv <= 0xFFF:
        raise ValueError("fbdiv must fit in 12 bits")
    if not 0 <= postdiv1 <= 0x7:
        raise ValueError("postdiv1 must fit in 3 bits")
    if not 0 <= postdiv2 <= 0x7:
        raise ValueError("postdiv2 must fit in 3 bits")

    # Assumed packing from the documented field widths and hardware readback:
    # REFDIV[5:0] encodes refdiv - 1, FBDIV[17:6],
    # POSTDIV1[20:18], POSTDIV2[23:21].
    return (refdiv - 1) | (fbdiv << 6) | (postdiv1 << 18) | (postdiv2 << 21)


def pll_frequency_mhz(refdiv, fbdiv, postdiv1, postdiv2, refclk_mhz=PLL_REFCLK_MHZ):
    return refclk_mhz * fbdiv / (refdiv * (postdiv1 + 1) * (postdiv2 + 1))


def recommended_pll_config_for_mhz(frequency_mhz):
    try:
        return PLL_RECOMMENDED_CONFIGS[int(frequency_mhz)]
    except KeyError as exc:
        supported = ", ".join(str(freq) for freq in sorted(PLL_RECOMMENDED_CONFIGS))
        raise ValueError(f"unsupported PLL frequency; choose one of: {supported}") from exc


def pll_config_value_for_mhz(frequency_mhz):
    return pll_config_value(*recommended_pll_config_for_mhz(frequency_mhz))


def rolltime_for_pll_mhz(frequency_mhz, offset=ROLLTIME_OFFSET):
    if frequency_mhz <= 0:
        raise ValueError("frequency_mhz must be positive")
    return round((2**24 * 12.5) / frequency_mhz - offset)


def expected_hashrate_ghs(frequency_mhz, chip_count=1):
    return (8 * 156 * frequency_mhz * 1_000_000 * chip_count) / 1_000_000_000


def set_hash_frequency(
    asic_serial,
    frequency_mhz,
    start_chip_id=0,
    chip_num=CHIP_NUM_ALL,
    update_rolltime=True,
    debug=False,
):
    pll_config = pll_config_value_for_mhz(frequency_mhz)
    writes = [
        (GLOBAL_SPD, DEFAULT_GLOBAL_SPD_VALUE),
        (PLL0_CFG, pll_config),
        (PLL0_EN, DEFAULT_PLL0_ENABLE),
    ]
    if update_rolltime:
        writes.append((ROLLTIME, rolltime_for_pll_mhz(frequency_mhz)))

    return write_registers(
        asic_serial,
        chip_id=start_chip_id,
        registers=writes,
        chip_num=chip_num,
        debug=debug,
    )


def cold_set_hash_frequency(
    asic_serial,
    frequency_mhz,
    start_chip_id=0,
    chip_num=CHIP_NUM_ALL,
    write_pll_config=True,
    update_rolltime=True,
    debug=False,
):
    pll_config = pll_config_value_for_mhz(frequency_mhz)
    writes = [
        (GLOBAL_SPD, DEFAULT_GLOBAL_SPD_VALUE),
    ]
    if write_pll_config:
        writes.append((PLL0_CFG, pll_config))
    writes.append((PLL0_EN, DEFAULT_PLL0_ENABLE))
    if update_rolltime:
        writes.append((ROLLTIME, rolltime_for_pll_mhz(frequency_mhz)))
    return write_registers(
        asic_serial,
        chip_id=start_chip_id,
        registers=writes,
        chip_num=chip_num,
        debug=debug,
    )


def read_hash_frequency_status(asic_serial, chip_id, debug=False):
    pll_cfg, _ = read_register(asic_serial, chip_id, PLL0_CFG, debug=debug)
    pll_en, _ = read_register(asic_serial, chip_id, PLL0_EN, debug=debug)
    rolltime, _ = read_register(asic_serial, chip_id, ROLLTIME, debug=debug)
    return {
        "chip_id": chip_id,
        "pll0_cfg": pll_cfg,
        "pll0_en": pll_en,
        "pll0_locked": bool(pll_en & PLL_LOCK_BIT),
        "rolltime": rolltime,
    }


def hash_frequency_status_matches(status, frequency_mhz, check_rolltime=True):
    cfg_ok = status["pll0_cfg"] == pll_config_value_for_mhz(frequency_mhz)
    rolltime_ok = (not check_rolltime) or status["rolltime"] == rolltime_for_pll_mhz(frequency_mhz)
    return cfg_ok and status["pll0_locked"] and rolltime_ok


def parse_version_rolling_nonce_buffer(words):
    if len(words) < NONCE_BUFFER_NOTE_WORDS + VERSION_ROLLING_NONCE_COUNT * 3:
        raise ValueError("version rolling nonce buffer needs at least 19 words")

    note = tuple(words[:NONCE_BUFFER_NOTE_WORDS])
    nonces = []
    offset = NONCE_BUFFER_NOTE_WORDS
    for index in range(VERSION_ROLLING_NONCE_COUNT):
        metadata = words[offset]
        nonce = words[offset + 1]
        version = words[offset + 2]
        for name, value in (
            ("metadata", metadata),
            ("nonce", nonce),
            ("version", version),
        ):
            _validate_u32(name, value)
        nonces.append(
            {
                "index": index,
                "valid": bool(metadata & 0x80000000),
                "core_id": (metadata >> 16) & 0x7,
                "ntime_offset": metadata & 0xFFFF,
                "nonce": nonce,
                "version": version,
            }
        )
        offset += 3
    return {"note": note, "nonces": nonces}


def compact_target_from_nbits(nbits):
    compact = byte_swap_u32(nbits)
    exponent = (compact >> 24) & 0xFF
    mantissa = compact & 0x007FFFFF
    if compact & 0x00800000:
        raise ValueError("negative compact targets are not valid for mining work")
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def work_target_value(work_target_h, work_target_l):
    _validate_u32("work_target_h", work_target_h)
    _validate_u32("work_target_l", work_target_l)
    value = (work_target_h << 32) | work_target_l
    if value <= 0:
        raise ValueError("work target must be nonzero")
    return value


def work_per_nonce(work_target_h, work_target_l):
    return (2**96) / work_target_value(work_target_h, work_target_l)


def hashrate_from_nonce_count(nonce_count, elapsed_seconds, work_target_h, work_target_l):
    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be positive")
    if nonce_count < 0:
        raise ValueError("nonce_count must be non-negative")
    return nonce_count * work_per_nonce(work_target_h, work_target_l) / elapsed_seconds


def spdlog_runtime_seconds(timer_count):
    if not 0 <= timer_count <= 0xFFFF:
        raise ValueError("timer_count must fit in 16 bits")
    return (timer_count << 20) / SPDLOG_XCLK_HZ


def spdlog_timer_value(timer_count, enabled=True):
    if not 0 <= timer_count <= 0xFFFF:
        raise ValueError("timer_count must fit in 16 bits")
    return timer_count | (SPDLOG_TIMER_ENABLE if enabled else 0)


def spdlog_timer_count_for_seconds(seconds):
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    return max(1, min(0xFFFF, round(seconds * SPDLOG_XCLK_HZ / (2**20))))


def core_target_leading_zeros(core_target):
    if not 0 <= core_target <= 0xFF:
        raise ValueError("core_target must fit in 8 bits")
    if core_target == 0:
        return 24
    return 24 + ((core_target + 1).bit_length() - 1)


def spdlog_hashrate_hs(pass_count, runtime_seconds, core_target):
    if pass_count < 0:
        raise ValueError("pass_count must be non-negative")
    if runtime_seconds <= 0:
        raise ValueError("runtime_seconds must be positive")
    return (2 ** core_target_leading_zeros(core_target)) * pass_count / runtime_seconds


def spdlog_candidate_hashrate_hs(pass_count, fail_count, runtime_seconds, core_target):
    if fail_count < 0:
        raise ValueError("fail_count must be non-negative")
    return spdlog_hashrate_hs(pass_count + fail_count, runtime_seconds, core_target)


def spdlog_registers(base=SPDLOG_BASE_DEFAULT):
    return {
        "timer": base + SPDLOG_TIMER_OFFSET,
        "rst": base + SPDLOG_RST_OFFSET,
        "pass": base + SPDLOG_PASS_OFFSET,
        "fail": base + SPDLOG_FAIL_OFFSET,
    }


def spdlog_work_cfg_value(core_target=0x00):
    if not 0 <= core_target <= 0xFF:
        raise ValueError("core_target must fit in 8 bits")
    return DEFAULT_WORK_CFG_SPDLOG | core_target


def set_spdlog_work_cfg(asic_serial, chip_id, core_target=0x00, chip_num=0, debug=False):
    updated = spdlog_work_cfg_value(core_target)
    write_register(
        asic_serial,
        chip_id=chip_id,
        register=WORK_CFG,
        value=updated,
        chip_num=chip_num,
        debug=debug,
    )
    return updated


def start_spdlog(asic_serial, chip_id, timer_count, core_target=0x00, base=SPDLOG_BASE_DEFAULT, debug=False):
    registers = spdlog_registers(base=base)
    write_register(
        asic_serial,
        chip_id=chip_id,
        register=registers["timer"],
        value=0x00000000,
        debug=debug,
    )
    write_register(
        asic_serial,
        chip_id=chip_id,
        register=GLOBAL_SPD,
        value=DEFAULT_GLOBAL_SPD_VALUE,
        debug=debug,
    )
    work_cfg = set_spdlog_work_cfg(
        asic_serial,
        chip_id=chip_id,
        core_target=core_target,
        debug=debug,
    )
    write_register(asic_serial, chip_id, registers["rst"], 0x00000001, debug=debug)
    write_register(
        asic_serial,
        chip_id,
        registers["timer"],
        spdlog_timer_value(timer_count, enabled=True),
        debug=debug,
    )
    return {
        "work_cfg": work_cfg,
        "runtime_seconds": spdlog_runtime_seconds(timer_count),
    }


def start_spdlog_broadcast(
    asic_serial,
    start_chip_id,
    chip_num,
    timer_count,
    core_target=0x00,
    base=SPDLOG_BASE_DEFAULT,
    debug=False,
):
    registers = spdlog_registers(base=base)
    write_register(
        asic_serial,
        chip_id=start_chip_id,
        register=GLOBAL_SPD,
        value=DEFAULT_GLOBAL_SPD_VALUE,
        chip_num=chip_num,
        debug=debug,
    )
    work_cfg = set_spdlog_work_cfg(
        asic_serial,
        chip_id=start_chip_id,
        core_target=core_target,
        chip_num=chip_num,
        debug=debug,
    )
    write_register(
        asic_serial,
        start_chip_id,
        registers["rst"],
        0x00000001,
        chip_num=chip_num,
        debug=debug,
    )
    write_register(
        asic_serial,
        start_chip_id,
        registers["timer"],
        spdlog_timer_value(timer_count, enabled=True),
        chip_num=chip_num,
        debug=debug,
    )
    return {
        "work_cfg": work_cfg,
        "runtime_seconds": spdlog_runtime_seconds(timer_count),
    }


def read_spdlog(asic_serial, chip_id, timer_count=None, core_target=0x00, base=SPDLOG_BASE_DEFAULT, debug=False):
    registers = spdlog_registers(base=base)
    work_cfg, _ = read_register(asic_serial, chip_id, WORK_CFG, debug=debug)
    target_l, _ = read_register(asic_serial, chip_id, WORK_TARGET_L, debug=debug)
    target_h, _ = read_register(asic_serial, chip_id, WORK_TARGET_H, debug=debug)
    rolltime, _ = read_register(asic_serial, chip_id, ROLLTIME, debug=debug)
    pll_en, _ = read_register(asic_serial, chip_id, PLL0_EN, debug=debug)
    timer, _ = read_register(asic_serial, chip_id, registers["timer"], debug=debug)
    passed, _ = read_register(asic_serial, chip_id, registers["pass"], debug=debug)
    failed, _ = read_register(asic_serial, chip_id, registers["fail"], debug=debug)
    runtime = spdlog_runtime_seconds(timer_count if timer_count is not None else timer & 0xFFFF)
    return {
        "work_cfg": work_cfg,
        "target_l": target_l,
        "target_h": target_h,
        "rolltime": rolltime,
        "pll0_en": pll_en,
        "pll0_locked": bool(pll_en & PLL_LOCK_BIT),
        "timer": timer,
        "pass": passed,
        "fail": failed,
        "runtime_seconds": runtime,
        "hashrate_hs": spdlog_hashrate_hs(passed, runtime, core_target),
        "candidate_hashrate_hs": spdlog_candidate_hashrate_hs(passed, failed, runtime, core_target),
        "leading_zeros": core_target_leading_zeros(core_target),
    }


def reconstruct_version_rolling_header(work, nonce):
    version = byte_swap_u32(nonce["version"])
    ntime = byte_swap_u32(byte_swap_u32(work.ntime) + nonce["ntime_offset"])
    return b"".join(
        [
            version.to_bytes(4, "big"),
            work.previous_hash,
            work.merkle_root,
            ntime.to_bytes(4, "big"),
            work.nbits.to_bytes(4, "big"),
            nonce["nonce"].to_bytes(4, "big"),
        ]
    )


def double_sha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def validate_version_rolling_nonce(work, nonce):
    header = reconstruct_version_rolling_header(work, nonce)
    digest = double_sha256(header)
    display_hash = digest[::-1]
    target = compact_target_from_nbits(work.nbits)
    hash_int = int.from_bytes(display_hash, "big")
    return {
        "header": header,
        "header_hex": header.hex().upper(),
        "hash": display_hash,
        "hash_hex": display_hash.hex().upper(),
        "target": target,
        "target_hex": f"{target:064X}",
        "meets_target": hash_int <= target,
        "version": int.from_bytes(header[0:4], "big"),
        "ntime": int.from_bytes(header[68:72], "big"),
        "nonce": int.from_bytes(header[76:80], "big"),
    }


def validate_version_rolling_nonces(work, parsed_nonce_buffer):
    results = []
    for nonce in parsed_nonce_buffer["nonces"]:
        result = {"nonce_record": nonce, "valid": nonce["valid"]}
        if nonce["valid"]:
            result.update(validate_version_rolling_nonce(work, nonce))
        results.append(result)
    return results


def write_registers(asic_serial, chip_id, registers, chip_num=0, debug=False):
    responses = []
    for register, value in registers:
        responses.append(
            write_register(
                asic_serial,
                chip_id=chip_id,
                register=register,
                value=value,
                chip_num=chip_num,
                debug=debug,
            )
        )
    return responses


def configure_version_rolling_mining(
    asic_serial,
    start_chip_id=0,
    chip_num=CHIP_NUM_ALL,
    rolltime=DEFAULT_ROLLTIME_200MHZ,
    debug=False,
):
    registers = version_rolling_mining_config_registers(rolltime=rolltime)
    return write_registers(
        asic_serial,
        chip_id=start_chip_id,
        registers=registers,
        chip_num=chip_num,
        debug=debug,
    )


def write_mining_target(asic_serial, work, start_chip_id=0, chip_num=CHIP_NUM_ALL, debug=False):
    return write_registers(
        asic_serial,
        chip_id=start_chip_id,
        registers=[
            (WORK_TARGET_L, work.work_target_l),
            (WORK_TARGET_H, work.work_target_h),
        ],
        chip_num=chip_num,
        debug=debug,
    )


def write_v_base(asic_serial, work, start_chip_id=0, chip_num=CHIP_NUM_ALL, debug=False):
    return write_register(
        asic_serial,
        chip_id=start_chip_id,
        register=V_BASE,
        value=v_base_value_for_work(work),
        chip_num=chip_num,
        debug=debug,
    )


def write_v_work(asic_serial, work, start_chip_id=0, chip_num=CHIP_NUM_ALL, debug=False):
    return write_registers(
        asic_serial,
        chip_id=start_chip_id,
        registers=build_v_work_registers(work),
        chip_num=chip_num,
        debug=debug,
    )


def start_app_note_version_rolling_mining(
    asic_serial,
    start_chip_id=0,
    chip_num=CHIP_NUM_ALL,
    work=None,
    rolltime=DEFAULT_ROLLTIME_200MHZ,
    debug=False,
):
    if work is None:
        work = app_note_version_rolling_work()
    configure_version_rolling_mining(
        asic_serial,
        start_chip_id=start_chip_id,
        chip_num=chip_num,
        rolltime=rolltime,
        debug=debug,
    )
    write_mining_target(
        asic_serial,
        work,
        start_chip_id=start_chip_id,
        chip_num=chip_num,
        debug=debug,
    )
    write_v_base(
        asic_serial,
        work,
        start_chip_id=start_chip_id,
        chip_num=chip_num,
        debug=debug,
    )
    write_v_work(
        asic_serial,
        work,
        start_chip_id=start_chip_id,
        chip_num=chip_num,
        debug=debug,
    )
    return work


def start_app_note_version_rolling_mining_distinct_ranges(
    asic_serial,
    first_chip_id=0,
    chip_count=4,
    version_mask_bits=DEFAULT_VERSION_MASK_BITS,
    work=None,
    rolltime=DEFAULT_ROLLTIME_200MHZ,
    debug=False,
):
    if work is None:
        work = app_note_version_rolling_work()
    configure_version_rolling_mining(
        asic_serial,
        start_chip_id=first_chip_id,
        chip_num=CHIP_NUM_ALL,
        rolltime=rolltime,
        debug=debug,
    )
    write_mining_target(
        asic_serial,
        work,
        start_chip_id=first_chip_id,
        chip_num=CHIP_NUM_ALL,
        debug=debug,
    )
    for chip_id, v_base in v_base_values_for_chip_range(
        work,
        first_chip_id=first_chip_id,
        chip_count=chip_count,
        version_mask_bits=version_mask_bits,
    ):
        write_register(
            asic_serial,
            chip_id=chip_id,
            register=V_BASE,
            value=v_base,
            chip_num=0,
            debug=debug,
        )
    write_v_work(
        asic_serial,
        work,
        start_chip_id=first_chip_id,
        chip_num=CHIP_NUM_ALL,
        debug=debug,
    )
    return work


def read_version_rolling_nonce_buffer(asic_serial, chip_id, debug=False):
    words = []
    word_count = NONCE_BUFFER_NOTE_WORDS + VERSION_ROLLING_NONCE_COUNT * 3
    for index in range(word_count):
        word, _ = read_register(
            asic_serial,
            chip_id=chip_id,
            register=NONCE_BUFFER + index * 4,
            debug=debug,
        )
        words.append(word)
    return parse_version_rolling_nonce_buffer(words)


def update_nonce_buffer(asic_serial, start_chip_id=0, chip_num=CHIP_NUM_ALL, debug=False):
    return write_register(
        asic_serial,
        chip_id=start_chip_id,
        register=NONCE_UPDATE,
        value=0x00000001,
        chip_num=chip_num,
        debug=debug,
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


def build_write_packet(chip_id, register, values, chip_num=0):
    if not values:
        raise ValueError("write packet needs at least one data word")

    header = build_header(chip_id=chip_id, chip_num=chip_num, mode=MODE_WRITE, data_length=len(values))
    fields = [
        encode_field(header, is_tail=False),
        encode_field(register, is_tail=False),
    ]
    for index, value in enumerate(values):
        fields.append(encode_field(value, is_tail=index == len(values) - 1))
    return b"".join(fields)


def build_read_packet(chip_id, register, data_length=1):
    header = build_header(chip_id=chip_id, chip_num=0, mode=MODE_READ, data_length=data_length)
    return b"".join(
        [
            encode_field(header, is_tail=False),
            encode_field(register, is_tail=False),
            encode_field(0x00000000, is_tail=True),
        ]
    )


def init_id_from_data_word(word):
    return (word >> 24) & 0xFF


def reverse_bits32(word):
    reversed_word = 0
    for _ in range(32):
        reversed_word = (reversed_word << 1) | (word & 1)
        word >>= 1
    return reversed_word


def datasheet_chain_count_from_data_word(word):
    return reverse_bits32(word)


def header_mode(header):
    return (header >> 8) & 0x0F


def header_chip_id(header):
    return (header >> 16) & 0xFF


def header_data_length(header):
    return header & 0xFF


def parse_init_response(response):
    if len(response) < 15:
        return None

    for offset in range(0, len(response) - 14):
        fields = [decode_field(response[offset + idx : offset + idx + 5]) for idx in (0, 5, 10)]
        header = fields[0]["word"]
        if (header >> 24) == START_FLAG and header_mode(header) == MODE_INIT:
            data_word = fields[2]["word"]
            next_chip_id = init_id_from_data_word(data_word)
            return {
                "offset": offset,
                "fields": fields,
                "data_word": data_word,
                "next_chip_id": next_chip_id,
                "datasheet_chain_count": datasheet_chain_count_from_data_word(data_word),
            }
    return None


def parse_read_response(response, expected_chip_id=None, expected_register=None, expected_length=1):
    field_count = 3 + expected_length
    packet_len = field_count * 5
    if len(response) < packet_len:
        return None

    for offset in range(0, len(response) - packet_len + 1):
        fields = [
            decode_field(response[offset + index * 5 : offset + (index + 1) * 5])
            for index in range(field_count)
        ]
        header = fields[0]["word"]
        register = fields[1]["word"]
        meta = fields[2]["word"]
        chip_id = (meta >> 8) & 0xFF
        data_length = meta & 0xFF

        if (header >> 24) != START_FLAG:
            continue
        if header_mode(header) != MODE_READ:
            continue
        if (meta >> 16) != 0xFFAA:
            continue
        if expected_chip_id is not None and chip_id != expected_chip_id:
            continue
        if expected_register is not None and register != expected_register:
            continue
        if data_length != expected_length:
            continue

        return {
            "offset": offset,
            "fields": fields,
            "chip_id": chip_id,
            "register": register,
            "data": [field["word"] for field in fields[3:]],
        }
    return None


def drain_serial(asic_serial):
    waiting = getattr(asic_serial, "in_waiting", 0)
    if waiting:
        asic_serial.read(waiting)


ULINK_FIELD_BYTES = 5
ULINK_COMMAND_FIELDS = 3
ULINK_READ_META_FIELDS = 3
ULINK_POLL_INTERVAL = 0.001
ULINK_RESPONSE_DELAY = 0.002


def transact(asic_serial, packet, read_size, response_delay=ULINK_RESPONSE_DELAY, debug=False):
    drain_serial(asic_serial)
    if debug:
        print(f"mc3 tx: [{pretty_hex(packet)}]")
    bytes_written = asic_serial.write(packet)
    asic_serial.flush()
    time.sleep(response_delay)
    response = asic_serial.read(max(read_size, getattr(asic_serial, "in_waiting", 0)))
    if debug:
        print(f"mc3 rx ({len(response)} after {bytes_written} tx): [{pretty_hex(response)}]")
    return response


def write_register(asic_serial, chip_id, register, value, chip_num=0, debug=False):
    packet = build_write_packet(chip_id=chip_id, register=register, values=[value], chip_num=chip_num)
    return transact(asic_serial, packet, read_size=len(packet), debug=debug)


def read_register(asic_serial, chip_id, register, debug=False):
    packet = build_read_packet(chip_id=chip_id, register=register, data_length=1)
    response = transact(
        asic_serial,
        packet,
        read_size=(ULINK_READ_META_FIELDS + 1) * ULINK_FIELD_BYTES,
        debug=debug,
    )
    parsed = parse_read_response(
        response,
        expected_chip_id=chip_id,
        expected_register=register,
        expected_length=1,
    )
    if not parsed:
        raise RuntimeError(f"no valid read response from chip {chip_id} register 0x{register:08X}")
    return parsed["data"][0], parsed


def wait_register(asic_serial, chip_id, register, expected, timeout=0.25, debug=False):
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value, _ = read_register(asic_serial, chip_id, register, debug=debug)
        if last_value == expected:
            return last_value
        time.sleep(ULINK_POLL_INTERVAL)
    raise TimeoutError(
        f"chip {chip_id} register 0x{register:08X} stayed 0x{last_value:08X}, expected 0x{expected:08X}"
    )


def temperature_c_from_dout(raw, resolution=THERMAL_RESOLUTION_BITS):
    return 675.61 * ((raw - (2 ** (11 - resolution))) / (2**12)) - 288.82


def voltage_v_from_dout(raw, resolution=VOLTAGE_RESOLUTION_BITS):
    scale = (7 * VOLTAGE_VREF) / 15
    return scale * (((6 * raw) / (2**14)) - (3 / (2**resolution)) - 1)


def setup_thermal_sensor(asic_serial, start_chip_id=0, debug=False):
    write_register(asic_serial, start_chip_id, THERMAL_SDIF_ENABLE, 0x00000000, chip_num=CHIP_NUM_ALL, debug=debug)
    write_register(asic_serial, start_chip_id, THERMAL_CLOCK, 0x01010000, chip_num=CHIP_NUM_ALL, debug=debug)
    write_register(asic_serial, start_chip_id, THERMAL_COMMAND, 0x89000000, chip_num=CHIP_NUM_ALL, debug=debug)
    write_register(asic_serial, start_chip_id, THERMAL_COMMAND, 0x8D000200, chip_num=CHIP_NUM_ALL, debug=debug)
    wait_register(asic_serial, start_chip_id, THERMAL_STATUS, 0x00000000, debug=debug)


def trigger_thermal_conversion(asic_serial, start_chip_id=0, debug=False):
    write_register(asic_serial, start_chip_id, THERMAL_COMMAND, 0x88000105, chip_num=CHIP_NUM_ALL, debug=debug)
    wait_register(asic_serial, start_chip_id, THERMAL_DONE, 0x00000001, timeout=0.5, debug=debug)


def read_chip_temperature(asic_serial, chip_id, debug=False):
    raw, _ = read_register(asic_serial, chip_id, THERMAL_DOUT, debug=debug)
    return raw, temperature_c_from_dout(raw)


def setup_voltage_sensors(asic_serial, channels, start_chip_id=0, voltage_clock=VOLTAGE_CLOCK_DEFAULT, debug=False):
    for channel in channels:
        if not 0 <= channel <= 15:
            raise ValueError("voltage channel must be 0-15")

    channel_mask = 0
    for channel in channels:
        channel_mask |= 1 << channel

    write_register(asic_serial, start_chip_id, VOLTAGE_SDIF_ENABLE, 0x00000000, chip_num=CHIP_NUM_ALL, debug=debug)
    write_register(asic_serial, start_chip_id, VOLTAGE_CLOCK, voltage_clock, chip_num=CHIP_NUM_ALL, debug=debug)
    write_register(asic_serial, start_chip_id, VOLTAGE_COMMAND, 0x89000000, chip_num=CHIP_NUM_ALL, debug=debug)
    write_register(asic_serial, start_chip_id, VOLTAGE_COMMAND, 0x8D000040, chip_num=CHIP_NUM_ALL, debug=debug)
    wait_register(asic_serial, start_chip_id, VOLTAGE_STATUS, 0x00000000, debug=debug)
    write_register(asic_serial, start_chip_id, VOLTAGE_COMMAND, 0x8C100000 | channel_mask, chip_num=CHIP_NUM_ALL, debug=debug)
    wait_register(asic_serial, start_chip_id, VOLTAGE_STATUS, 0x00000000, debug=debug)


def setup_voltage_sensor(asic_serial, channel=0, start_chip_id=0, voltage_clock=VOLTAGE_CLOCK_DEFAULT, debug=False):
    setup_voltage_sensors(
        asic_serial,
        [channel],
        start_chip_id=start_chip_id,
        voltage_clock=voltage_clock,
        debug=debug,
    )


def trigger_voltage_conversion(asic_serial, start_chip_id=0, debug=False):
    write_register(asic_serial, start_chip_id, VOLTAGE_COMMAND, 0x88000505, chip_num=CHIP_NUM_ALL, debug=debug)
    wait_register(asic_serial, start_chip_id, VOLTAGE_DONE, 0x00000001, timeout=0.5, debug=debug)


def read_chip_voltage(asic_serial, chip_id, channel=0, debug=False):
    if not 0 <= channel <= 15:
        raise ValueError("voltage channel must be 0-15")

    raw, _ = read_register(asic_serial, chip_id, VOLTAGE_DOUT_REGISTERS[channel], debug=debug)
    return raw, voltage_v_from_dout(raw)


def scaled_voltage_for_rail(sensor_volts, scale):
    return sensor_volts * scale


def rail_summary_channels(rails=VOLTAGE_RAIL_SUMMARY):
    channels = []
    for _, rail_channels, _ in rails:
        for channel in rail_channels:
            if channel not in channels:
                channels.append(channel)
    return tuple(channels)


def mc3_voltage_temp_rail_summary(
    asic_serial,
    first_chip_id=0,
    chip_count=4,
    voltage_clock=VOLTAGE_CLOCK_DEFAULT,
    debug=False,
):
    chip_ids = tuple(range(first_chip_id, first_chip_id + chip_count))
    channels = rail_summary_channels()

    print("Configuring thermal sensors on all MC3 chips...")
    setup_thermal_sensor(asic_serial, start_chip_id=first_chip_id, debug=debug)
    trigger_thermal_conversion(asic_serial, start_chip_id=first_chip_id, debug=debug)

    temperatures = {}
    for chip_id in chip_ids:
        _, temp_c = read_chip_temperature(asic_serial, chip_id, debug=debug)
        temperatures[chip_id] = temp_c

    voltage_by_chip = {chip_id: {} for chip_id in chip_ids}
    print("Configuring voltage sensors for rail summary...")
    print(f"Voltage sensor clock register: 0x{voltage_clock:08X}")
    for channel in channels:
        setup_voltage_sensor(
            asic_serial,
            channel=channel,
            start_chip_id=first_chip_id,
            voltage_clock=voltage_clock,
            debug=debug,
        )
        trigger_voltage_conversion(asic_serial, start_chip_id=first_chip_id, debug=debug)
        for chip_id in chip_ids:
            _, volts = read_chip_voltage(asic_serial, chip_id, channel=channel, debug=debug)
            voltage_by_chip[chip_id][channel] = volts

    results = []
    print("")
    print("Chip  Temp C  VDDIO12   VDDH  VDDI1  VDDI2  VDDI3    VDD")
    print("----  ------  -------  -----  -----  -----  -----  -----")
    for chip_id in chip_ids:
        row = {
            "chip_id": chip_id,
            "temperature_c": temperatures[chip_id],
            "rails": {},
        }
        cells = []
        for rail_name, rail_channels, scale in VOLTAGE_RAIL_SUMMARY:
            sensor_values = [voltage_by_chip[chip_id][channel] for channel in rail_channels]
            sensor_avg = sum(sensor_values) / len(sensor_values)
            rail_volts = scaled_voltage_for_rail(sensor_avg, scale)
            row["rails"][rail_name] = {
                "voltage_v": rail_volts,
                "sensor_voltage_v": sensor_avg,
                "channels": rail_channels,
                "scale": scale,
            }
            cells.append(f"{rail_volts:>7.3f}" if rail_name == "VDDIO12" else f"{rail_volts:>5.3f}")
        results.append(row)
        print(f"{chip_id:>4}  {temperatures[chip_id]:>6.2f}  " + "  ".join(cells))

    print("")
    print("Note: VDDIO12 and VDD are shown after 2x prescaler correction.")
    return results


def voltage_matrix_test(asic_serial, first_chip_id=0, chip_count=4, voltage_clock=VOLTAGE_CLOCK_DEFAULT, debug=False):
    chip_ids = range(first_chip_id, first_chip_id + chip_count)
    channels = ALL_VOLTAGE_CHANNELS
    results = []
    diagonal = {}

    print("Voltage matrix diagnostic: select one channel, then read all DOUT registers.")
    print(f"Voltage sensor clock register: 0x{voltage_clock:08X}")
    print("Raw 0x0AAB is approximately 0 V with the datasheet conversion.")
    header = "Sel  Chip  " + "  ".join(f"D{channel:02d}" for channel in channels)
    print(header)
    print("-" * len(header))

    for selected_channel in channels:
        setup_voltage_sensor(
            asic_serial,
            channel=selected_channel,
            start_chip_id=first_chip_id,
            voltage_clock=voltage_clock,
            debug=debug,
        )
        trigger_voltage_conversion(asic_serial, start_chip_id=first_chip_id, debug=debug)

        for chip_id in chip_ids:
            row = []
            for dout_channel in channels:
                raw, volts = read_chip_voltage(
                    asic_serial,
                    chip_id,
                    channel=dout_channel,
                    debug=debug,
                )
                row.append((dout_channel, raw, volts))
            results.append(
                {
                    "selected_channel": selected_channel,
                    "chip_id": chip_id,
                    "dout": row,
                }
            )
            for dout_channel, raw, volts in row:
                if dout_channel == selected_channel:
                    diagonal.setdefault(selected_channel, []).append((chip_id, raw, volts))
            raw_cells = "  ".join(f"{raw:04X}" for _, raw, _ in row)
            print(f"{selected_channel:>3}  {chip_id:>4}  {raw_cells}")

    print("")
    print("Selected-channel summary")
    print("Vch  Supply   DOUT addr    " + "  ".join(f"chip{chip_id}" for chip_id in chip_ids))
    print("---  -------  ----------  " + "  ".join("----------" for _ in chip_ids))
    for channel in channels:
        cells = []
        for _, raw, volts in diagonal.get(channel, []):
            cells.append(f"{volts:6.3f}V")
        print(
            f"{channel:>3}  {VOLTAGE_CHANNELS[channel]:<7}  "
            f"0x{VOLTAGE_DOUT_REGISTERS[channel]:08X}  "
            + "  ".join(cells)
        )

    return results


def sensor_read_test(
    asic_serial,
    first_chip_id=0,
    chip_count=4,
    voltage_channel=0,
    voltage_clock=VOLTAGE_CLOCK_DEFAULT,
    debug=False,
):
    chip_ids = range(first_chip_id, first_chip_id + chip_count)
    voltage_channels = (
        ALL_VOLTAGE_CHANNELS if voltage_channel < 0 else (voltage_channel,)
    )

    print("Configuring thermal sensors on all MC3 chips...")
    setup_thermal_sensor(asic_serial, start_chip_id=first_chip_id, debug=debug)
    trigger_thermal_conversion(asic_serial, start_chip_id=first_chip_id, debug=debug)

    temperatures = {}
    for chip_id in chip_ids:
        temp_raw, temp_c = read_chip_temperature(asic_serial, chip_id, debug=debug)
        temperatures[chip_id] = (temp_raw, temp_c)

    channel_label = (
        "all voltage channels, one conversion per channel"
        if voltage_channel < 0
        else f"voltage sensor channel {voltage_channel}"
    )
    print(f"Configuring {channel_label} on all MC3 chips...")
    print(f"Voltage sensor clock register: 0x{voltage_clock:08X}")

    print("")
    print("Chip  Temp raw    Temp C  Vch  Supply   DOUT addr    Volt raw    Sensor V")
    print("----  --------  --------  ---  -------  ----------  ----------  --------")
    results = []
    for channel in voltage_channels:
        setup_voltage_sensor(
            asic_serial,
            channel=channel,
            start_chip_id=first_chip_id,
            voltage_clock=voltage_clock,
            debug=debug,
        )
        trigger_voltage_conversion(asic_serial, start_chip_id=first_chip_id, debug=debug)

        for chip_id in chip_ids:
            temp_raw, temp_c = temperatures[chip_id]
            volt_raw, volts = read_chip_voltage(asic_serial, chip_id, channel=channel, debug=debug)
            results.append(
                {
                    "chip_id": chip_id,
                    "temperature_raw": temp_raw,
                    "temperature_c": temp_c,
                    "voltage_channel": channel,
                    "voltage_name": VOLTAGE_CHANNELS[channel],
                    "voltage_register": VOLTAGE_DOUT_REGISTERS[channel],
                    "voltage_raw": volt_raw,
                    "voltage_v": volts,
                }
            )
            print(
                f"{chip_id:>4}  0x{temp_raw:06X}  {temp_c:8.2f}  "
                f"{channel:>3}  {VOLTAGE_CHANNELS[channel]:<7}  "
                f"0x{VOLTAGE_DOUT_REGISTERS[channel]:08X}  "
                f"0x{volt_raw:08X}  {volts:8.4f}"
            )
    return results


def reset_chain(control_serial, debug=False):
    print("Resetting MC3 chain...")
    bitaxeraw.gpio_set(control_serial, 0xAB, bitaxeraw.GPIO_ASIC_RST, bitaxeraw.GPIO_LOW, debug=debug)
    time.sleep(0.1)
    bitaxeraw.gpio_set(control_serial, 0xAB, bitaxeraw.GPIO_ASIC_RST, bitaxeraw.GPIO_HIGH, debug=debug)
    time.sleep(0.1)


def enumerate_chain(control_serial, asic_serial, first_chip_id=0, expected_chain_chips=4, debug=False):
    reset_chain(control_serial, debug=debug)
    asic_serial.reset_input_buffer()
    asic_serial.reset_output_buffer()

    # Datasheet requires at least N * 50 logic-zero bits before INIT to flush ULink buffers.
    flush_zero_bits = max(1, expected_chain_chips) * 50
    flush_zero_bytes = max(32, (flush_zero_bits + 7) // 8)
    print(f"Flushing ULink with {flush_zero_bytes} zero byte(s) before INIT...")
    asic_serial.write(b"\x00" * flush_zero_bytes)
    asic_serial.flush()
    time.sleep(0.05)

    packet = build_init_packet(first_chip_id=first_chip_id)
    print(f"Sending MC3 ULink INIT packet on {asic_serial.port} ({len(packet)} bytes)...")
    print(f"mc3 init tx: [{pretty_hex(packet)}]")

    bytes_written = asic_serial.write(packet)
    trailing_zero_bytes = 8
    print(f"Sending {trailing_zero_bytes} trailing zero byte(s) after INIT...")
    bytes_written += asic_serial.write(b"\x00" * trailing_zero_bytes)
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
        ulink_count = parsed["next_chip_id"] - first_chip_id
        datasheet_count = parsed["datasheet_chain_count"]
        print(f"INIT data word: 0x{parsed['data_word']:08X}")
        print(f"ULink next-chip-id count: {ulink_count}")
        print(f"Datasheet bit-reversed count interpretation: {datasheet_count}")
        if datasheet_count != ulink_count:
            print("Note: ULink app note and datasheet section 6 use different INIT count encodings.")
        print(f"MC3 chain count: {ulink_count}")
    else:
        print("No valid ULink INIT response found.")

    return response
