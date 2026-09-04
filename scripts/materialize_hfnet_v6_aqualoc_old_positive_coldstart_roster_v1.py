#!/usr/bin/env python3
"""Prepare one exact-window AQUALOC HFNet cold-start input, and nothing else.

The five profiles are the historical learned+KLT versus KLT positive windows.
Each feed is exactly the historical score window, so the external system and
the historical frontends see the same image history.  The implementation
streams canonical PNG bytes from the pinned raw archive, shifts only IMU
timestamps into the camera clock, publishes atomically, and never starts a
scientific process.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_phase_f_h03_1800_3600_v1 as core


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-aqualoc-old-positive-coldstart-input-materialization-v1"
)
ROSTER_SCHEMA = "aqua-fe-hfnet-v6-aqualoc-old-positive-coldstart-roster-v1"
CORE_PATH = ROOT / "scripts/materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py"
CORE_SIZE = 38_774
CORE_SHA256 = "9146602be29e6faee2d13c91e25b01d2bc4081c11bbf419787128822275e584d"
DEFAULT_ROSTER = ROOT / "papers/hfnet_v6_aqualoc_old_positive_coldstart_roster_v1.json"
ROSTER_SIZE = 2_064
ROSTER_SHA256 = "92317c930443c140ec9b6a8fe61ac4c0b97d9572eec07c4833f0ea4d0b06821d"
DEFAULT_CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_aqualoc_archaeology_coldstart_roster_v1.yaml"
)
CONFIG_SIZE = 1_864
CONFIG_SHA256 = "d0cbe8e575c2b8234d1d617baabc27560118625398fd588ec83c3e93b4ce6177"
SOURCE_DIRECTORY = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences"
)
OUTPUT_NAMESPACE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/"
    "hfnet_v6_aqualoc_old_positive_coldstart_roster_v1"
)
IMU_SHIFT_NS = 53_694_112

FilePin = core.FilePin
MaterializationContract = core.MaterializationContract
ContractError = core.ContractError


@dataclass(frozen=True)
class Profile:
    key: str
    sequence_number: int
    sequence_id: str
    start: int
    end: int
    source_size: int
    source_sha256: str
    gzip_crc32: str
    gzip_isize: int
    image_csv_size: int
    image_csv_sha256: str
    image_csv_crc32: str
    imu_csv_size: int
    imu_csv_sha256: str
    imu_csv_crc32: str
    source_camera_count: int
    source_imu_count: int
    camera_first_ns: int
    camera_last_ns: int
    imu_first_index: int
    imu_last_index: int
    imu_first_raw_ns: int
    imu_last_raw_ns: int
    imu_output_endpoints: Sequence[int]
    image_total_bytes: int
    source_inventory_sha256: str
    source_inventory_crc32: str
    renamed_inventory_sha256: str
    renamed_inventory_crc32: str
    times_pin: Sequence[Any]
    camera_csv_pin: Sequence[Any]
    imu_output_pin: Sequence[Any]
    payload_sha256: str
    payload_crc32: str
    legacy_times_path: Optional[str] = None
    legacy_full_bag_path: Optional[str] = None
    legacy_full_bag_size: Optional[int] = None
    legacy_full_bag_sha256: Optional[str] = None

    @property
    def camera_count(self) -> int:
        return self.end - self.start + 1

    @property
    def source_archive(self) -> Path:
        return SOURCE_DIRECTORY / f"archaeo_sequence_{self.sequence_number}_raw_data.tar.gz"

    @property
    def output_root(self) -> Path:
        return OUTPUT_NAMESPACE / self.key

    @property
    def image_csv_member(self) -> str:
        return f"raw_data/img_sequence_{self.sequence_number}.csv"

    @property
    def imu_csv_member(self) -> str:
        return f"raw_data/imu_sequence_{self.sequence_number}.csv"

    @property
    def image_member_prefix(self) -> str:
        return f"raw_data/images_sequence_{self.sequence_number}/"


def _profile(**values: Any) -> Profile:
    return Profile(**values)


PROFILES: Dict[str, Profile] = {
    "a02_7600_8000": _profile(
        key="a02_7600_8000", sequence_number=2, sequence_id="A02", start=7600, end=8000,
        source_size=2_195_786_266, source_sha256="8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69",
        gzip_crc32="daa06f87", gzip_isize=2_223_994_880,
        image_csv_size=323_558, image_csv_sha256="a1781919532af0e1c7babe2a2676fd7cf7c112a7f4070da8ed868757eb67f05c", image_csv_crc32="2aa8333e",
        imu_csv_size=10_119_433, imu_csv_sha256="068db1d6eabba9b19bb3df4a922e5ff22b3f8120c6255896450a6d7adf34393c", imu_csv_crc32="6e3c8e19",
        source_camera_count=8_987, source_imu_count=89_795,
        camera_first_ns=1_542_829_171_674_622_016, camera_last_ns=1_542_829_191_671_578_400,
        imu_first_index=75_927, imu_last_index=79_925,
        imu_first_raw_ns=1_542_829_171_619_504_800, imu_last_raw_ns=1_542_829_191_623_182_272,
        imu_output_endpoints=(1_542_829_171_673_198_912, 1_542_829_171_678_482_272, 1_542_829_191_671_509_984, 1_542_829_191_676_876_384),
        image_total_bytes=81_611_163,
        source_inventory_sha256="faa5bb1f0bf492de13351f6d97f888af0b39a804f8760d347821edfbf25b802d", source_inventory_crc32="213cf717",
        renamed_inventory_sha256="69887e0152fae9009f1b790576da0e2eef5baa375768fbfa769cfa6787fbb5da", renamed_inventory_crc32="db23636f",
        times_pin=(8_020, "5a8538fbae093a7e5e0cd096460046048fd30c529823cde8d885bea36a213546", "ffa43e9c"),
        camera_csv_pin=(17_669, "c7ef66c5232a39d843302429db9261757eb2a8db5adee43436101c176fa11e75", "94867e79"),
        imu_output_pin=(446_529, "77915c62223b041f68454fc8a978ff4c5cac43b32cc7681f654311aeff29d0da", "b2718ad9"),
        payload_sha256="3fe6850c3ac50886c8388ffd83a1721256869b1855d73721b8859cacd449433c", payload_crc32="9d965c23",
        legacy_times_path="/mnt/data/AQUA-FE_WS/orbslam3_validation/aqualoc_a02_7600_8000/dataset/cam0_times.txt",
        legacy_full_bag_path="/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a02_7600_8000_low_grid_rejected_rich_visible_motion_count/features.bag",
        legacy_full_bag_size=6_112_322,
        legacy_full_bag_sha256="b1a8490ad161d81b4e958d5dfc1837353e3a911920e5c8d2633f3e199b798452",
    ),
    "a05_3300_3700": _profile(
        key="a05_3300_3700", sequence_number=5, sequence_id="A05", start=3300, end=3700,
        source_size=866_604_152, source_sha256="49fc60a27a2da30ab3e3a883badafd43b579406a1fad10de632e175ad18be52c",
        gzip_crc32="94fd6d95", gzip_isize=879_257_600,
        image_csv_size=143_414, image_csv_sha256="a63ad0fd91cb268038e4dc9a6e478166d7b0c2f9bace636926e59ac1ed8a8980", image_csv_crc32="79fa2f29",
        imu_csv_size=4_451_826, imu_csv_sha256="ff069b4df9d6fa4953c0f86fa85d32e767441d21904c19c20c2dc2bc4e8c2c01", imu_csv_crc32="ee1052d8",
        source_camera_count=3_983, source_imu_count=39_796,
        camera_first_ns=1_455_214_343_539_451_680, camera_last_ns=1_455_214_363_536_846_272,
        imu_first_index=32_967, imu_last_index=36_964,
        imu_first_raw_ns=1_455_214_343_484_801_952, imu_last_raw_ns=1_455_214_363_483_388_320,
        imu_output_endpoints=(1_455_214_343_538_496_064, 1_455_214_343_543_961_056, 1_455_214_363_534_102_112, 1_455_214_363_537_082_432),
        image_total_bytes=83_758_704,
        source_inventory_sha256="701b6716e7219a64ae32d7e347074fa36231aed15abdd6da20fcfeb0f70c08aa", source_inventory_crc32="f150366e",
        renamed_inventory_sha256="d3ab60a61a2299c4d9e31061839ad846e7d753e13ceff29e4297cf43b3e746fa", renamed_inventory_crc32="95889bb1",
        times_pin=(8_020, "6c78c8da96914e2345f8ecc87f01a87e1176b09acdca69058c4f3b2504f79dea", "6dcb832d"),
        camera_csv_pin=(17_669, "a1f349b1695af73d596146073becb35258d3f1a7a74a7e7e533c91addb1dcb14", "8732616f"),
        imu_output_pin=(447_051, "551f31e6f4f268f4f1ff42b631b37574a5d59ab35bcbc37b22ea74ba8dc0c16e", "83cbb5f1"),
        payload_sha256="a2c402068aec6a0f05d8c495bef09da4f3888a38870d062e7674ab9fcdf3f1cd", payload_crc32="6cdcd36d",
        legacy_full_bag_path="/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a05_3300_3700_degraded_early_dense_visible_motion_count/features.bag",
        legacy_full_bag_size=6_107_455,
        legacy_full_bag_sha256="7047ec08638d043d619f8c18262d26a5171f2fe678845ab148aaf3d598d81d69",
    ),
    "a07_10800_11200": _profile(
        key="a07_10800_11200", sequence_number=7, sequence_id="A07", start=10800, end=11200,
        source_size=2_792_940_805, source_sha256="f201abbe0b5271695b80a4009883e1a588bd4a0057f2a49777649c1f97c5032c",
        gzip_crc32="d3ae93a3", gzip_isize=2_824_642_560,
        image_csv_size=409_598, image_csv_sha256="e0b5c91f17c5a1b9230c68f7a9d20e7cc60cae12cc2d32e2c5682db274b539c3", image_csv_crc32="d8cdd432",
        imu_csv_size=12_692_960, imu_csv_sha256="4065d8f24946126c2398af4bd3382f4977f0f97182fd39dd4e9bb01a07245b22", imu_csv_crc32="2c3f2cd8",
        source_camera_count=11_377, source_imu_count=113_557,
        camera_first_ns=1_542_884_252_125_312_224, camera_last_ns=1_542_884_272_123_384_448,
        imu_first_index=107_781, imu_last_index=111_779,
        imu_first_raw_ns=1_542_884_252_069_452_064, imu_last_raw_ns=1_542_884_272_073_589_184,
        imu_output_endpoints=(1_542_884_252_123_146_176, 1_542_884_252_128_448_224, 1_542_884_272_121_997_984, 1_542_884_272_127_283_296),
        image_total_bytes=84_445_909,
        source_inventory_sha256="c25f68d228630b6c2512d353dec2c022eed049f15c13288e801dcf4fecc7baf4", source_inventory_crc32="38b14230",
        renamed_inventory_sha256="bdadc8036be27769db84ba2c142650a3522f1b1c714bc58b24a95c8b80422d94", renamed_inventory_crc32="4e1bb750",
        times_pin=(8_020, "8dfd7e6391db4788b74e81f9bb915473e5defd2f817b0e2607c700fd01e260a1", "d70590cb"),
        camera_csv_pin=(17_669, "bd1956cd40dbbeada49547d2ff61dd990058b0c4040559307accb7ac577a3ade", "22d3ecdf"),
        imu_output_pin=(448_747, "84a1aa69bc767a5062a041edadb997f08362f62bddc79092a91d4132a9ca5cd8", "771da5a6"),
        payload_sha256="f1c2846614f8b6268b3ad84179d666ad1f31e981af024e4dd6cddf8b047d8909", payload_crc32="e69a812a",
        legacy_times_path="/mnt/data/AQUA-FE_WS/orbslam3_validation/aqualoc_a07_10800_11200/dataset/cam0_times.txt",
        legacy_full_bag_path="/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a07_10800_11200_degraded_mature_dense_lineage/features.bag",
        legacy_full_bag_size=6_087_810,
        legacy_full_bag_sha256="da79318985e46a2e01a1407b0eb0210223b13c8aaaf175da3c267bfc4e0d7292",
    ),
    "a08_4500_4660": _profile(
        key="a08_4500_4660", sequence_number=8, sequence_id="A08", start=4500, end=4660,
        source_size=2_316_571_070, source_sha256="b45e4f6dbf852ff8d7e5c9386e3df2db4daa84d1841f1eafb01a4637d2fe9153",
        gzip_crc32="3ebe1f0c", gzip_isize=2_343_168_000,
        image_csv_size=338_102, image_csv_sha256="1137d5b60e618c5febfb62f6f89f0d261af206e2256d5bfac2bea6f0cbafe689", image_csv_crc32="179269f8",
        imu_csv_size=10_495_986, imu_csv_sha256="be4ce25d04d2a50b51474a072a14071f77e450dd78aff51e5ba8378f556c3643", imu_csv_crc32="6b630122",
        source_camera_count=9_391, source_imu_count=93_837,
        camera_first_ns=1_542_885_186_107_583_632, camera_last_ns=1_542_885_194_106_222_672,
        imu_first_index=44_971, imu_last_index=46_570,
        imu_first_raw_ns=1_542_885_186_053_683_184, imu_last_raw_ns=1_542_885_194_055_132_080,
        imu_output_endpoints=(1_542_885_186_107_377_296, 1_542_885_186_112_556_240, 1_542_885_194_103_702_576, 1_542_885_194_108_826_192),
        image_total_bytes=32_753_938,
        source_inventory_sha256="237bf273bd7dfb59678db66b5c49c807430989d2246458ec2765eb19179702f3", source_inventory_crc32="1297b58b",
        renamed_inventory_sha256="53167e8dcbb9fbf0980c6fbd50c2b17285b9154bf57549b0ab829a1ada85e395", renamed_inventory_crc32="67f4a104",
        times_pin=(3_220, "6eb402b66039d6f445b481624f611c61d31c2ef7c9a74d8fddf7d98887faaf42", "cfa45570"),
        camera_csv_pin=(7_109, "9e336c1d57aca116ad04199b972b9ff8b6213a034435b4ee4ba0e679170c18b9", "b5d3d647"),
        imu_output_pin=(179_521, "647244027cceb800a1723935bc3b28cecd9290200a49b6e4d443de65d7346fcc", "f8917097"),
        payload_sha256="01d17102db0a48befb503178d055b3d65bdb1cbf9de6491735cc44fda0944b56", payload_crc32="da417214",
        legacy_times_path="/mnt/data/AQUA-FE_WS/orbslam3_validation/aqualoc_a08_4500_4660/dataset/cam0_times.txt",
        legacy_full_bag_path="/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a08_4500_4660_oldcontract_microburst/features.bag",
        legacy_full_bag_size=2_461_228,
        legacy_full_bag_sha256="6113359ba6bfa957b42302666b72f87b58bbc8300bb19d621522eb70604943f1",
    ),
    "a09_6000_6200": _profile(
        key="a09_6000_6200", sequence_number=9, sequence_id="A09", start=6000, end=6200,
        source_size=1_722_658_380, source_sha256="4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901",
        gzip_crc32="b2f3021d", gzip_isize=1_742_161_920,
        image_csv_size=251_738, image_csv_sha256="29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a", image_csv_crc32="6ab5e1f7",
        imu_csv_size=7_806_649, imu_csv_sha256="9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3", imu_csv_crc32="cc6033a9",
        source_camera_count=6_992, source_imu_count=69_861,
        camera_first_ns=1_542_889_046_021_625_712, camera_last_ns=1_542_889_056_019_958_896,
        imu_first_index=59_948, imu_last_index=61_947,
        imu_first_raw_ns=1_542_889_045_966_739_312, imu_last_raw_ns=1_542_889_055_968_943_952,
        imu_output_endpoints=(1_542_889_046_020_433_424, 1_542_889_046_026_182_064, 1_542_889_056_017_423_152, 1_542_889_056_022_638_064),
        image_total_bytes=44_103_574,
        source_inventory_sha256="686f9b22ba53d98e6166d2caa1826e6d95ab84a436c07c5e752a6ee42941a8a5", source_inventory_crc32="fb8eca52",
        renamed_inventory_sha256="cabef979ff944be56461127fa96f79ebb99510003e02a68f3be83b85f7957e10", renamed_inventory_crc32="fb6b7046",
        times_pin=(4_020, "7153a331ac4ba92dff9d31be3c99ad64c357483259f82bf51cfb3bd85ccc5240", "a1cdf69b"),
        camera_csv_pin=(8_869, "cd7d96bec8f8fd3993370904f2d3b401472dea42108868103d07a5c4b2807f79", "c3e9f1fe"),
        imu_output_pin=(223_916, "944d5ab23bfc0ca71ce3d22ae2637b0916e34b9d3c8ad3f31e1f103dee0a1a6f", "d78d16fc"),
        payload_sha256="acb17fe3c3f0e8c9b0345e2a2f8bcf6371f42dc41973f197086ffefc555ecd40", payload_crc32="0e0fa799",
        legacy_times_path="/mnt/data/AQUA-FE_WS/orbslam3_validation/aqualoc_a09_6000_6200/dataset/cam0_times.txt",
        legacy_full_bag_path="/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_jul14frozen3way_a09_6000_6200_oldcontract_microburst/features.bag",
        legacy_full_bag_size=3_090_062,
        legacy_full_bag_sha256="b92e2a31102413709586f346bb5aee7c702d6c15630eee94488ecc338f33b295",
    ),
}


def _pin(values: Sequence[Any]) -> FilePin:
    return FilePin(size_bytes=int(values[0]), sha256=str(values[1]), crc32=str(values[2]))


def contract_for(profile: Profile) -> MaterializationContract:
    endpoints = tuple(int(value) for value in profile.imu_output_endpoints)
    return MaterializationContract(
        source_archive=profile.source_archive,
        source_pin=FilePin(profile.source_size, profile.source_sha256),
        source_gzip_crc32=profile.gzip_crc32,
        source_gzip_isize=profile.gzip_isize,
        image_csv_member=profile.image_csv_member,
        image_csv_pin=FilePin(profile.image_csv_size, profile.image_csv_sha256, profile.image_csv_crc32),
        imu_csv_member=profile.imu_csv_member,
        imu_csv_pin=FilePin(profile.imu_csv_size, profile.imu_csv_sha256, profile.imu_csv_crc32),
        image_member_prefix=profile.image_member_prefix,
        source_camera_count=profile.source_camera_count,
        source_imu_count=profile.source_imu_count,
        camera_start_index=profile.start,
        camera_end_index=profile.end,
        camera_first_ns=profile.camera_first_ns,
        camera_last_ns=profile.camera_last_ns,
        width=968, height=608, png_bit_depth=8, png_color_type=0,
        imu_shift_ns=IMU_SHIFT_NS,
        imu_first_index=profile.imu_first_index,
        imu_last_index=profile.imu_last_index,
        imu_first_raw_ns=profile.imu_first_raw_ns,
        imu_last_raw_ns=profile.imu_last_raw_ns,
        imu_first_output_ns=endpoints[0], imu_second_output_ns=endpoints[1],
        imu_penultimate_output_ns=endpoints[2], imu_last_output_ns=endpoints[3],
        expected_image_total_bytes=profile.image_total_bytes,
        expected_source_image_inventory_sha256=profile.source_inventory_sha256,
        expected_source_image_inventory_crc32=profile.source_inventory_crc32,
        expected_renamed_image_inventory_sha256=profile.renamed_inventory_sha256,
        expected_renamed_image_inventory_crc32=profile.renamed_inventory_crc32,
        times_pin=_pin(profile.times_pin), camera_csv_pin=_pin(profile.camera_csv_pin),
        imu_output_pin=_pin(profile.imu_output_pin),
        expected_payload_sha256=profile.payload_sha256,
        expected_payload_crc32=profile.payload_crc32,
    )


def require_identity(path: Path, size: int, sha256: str, label: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed = core.identity_file(path, str(path.resolve()))
    if observed["size_bytes"] != size or observed["sha256"] != sha256:
        raise ContractError(f"{label}_IDENTITY_MISMATCH")
    return observed


def validate_authorities(profile: Profile, roster: Path, config: Path) -> Dict[str, Any]:
    reused_core = require_identity(CORE_PATH, CORE_SIZE, CORE_SHA256, "REUSED_STREAMING_CORE")
    roster_identity = require_identity(roster, ROSTER_SIZE, ROSTER_SHA256, "ROSTER")
    config_identity = require_identity(config, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")
    value = json.loads(roster.read_text(encoding="utf-8"))
    if value.get("schema_version") != ROSTER_SCHEMA or value.get("status") != "PROSPECTIVE_PREPARATION_ONLY_NO_RUN_AUTHORITY":
        raise ContractError("ROSTER_SCHEMA_OR_STATUS_MISMATCH")
    if any(claim is not False for claim in value.get("claims", {}).values()):
        raise ContractError("ROSTER_FORBIDDEN_CLAIM")
    row = value.get("profiles", {}).get(profile.key, {})
    expected = {
        "camera_count": profile.camera_count,
        "camera_indices_inclusive": [profile.start, profile.end],
        "sequence_id": profile.sequence_id,
        "source_archive_sha256": profile.source_sha256,
    }
    if row != expected:
        raise ContractError("ROSTER_PROFILE_MISMATCH")
    text = config.read_text(encoding="utf-8")
    for required in (
        'Camera.type: "PinHole"', "Camera.width: 968", "Camera.height: 608",
        "Camera.fps: 20", 'Extractor.type: "HFNetRT"', "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01", "Extractor.scaleFactor: 1.2", "Extractor.nLevels: 4",
        "IMU.Frequency: 200.0", "loopClosing: 1",
    ):
        if required not in text:
            raise ContractError(f"CONFIG_REQUIRED_SETTING_MISSING:{required}")
    return {"reused_streaming_core": reused_core, "roster": roster_identity, "config": config_identity}


def crosscheck_legacy_window(
    profile: Profile, selected_camera: Sequence[Sequence[Any]]
) -> Dict[str, Any]:
    """Prove the archive slice is the exact historical every2 positive window."""
    if not all(
        value is not None
        for value in (
            profile.legacy_full_bag_path,
            profile.legacy_full_bag_size,
            profile.legacy_full_bag_sha256,
        )
    ):
        return {
            "status": "NOT_CONFIGURED_FOR_THIS_PROFILE",
            "same_window_claimed": False,
        }
    bag_path = Path(str(profile.legacy_full_bag_path))
    selected_stamps = [int(row[0]) for row in selected_camera]
    times_identity: Mapping[str, Any]
    if profile.legacy_times_path is not None:
        times_path = Path(str(profile.legacy_times_path))
        expected_times = _pin(profile.times_pin)
        times_identity = core.identity_file(times_path, str(times_path.resolve()))
        core.require_pin(times_identity, expected_times, "LEGACY_WINDOW_TIMES")
        try:
            legacy_stamps = [int(line) for line in times_path.read_text(encoding="ascii").splitlines()]
        except ValueError as error:
            raise ContractError("LEGACY_WINDOW_TIMES_INVALID") from error
        if legacy_stamps != selected_stamps:
            raise ContractError("LEGACY_WINDOW_CAMERA_HEADERS_DIFFER")
    else:
        times_identity = {
            "status": "NO_SEPARATE_401_HEADER_FILE; BAG_HEADERS_CROSSCHECKED_DIRECTLY"
        }
    bag_identity = require_identity(
        bag_path,
        int(profile.legacy_full_bag_size),
        str(profile.legacy_full_bag_sha256),
        "LEGACY_FULL_FEATURE_BAG",
    )
    try:
        import rosbag  # type: ignore

        feature_stamps: List[int] = []
        with rosbag.Bag(str(bag_path), "r") as bag:
            for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
                feature_stamps.append(int(message.header.stamp.to_nsec()))
    except Exception as error:
        raise ContractError(f"LEGACY_FULL_FEATURE_BAG_UNREADABLE:{type(error).__name__}") from error
    expected_every2 = selected_stamps[1::2]
    if feature_stamps != expected_every2:
        raise ContractError("LEGACY_EVERY2_FEATURE_HEADERS_DIFFER_FROM_ARCHIVE_WINDOW")
    return {
        "status": "PASS_EXACT_HISTORICAL_WINDOW_CROSSCHECK",
        "legacy_exact_window_times": times_identity,
        "legacy_full_feature_bag": bag_identity,
        "source_camera_count": len(selected_stamps),
        "source_camera_header_ns_inclusive": [selected_stamps[0], selected_stamps[-1]],
        "legacy_every2_feature_count": len(feature_stamps),
        "legacy_every2_relative_indices": [1, len(selected_stamps) - 2, 2],
        "all_legacy_every2_headers_equal_archive_window_relative_odd_indices": True,
        "same_window_claimed": True,
    }


def prepare_metadata(
    profile: Profile,
    source_archive: Path,
    contract: MaterializationContract,
    roster: Path,
    config: Path,
) -> Dict[str, Any]:
    authorities = validate_authorities(profile, roster, config)
    source = core.validate_source_archive(source_archive, contract)
    image_payload, image_member = core.read_pinned_member(source_archive, contract.image_csv_member, contract.image_csv_pin, "IMAGE_CSV")
    imu_payload, imu_member = core.read_pinned_member(source_archive, contract.imu_csv_member, contract.imu_csv_pin, "IMU_CSV")
    _, selected_camera = core.parse_camera_rows(image_payload, contract)
    _, selected_imu = core.parse_imu_rows(imu_payload, selected_camera, contract)
    legacy_window_crosscheck = crosscheck_legacy_window(profile, selected_camera)
    times_payload = core.camera_times_bytes(selected_camera)
    camera_csv_payload = core.camera_csv_bytes(selected_camera)
    output_imu_payload = core.imu_csv_bytes(selected_imu, contract.imu_shift_ns)
    generated = {
        "cam0_times": core.identity_bytes("cam0_times.txt", times_payload),
        "cam0_data_csv": core.identity_bytes("mav0/cam0/data.csv", camera_csv_payload),
        "imu0_data_csv": core.identity_bytes("mav0/imu0/data.csv", output_imu_payload),
    }
    core.require_pin(generated["cam0_times"], contract.times_pin, "CAM0_TIMES")
    core.require_pin(generated["cam0_data_csv"], contract.camera_csv_pin, "CAM0_DATA_CSV")
    core.require_pin(generated["imu0_data_csv"], contract.imu_output_pin, "IMU0_DATA_CSV")
    bracket = core.validate_imu_bracket(output_imu_payload, selected_camera, contract)
    return {
        "authorities": authorities, "source": source,
        "source_members": {"camera_csv": image_member, "imu_csv": imu_member},
        "selected_camera": selected_camera, "selected_imu": selected_imu,
        "times_payload": times_payload, "camera_csv_payload": camera_csv_payload,
        "imu_payload": output_imu_payload, "generated_identities": generated,
        "imu_bracket": bracket, "legacy_window_crosscheck": legacy_window_crosscheck,
    }


def build_manifest(
    profile: Profile, metadata: Mapping[str, Any], image_rows: Sequence[Mapping[str, Any]],
    payload_identity: Mapping[str, Any], source_identity: Mapping[str, Any],
    renamed_identity: Mapping[str, Any], output_root: Path, contract: MaterializationContract,
) -> Dict[str, Any]:
    histogram: Dict[str, int] = {}
    for row in image_rows:
        key = str(row["png"]["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION, "status": "PASS_PREPARATION_ONLY",
        "profile": profile.key, "output_root": str(output_root.resolve(strict=False)),
        "authorities": metadata["authorities"],
        "legacy_window_crosscheck": metadata["legacy_window_crosscheck"],
        "source": {**metadata["source"], "members": metadata["source_members"], "gzip_stream_fully_consumed_and_crc_checked": True},
        "selection": {
            "dataset_family": "aqualoc_archaeology", "sequence_id": profile.sequence_id,
            "camera_indices_inclusive": [profile.start, profile.end], "camera_count": profile.camera_count,
            "score_camera_indices_inclusive": [profile.start, profile.end],
            "score_relative_indices_inclusive": [0, profile.camera_count - 1],
            "history_policy": "exact_window_cold_start", "preroll_camera_count": 0,
            "development_result_conditioned_selection": True,
            "imu_source_indices_inclusive_zero_based": [contract.imu_first_index, contract.imu_last_index],
            "imu_count": contract.imu_count, "imu_shift_ns": contract.imu_shift_ns,
            "imu_time_transform": "output_ns=raw_ns+53694112", "synthetic_imu_samples_added": False,
        },
        "camera": {
            "copy_policy": "canonical tar member PNG bytes copied unchanged",
            "renamed_to": "mav0/cam0/data/<camera_timestamp_ns>.png", "count": len(image_rows),
            "total_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "schema": "968x608 8-bit grayscale non-interlaced PNG",
            "png_chunk_crc_all_valid": True, "png_idat_all_decompressed": True,
            "png_chunk_count_histogram": histogram,
            "source_member_inventory_identity": source_identity,
            "renamed_output_inventory_identity": renamed_identity, "files": list(image_rows),
        },
        "generated_files": metadata["generated_identities"],
        "imu": {"measurement_tokens_preserved": True, "axis_transform": "none", "final_newline": False, "bracket_audit": metadata["imu_bracket"]},
        "payload_identity_excluding_manifest": payload_identity,
        "payload_file_count_excluding_manifest": len(image_rows) + 3,
        "reporting_boundary": "preparation-only same-window cold-start input; no runability, trajectory, accuracy, or ranking",
        "claims": {
            "runner_created": False, "start_claim_created": False, "hfnet_started": False,
            "vins_started": False, "detector_started": False, "evaluator_started": False,
            "trajectory_produced": False, "accuracy_measured": False,
            "scientific_comparison_produced": False, "system_ranking_supported": False,
        },
    }


def materialize(
    profile: Profile, source_archive: Path, output_root: Path,
    roster: Path = DEFAULT_ROSTER, config: Path = DEFAULT_CONFIG,
    contract: Optional[MaterializationContract] = None,
) -> Dict[str, Any]:
    contract = contract or contract_for(profile)
    metadata = prepare_metadata(profile, source_archive, contract, roster, config)
    with core.atomic_directory(output_root) as staging:
        image_rows, source_rows = core.stream_selected_images(source_archive, metadata["selected_camera"], staging, contract)
        image_total = sum(int(row["size_bytes"]) for row in image_rows)
        if image_total != contract.expected_image_total_bytes:
            raise ContractError(f"SELECTED_IMAGE_TOTAL_SIZE_MISMATCH:{image_total}")
        source_identity = core.aggregate_identities(source_rows)
        renamed_identity = core.aggregate_identities(image_rows)
        core.enforce_expected_aggregate(source_identity, contract.expected_source_image_inventory_sha256, contract.expected_source_image_inventory_crc32, "SOURCE_IMAGE_INVENTORY")
        core.enforce_expected_aggregate(renamed_identity, contract.expected_renamed_image_inventory_sha256, contract.expected_renamed_image_inventory_crc32, "RENAMED_IMAGE_INVENTORY")
        generated = metadata["generated_identities"]
        core.write_exclusive_bytes(staging / "cam0_times.txt", metadata["times_payload"])
        core.write_exclusive_bytes(staging / "mav0/cam0/data.csv", metadata["camera_csv_payload"])
        core.write_exclusive_bytes(staging / "mav0/imu0/data.csv", metadata["imu_payload"])
        payload_rows: List[Mapping[str, Any]] = list(image_rows) + [generated["cam0_times"], generated["cam0_data_csv"], generated["imu0_data_csv"]]
        payload_identity = core.aggregate_identities(payload_rows)
        core.enforce_expected_aggregate(payload_identity, contract.expected_payload_sha256, contract.expected_payload_crc32, "PAYLOAD_IDENTITY")
        manifest = build_manifest(profile, metadata, image_rows, payload_identity, source_identity, renamed_identity, output_root, contract)
        core.write_exclusive_bytes(staging / "materialization_manifest.json", core.canonical_json(manifest))
        for directory in (staging / "mav0/cam0/data", staging / "mav0/cam0", staging / "mav0/imu0", staging / "mav0", staging):
            core.fsync_directory(directory)
    return manifest


def filesystem_capacity(path: Path) -> Dict[str, int]:
    probe = path.expanduser().resolve(strict=False)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    stats = os.statvfs(str(probe))
    return {"probe_path": str(probe), "available_bytes": stats.f_bavail * stats.f_frsize}


def preflight_result(
    profile: Profile, source_archive: Path, output_root: Path,
    roster: Path = DEFAULT_ROSTER, config: Path = DEFAULT_CONFIG,
    contract: Optional[MaterializationContract] = None,
) -> Dict[str, Any]:
    if output_root.exists() or output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")
    contract = contract or contract_for(profile)
    metadata = prepare_metadata(profile, source_archive, contract, roster, config)
    capacity = filesystem_capacity(output_root.parent)
    estimated_payload = profile.image_total_bytes + sum(int(row["size_bytes"]) for row in metadata["generated_identities"].values())
    required = estimated_payload + 256 * 1024 * 1024
    if capacity["available_bytes"] < required:
        raise ContractError(f"INSUFFICIENT_OUTPUT_CAPACITY:{capacity['available_bytes']}:{required}")
    return {
        "schema_version": SCHEMA_VERSION, "status": "PREFLIGHT_READY_PREPARATION_ONLY",
        "profile": profile.key, "source": metadata["source"], "authorities": metadata["authorities"],
        "output_root": str(output_root.resolve(strict=False)),
        "selection": {"sequence_id": profile.sequence_id, "camera_indices_inclusive": [profile.start, profile.end], "camera_count": profile.camera_count, "history_policy": "exact_window_cold_start"},
        "imu_count": contract.imu_count, "generated_identities": metadata["generated_identities"],
        "imu_bracket": metadata["imu_bracket"],
        "legacy_window_crosscheck": metadata["legacy_window_crosscheck"],
        "capacity": {**capacity, "estimated_payload_bytes": estimated_payload, "required_with_256_mib_headroom": required, "ready": True},
        "process_boundary": {"gpu_required_for_preparation": False, "hfnet_started": False, "output_created": False},
        "claims": {"trajectory_produced": False, "accuracy_measured": False, "system_ranking_supported": False},
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--action", choices=("list", "preflight", "materialize"), default="preflight")
    value.add_argument("--profile", choices=tuple(PROFILES), default="a02_7600_8000")
    value.add_argument("--source-archive", type=Path)
    value.add_argument("--output-root", type=Path)
    value.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    value.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "list":
            result = {"schema_version": SCHEMA_VERSION, "status": "ROSTER_LIST_ONLY", "profiles": {key: {"sequence_id": row.sequence_id, "camera_indices_inclusive": [row.start, row.end], "camera_count": row.camera_count, "output_root": str(row.output_root)} for key, row in PROFILES.items()}, "claims": {"hfnet_started": False, "output_created": False}}
        else:
            profile = PROFILES[args.profile]
            source = args.source_archive or profile.source_archive
            output = args.output_root or profile.output_root
            result = materialize(profile, source, output, args.roster, args.config) if args.action == "materialize" else preflight_result(profile, source, output, args.roster, args.config)
        return_code = 0
    except Exception as error:
        result = {"schema_version": SCHEMA_VERSION, "status": "INTEGRITY_ERROR", "errors": [f"{type(error).__name__}:{error}"], "claims": {"hfnet_started": False, "trajectory_produced": False}}
        return_code = 2
    sys.stdout.buffer.write(core.canonical_json(result))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
