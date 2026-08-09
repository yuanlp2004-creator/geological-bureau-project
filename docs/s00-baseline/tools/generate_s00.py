from __future__ import annotations

import configparser
import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import struct
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


BASELINE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[3]
GENERATED_DIR = BASELINE_DIR / "generated"
GOLDEN_DIR = BASELINE_DIR / "golden"
ACCESS_DIR = GENERATED_DIR / "access-probes"

CONTROLLED_ROOTS = (
    "Spec Source",
    "Spec2.02",
    "SpecFile",
    "Spec2.02功能研究",
)
CONTROLLED_FILES = (
    "AGENTS.md",
    "PLAN.md",
    "docs/项目重构Plan提示词与UI参考_AI执行版.md",
    "docs/ui-test-homepage-reference.png",
)

LEGACY_EXTENSIONS = {
    ".mtd",
    ".mdb",
    ".cdt",
    ".cmt",
    ".edt",
    ".wdt",
    ".pdt",
    ".dat",
    ".sam",
    ".cfg",
    ".opt",
    ".acq",
}

ACCESS_SAMPLES = {
    "mtd": "Spec2.02/DIRECT.MTD",
    "cdt": "Spec Source/Bin/DATA/测试15-5_20170509_[2-16].cdt",
    "cmt": "Spec2.02/DATA/测试15-5_20170509_[2-16].cmt",
    "edt": "Spec2.02/DATA/20141029_测试.edt",
    "wdt": "Spec2.02/DATA/20141029_测试.wdt",
    "mtd_legacy_16": "SpecFile/03_方法与数据库/DIRECT.MTD",
    "mdb_partial_interval": "SpecFile/03_方法与数据库/分时样品.mdb",
    "mdb_evaporation_dispersion": "SpecFile/03_方法与数据库/蒸发色散.mdb",
}

SELECTED_SAMPLES = {
    "cfg": "Spec2.02/DIRECT.CFG",
    "opt": "Spec2.02/DIRECT.OPT",
    "sam_short": "Spec2.02/DATA/测试15-5.sam",
    "sam_960": "Spec2.02/DATA/测试15-5-960.sam",
    "pdt": "Spec Source/Bin/DATA/测试15-5_20190421_1842.pdt",
    "dat": "Spec Source/Bin/DATA/测试15-5_20190421_1842.dat",
    "acq": "Spec Source/Res/模拟数据/280-288.acq",
}


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_DIR.resolve()).as_posix()


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def controlled_paths() -> list[Path]:
    paths: list[Path] = []
    for root_name in CONTROLLED_ROOTS:
        root = PROJECT_DIR / root_name
        paths.extend(path for path in root.rglob("*") if path.is_file())
    paths.extend(PROJECT_DIR / name for name in CONTROLLED_FILES)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"受控文件不存在: {missing}")
    return sorted(set(paths), key=lambda item: rel(item).casefold())


def generate_manifest() -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for path in controlled_paths():
        stat = path.stat()
        rows.append(
            {
                "path": rel(path),
                "size": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(timespec="microseconds"),
                "sha256": sha256_file(path),
            }
        )
    manifest_path = GENERATED_DIR / "controlled-files.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("path", "size", "mtime_utc", "sha256")
        )
        writer.writeheader()
        writer.writerows(rows)

    extension_counts = Counter(
        Path(row["path"]).suffix.lower() or "<none>" for row in rows
    )
    summary = {
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "controlled_roots": list(CONTROLLED_ROOTS),
        "controlled_files": list(CONTROLLED_FILES),
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "extension_counts": dict(sorted(extension_counts.items())),
        "hash_duration_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(GENERATED_DIR / "manifest-summary.json", summary)
    return rows, summary["hash_duration_seconds"]


def generate_legacy_inventory(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = {
        Path(value).as_posix() for value in ACCESS_SAMPLES.values()
    } | {Path(value).as_posix() for value in SELECTED_SAMPLES.values()}
    rows = []
    for item in manifest:
        suffix = Path(item["path"]).suffix.lower()
        if suffix not in LEGACY_EXTENSIONS:
            continue
        rows.append(
            {
                "path": item["path"],
                "format": suffix[1:],
                "size": item["size"],
                "mtime_utc": item["mtime_utc"],
                "sha256": item["sha256"],
                "selected_probe": "yes" if item["path"] in selected else "no",
            }
        )
    output = GENERATED_DIR / "legacy-files.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "path",
                "format",
                "size",
                "mtime_utc",
                "sha256",
                "selected_probe",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def decode_legacy_text(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1"), "latin1-lossless"


def parse_ini(path: Path) -> dict[str, Any]:
    text, encoding = decode_legacy_text(path.read_bytes())
    parser = configparser.RawConfigParser(
        interpolation=None, strict=False, empty_lines_in_values=False
    )
    parser.optionxform = str
    parser.read_string(text)
    return {
        "path": rel(path),
        "encoding": encoding,
        "sections": {
            section: dict(parser.items(section, raw=True))
            for section in parser.sections()
        },
    }


def parse_sam(path: Path) -> dict[str, Any]:
    text, encoding = decode_legacy_text(path.read_bytes())
    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "\t" not in line:
            raise ValueError(f"{rel(path)}:{line_number} 缺少制表符")
        name, rep_text = line.split("\t", 1)
        rows.append(
            {
                "line": line_number,
                "name": name.strip(),
                "repeat": int(rep_text.strip()),
            }
        )
    return {
        "path": rel(path),
        "encoding": encoding,
        "row_count": len(rows),
        "blank_count": sum(row["repeat"] == 0 for row in rows),
        "expanded_band_count": sum(
            1 if row["repeat"] == 0 else row["repeat"] for row in rows
        ),
        "first_rows": rows[:5],
        "last_rows": rows[-5:],
    }


def parse_acq(path: Path, active_indexes: Iterable[int]) -> dict[str, Any]:
    raw = path.read_bytes()
    frame_count = 3
    ccds_per_frame = 2
    points_per_ccd = 2048
    values_per_frame = ccds_per_frame * points_per_ccd
    frame_size = 1 + values_per_frame * 2
    expected_size = frame_count * frame_size
    if len(raw) != expected_size:
        raise ValueError(
            f"{rel(path)} 长度 {len(raw)}，预期 {expected_size}"
        )
    frames = []
    for frame_index in range(frame_count):
        offset = frame_index * frame_size
        head = raw[offset]
        adcs = struct.unpack_from(f"<{values_per_frame}H", raw, offset + 1)
        frames.append({"head": head, "adcs": adcs})

    def map_ccd(ccd_index: int, mirror: bool) -> list[int]:
        if mirror:
            frame_index = ccd_index // ccds_per_frame
            mod_index = ccd_index % ccds_per_frame
            point_indexes = range(points_per_ccd - 1, -1, -1)
        else:
            ccd_volume = frame_count * ccds_per_frame
            frame_index = (ccd_volume - (ccd_index + 1)) // ccds_per_frame
            mod_index = (ccds_per_frame - 1) - ccd_index % ccds_per_frame
            point_indexes = range(points_per_ccd)
        return [
            frames[frame_index]["adcs"][ccds_per_frame * point + mod_index]
            for point in point_indexes
        ]

    mappings: dict[str, Any] = {}
    for mirror in (False, True):
        label = "mirror_true" if mirror else "mirror_false"
        mapped = []
        for ccd_index in active_indexes:
            values = map_ccd(ccd_index, mirror)
            packed = struct.pack(f"<{len(values)}H", *values)
            mapped.append(
                {
                    "physical_ccd_index_zero_based": ccd_index,
                    "point_count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "sum": sum(values),
                    "first_8": values[:8],
                    "last_8": values[-8:],
                    "sha256_uint16_le": hashlib.sha256(packed).hexdigest(),
                }
            )
        mappings[label] = mapped

    return {
        "path": rel(path),
        "byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "frame_count": frame_count,
        "frame_size": frame_size,
        "heads": [frame["head"] for frame in frames],
        "good": all(frame["head"] == 0 for frame in frames),
        "frames": [
            {
                "index": index,
                "min": min(frame["adcs"]),
                "max": max(frame["adcs"]),
                "sum": sum(frame["adcs"]),
                "first_8": list(frame["adcs"][:8]),
                "last_8": list(frame["adcs"][-8:]),
            }
            for index, frame in enumerate(frames)
        ],
        "active_ccd_indexes_zero_based": list(active_indexes),
        "mappings": mappings,
    }


class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def unpack(self, format_string: str) -> tuple[Any, ...]:
        values = struct.unpack_from("<" + format_string, self.data, self.offset)
        self.offset += struct.calcsize("<" + format_string)
        return values

    def short_string(self, max_bytes: int) -> str:
        length = self.unpack("B")[0]
        raw = self.data[self.offset : self.offset + max_bytes]
        self.offset += max_bytes
        if length > max_bytes:
            raise ValueError(f"ShortString 长度 {length} 超过 {max_bytes}")
        text, _ = decode_legacy_text(raw[:length])
        return text


def delphi_datetime(value: float) -> str:
    epoch = datetime(1899, 12, 30)
    return (epoch + timedelta(days=value)).isoformat(timespec="milliseconds")


def parse_pdt(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    reader = BinaryReader(raw)
    head = reader.unpack("H")[0]
    if head not in (0x0A70, 0x0A73):
        raise ValueError(f"{rel(path)} 未知 PDT 头 0x{head:04x}")
    method_id = reader.unpack("i")[0]
    measured = reader.unpack("d")[0]
    sample_count, line_count = reader.unpack("hh")
    sample_names = [reader.short_string(10) for _ in range(sample_count)]
    sample_repeats = list(reader.unpack(f"{sample_count}h"))
    elements = [reader.short_string(4) for _ in range(line_count)]
    waves = list(reader.unpack(f"{line_count}f"))
    backs = list(reader.unpack(f"{line_count}h"))
    digits = list(reader.unpack(f"{line_count}h"))
    exposure_segments = None
    if head == 0x0A73:
        exposure_segments = [
            {"left": left, "right": right}
            for left, right in (
                reader.unpack("BB") for _ in range(line_count)
            )
        ]
    band_count = sum(sample_repeats)
    matrix = []
    for line_index in range(line_count):
        row = [
            {"peak": peak, "back": back}
            for peak, back in (
                reader.unpack("ff") for _ in range(band_count)
            )
        ]
        matrix.append(row)
    if reader.offset != len(raw):
        raise ValueError(
            f"{rel(path)} 解析结束位置 {reader.offset}，文件长度 {len(raw)}"
        )
    return {
        "path": rel(path),
        "head_hex": f"0x{head:04x}",
        "exposure_segment_mode": head == 0x0A73,
        "method_id": method_id,
        "measure_time": delphi_datetime(measured),
        "sample_count": sample_count,
        "line_count": line_count,
        "band_count": band_count,
        "sample_names": sample_names,
        "sample_repeats": sample_repeats,
        "elements": elements,
        "waves": waves,
        "backs": backs,
        "digits": digits,
        "exposure_segments": exposure_segments,
        "matrix_probe": [
            {
                "line_index": index,
                "first": row[0] if row else None,
                "last": row[-1] if row else None,
            }
            for index, row in enumerate(matrix)
        ],
        "bytes_consumed": reader.offset,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def parse_dat(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    reader = BinaryReader(raw)
    head = reader.unpack("H")[0]
    if head != 0x0A64:
        raise ValueError(f"{rel(path)} 未知 DAT 头 0x{head:04x}")
    measured = reader.unpack("d")[0]
    sample_count, line_count = reader.unpack("hh")
    sample_names = [reader.short_string(10) for _ in range(sample_count)]
    elements = [reader.short_string(4) for _ in range(line_count)]
    digits = list(reader.unpack(f"{line_count}h"))
    matrix = [
        list(reader.unpack(f"{sample_count}f")) for _ in range(line_count)
    ]
    if reader.offset != len(raw):
        raise ValueError(
            f"{rel(path)} 解析结束位置 {reader.offset}，文件长度 {len(raw)}"
        )
    return {
        "path": rel(path),
        "head_hex": f"0x{head:04x}",
        "measure_time": delphi_datetime(measured),
        "sample_count": sample_count,
        "line_count": line_count,
        "sample_names": sample_names,
        "elements": elements,
        "digits": digits,
        "matrix_probe": [
            {
                "line_index": index,
                "first": row[0] if row else None,
                "last": row[-1] if row else None,
            }
            for index, row in enumerate(matrix)
        ],
        "bytes_consumed": reader.offset,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def probe_access(label: str, source: Path) -> dict[str, Any]:
    ps32 = Path(
        os.environ.get(
            "S00_PS32",
            r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe",
        )
    )
    reader_script = BASELINE_DIR / "tools" / "read_access.ps1"
    if not ps32.is_file():
        raise FileNotFoundError(f"缺少 32 位 Windows PowerShell: {ps32}")
    with tempfile.TemporaryDirectory(prefix="specdirect-s00-access-") as temp_dir:
        copied = Path(temp_dir) / source.name
        shutil.copy2(source, copied)
        command = [
            str(ps32),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(reader_script),
            "-Path",
            str(copied),
        ]
        completed = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Access 探测失败 {rel(source)}，退出码 {completed.returncode}: "
                f"{completed.stderr.strip()}"
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"Access 探测无输出: {rel(source)}")
        result = json.loads(lines[-1].lstrip("\ufeff"))
    result["label"] = label
    result["source_path"] = rel(source)
    result["source_sha256"] = sha256_file(source)
    write_json(ACCESS_DIR / f"{label}.json", result)
    return result


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def legacy_gaussian(values: list[float]) -> dict[str, Any]:
    size = len(values)
    result: dict[str, Any] = {
        "ok": False,
        "size": size,
        "center": 0.0,
        "peak_double": 0.0,
        "peak_stored_float32": 0.0,
        "sigma": None,
    }
    if size < 3 or size > 9 or size % 2 == 0:
        return result
    if size == 3:
        cal_size, multiplier = 7, 3
    elif size == 5:
        cal_size, multiplier = 9, 2
    else:
        cal_size, multiplier = size, 1
    pace = 1.0 / multiplier
    xs: list[float] = []
    weights: list[float] = []
    ys: list[float] = []
    for i in range(cal_size):
        x = i * pace
        j = i // multiplier
        weight = values[j]
        k = i % multiplier
        if k:
            weight += (values[j + 1] - weight) * k * pace
        if weight <= 0:
            return result
        xs.append(x)
        weights.append(weight)
        ys.append(math.log(weight))
    buffer = [0.0] * 8
    for x, weight, y in zip(xs, weights, ys):
        working_weight = weight
        for j in range(5):
            if j < 3:
                buffer[j + 5] += working_weight * y
            buffer[j] += working_weight
            working_weight *= x
    x_mean = buffer[1] / buffer[0]
    second_mean = buffer[2] / buffer[0]
    buffer[5] /= buffer[0]
    buffer[6] -= buffer[1] * buffer[5]
    buffer[7] -= buffer[2] * buffer[5]
    buffer[4] -= buffer[2] * second_mean
    buffer[3] -= buffer[1] * second_mean
    buffer[1] = buffer[2] - buffer[1] * x_mean
    determinant = buffer[1] * buffer[4] - buffer[3] * buffer[3]
    if abs(determinant) < 1e-100:
        return result
    a2 = (buffer[1] * buffer[7] - buffer[3] * buffer[6]) / determinant
    a1 = (buffer[4] * buffer[6] - buffer[3] * buffer[7]) / determinant
    a0 = buffer[5] - a1 * x_mean - a2 * second_mean
    if a2 >= 0:
        return result
    sigma = math.sqrt(-0.5 / a2)
    center = -0.5 * a1 / a2
    peak = math.exp(a0 + 0.5 * center * a1)
    result.update(
        {
            "ok": True,
            "center": center,
            "peak_double": peak,
            "peak_stored_float32": f32(peak),
            "sigma": sigma,
        }
    )
    return result


def legacy_least_squares(
    xs: list[float], ys: list[float], mode: str
) -> list[float]:
    if len(xs) != len(ys) or not xs:
        raise ValueError("拟合输入长度无效")
    mode_index = {"linear": 0, "quadratic": 1, "cubic": 2}[mode]
    size = len(xs)
    coefficients = [0.0] * 4
    cx = [0.0] * 10
    for x, y in zip(xs, ys):
        power = 1.0
        for j in range(6):
            if j < 4:
                cx[j + 6] += power * y
            power *= x
            cx[j] += power
    cx[6] /= size
    for index in range(7, 10):
        cx[index] -= cx[index - 7] * cx[6]
    d = cx[1] / size
    e = cx[3] - cx[1] * d
    zz = cx[2] / size
    c = cx[0] / size
    for index in range(3):
        cx[index + 3] -= cx[index] * zz
    cx[2] -= cx[0] * d
    cx[0] = cx[1] - cx[0] * c
    coefficients[0] = cx[2] * cx[2]
    coefficients[1] = cx[4] * cx[4]
    determinant = cx[2] * cx[3] * cx[4]
    determinant = (
        determinant
        + determinant
        + cx[0] * (e * cx[5] - coefficients[1])
        - e * cx[3] * cx[3]
        - coefficients[0] * cx[5]
    )
    if abs(determinant) < 1e-19 or mode_index == 0:
        coefficients[1] = cx[7] / cx[0]
    elif mode_index == 1:
        denominator = e * cx[0] - cx[2] * cx[2]
        coefficients[2] = (cx[8] * cx[0] - cx[2] * cx[7]) / denominator
        coefficients[1] = (e * cx[7] - cx[2] * cx[8]) / denominator
    else:
        coefficients[3] = (
            cx[7] * (cx[2] * cx[4] - cx[3] * e)
            + cx[8] * (cx[2] * cx[3] - cx[0] * cx[4])
            + cx[9] * (cx[0] * e - coefficients[0])
        ) / determinant
        coefficients[2] = (
            cx[7] * (cx[3] * cx[4] - cx[2] * cx[5])
            + cx[8] * (cx[0] * cx[5] - cx[3] * cx[3])
            + cx[9] * (cx[2] * cx[3] - cx[0] * cx[4])
        ) / determinant
        coefficients[1] = (
            cx[7] * (e * cx[5] - coefficients[1])
            + cx[8] * (cx[3] * cx[4] - cx[2] * cx[5])
            + cx[9] * (cx[2] * cx[4] - cx[3] * e)
        ) / determinant
    coefficients[0] = (
        cx[6]
        - coefficients[1] * c
        - coefficients[2] * d
        - coefficients[3] * zz
    )
    return [f32(value) for value in coefficients]


def natural_spline(xs: list[float], ys: list[float]) -> dict[str, Any]:
    size = len(xs)
    if size < 3 or size != len(ys):
        raise ValueError("样条输入无效")
    h = [xs[i + 1] - xs[i] for i in range(size - 1)]
    dy = [(ys[i + 1] - ys[i]) / h[i] for i in range(size - 1)]
    second = [0.0] * size
    slopes = [0.0] * (size - 1)
    e_values = [0.0] * (size - 2)
    for i in range(1, size - 1):
        second[i] = (dy[i] - dy[i - 1]) * 6.0
    z = (h[0] + h[1]) * 2.0
    slopes[0] = -h[1] / z
    e_values[0] = second[1] / z
    for i in range(1, size - 2):
        z = (h[i] + h[i + 1]) * 2.0 + h[i] * slopes[i - 1]
        slopes[i] = -h[i + 1] / z
        e_values[i] = (second[i + 1] - h[i] * e_values[i - 1]) / z
    second[size - 2] = e_values[size - 3]
    for offset in range(1, size - 2):
        i = (size - 2) - offset
        second[i] = slopes[i - 1] * second[i + 1] + e_values[i - 1]
    for i in range(size - 1):
        slopes[i] = (second[i + 1] - second[i]) / h[i]
    return {
        "second_derivatives": [f32(value) for value in second],
        "segment_slopes": [f32(value) for value in slopes],
        "dy": [f32(value) for value in dy],
    }


def spline_y(
    x: float,
    xs: list[float],
    ys: list[float],
    second: list[float],
    slopes: list[float],
    dy: list[float],
) -> float:
    i = 1
    while i < len(xs):
        if x <= xs[i]:
            break
        i += 1
    segment = i - 1
    h_value = x - xs[segment]
    result = ys[segment] + h_value * (
        dy[segment]
        + (x - xs[segment + 1])
        * (
            second[segment + 1]
            + 2 * second[segment]
            + h_value * slopes[segment]
        )
        / 6.0
    )
    return f32(result)


def generate_golden() -> list[Path]:
    gaussian_cases = []
    for name, values in (
        ("three_point_symmetric", [10.0, 40.0, 10.0]),
        ("five_point_symmetric", [1.0, 4.0, 10.0, 4.0, 1.0]),
        (
            "seven_point_offset",
            [
                100.0 * math.exp(-0.5 * ((index - 3.2) / 1.1) ** 2)
                for index in range(7)
            ],
        ),
        ("invalid_even", [1.0, 2.0, 2.0, 1.0]),
        ("invalid_nonpositive", [1.0, 0.0, 1.0]),
    ):
        gaussian_cases.append(
            {"name": name, "input": values, "expected": legacy_gaussian(values)}
        )
    gaussian = {
        "profile": "legacy_2_0_2",
        "provenance": "Spec Source/Source/Common/uPeakMode.pas:TGaussCur.Cal",
        "note": "旧版返回高斯峰高；不是峰面积。写入 TPdt.Peak 时按 float32 保存。",
        "tolerance": {"double_absolute": 1e-9, "stored_float32_absolute": 1e-5},
        "cases": gaussian_cases,
    }
    gaussian_path = GOLDEN_DIR / "legacy-gaussian.json"
    write_json(gaussian_path, gaussian)

    fit_cases = []
    fit_inputs = (
        (
            "linear_exact",
            "linear",
            [1.0, 2.0, 3.0, 4.0],
            [5.0, 8.0, 11.0, 14.0],
        ),
        (
            "quadratic_exact",
            "quadratic",
            [0.0, 1.0, 2.0, 3.0, 4.0],
            [1.0 + 2.0 * x + 0.5 * x * x for x in range(5)],
        ),
        (
            "cubic_exact",
            "cubic",
            [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0],
            [
                2.0 - x + 0.25 * x * x + 0.1 * x * x * x
                for x in [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
            ],
        ),
    )
    for name, mode, xs, ys in fit_inputs:
        coefficients = legacy_least_squares(xs, ys, mode)
        fit_cases.append(
            {
                "name": name,
                "mode": mode,
                "x": xs,
                "y": ys,
                "expected_coefficients_c0_to_c3_float32": coefficients,
                "expected_at_2_5": f32(
                    coefficients[0]
                    + 2.5
                    * (
                        coefficients[1]
                        + 2.5 * (coefficients[2] + 2.5 * coefficients[3])
                    )
                ),
            }
        )
    spline_x = [0.0, 1.0, 2.0, 4.0]
    spline_values = [0.0, 1.0, 0.0, 2.0]
    spline = natural_spline(spline_x, spline_values)
    spline["evaluations"] = [
        {
            "x": x,
            "expected_y_float32": spline_y(
                x,
                spline_x,
                spline_values,
                spline["second_derivatives"],
                spline["segment_slopes"],
                spline["dy"],
            ),
        }
        for x in (0.0, 0.5, 1.5, 3.0, 4.0)
    ]
    curve_fit = {
        "profile": "legacy_2_0_2",
        "provenance": "Spec Source/Source/Common/uFitMode.pas",
        "coefficient_storage": "float32",
        "tolerance_absolute": 1e-5,
        "least_squares_cases": fit_cases,
        "natural_spline_case": {
            "x": spline_x,
            "y": spline_values,
            **spline,
        },
        "log_coordinate_case": {
            "input_intensity": 10.0,
            "input_content": 100.0,
            "transformed": [math.log(10.0), math.log(100.0)],
            "reverse_content": math.exp(math.log(100.0)),
            "provenance": "Spec Source/Source/Main/mmAnalyze/FmAnaCurve.pas:TCoordTransform",
        },
    }
    curve_path = GOLDEN_DIR / "legacy-curve-fit.json"
    write_json(curve_path, curve_fit)

    stats_values = [10.0, 12.0, 14.0]
    mean = statistics.mean(stats_values)
    stddev = statistics.stdev(stats_values)
    signal = {
        "profile": "legacy_2_0_2",
        "provenance": [
            "Spec Source/Source/Common/uCcdBand.pas:TCcdBand.CalAllAvgs/CalMinAvgs",
            "Spec Source/Source/Common/uAnaThread.pas:TAnaThread.SeekPeak",
            "Spec Source/Source/Main/mmAnalyze/FmAnaCheck.pas:PdtToBlack/CalRsd/CheckSampOver",
        ],
        "average_dark_subtraction": [
            {
                "burn_adc": [100, 120, 140],
                "burn_cycle_seconds": 2.0,
                "dark_adc": [10, 14],
                "dark_cycle_seconds": 1.0,
                "expected_float32": f32((100 + 120 + 140) / 6.0 - 24 / 2.0),
            },
            {
                "burn_adc": [1, 1],
                "burn_cycle_seconds": 2.0,
                "dark_adc": [10],
                "dark_cycle_seconds": 1.0,
                "expected_float32": f32(0.1),
                "note": "低于 LowAvg=0.1 时截断。",
            },
        ],
        "peak_search": [
            {
                "mode": "triangle_checked",
                "values": [1.0, 3.0, 2.0, 7.0, 5.0, 9.0, 4.0],
                "initial_index": 1,
                "low_peak": 6.0,
                "low_ratio": 2.0,
                "expected_index": 5,
                "expected_peak": 9.0,
                "expected_min": 1.0,
            },
            {
                "mode": "triangle_fallback",
                "values": [5.0, 4.0, 3.0, 4.0, 5.0],
                "initial_index": 2,
                "expected_index": 2,
                "expected_peak": 3.0,
                "expected_min": 3.0,
            },
            {
                "mode": "max_first_on_tie",
                "values": [1.0, 8.0, 8.0, 2.0],
                "expected_index": 1,
                "expected_peak": 8.0,
                "expected_min": 1.0,
            },
        ],
        "pdt_to_black": [
            {"case": "no_background", "peak": 120.0, "expected": 120.0},
            {
                "case": "subtract_background",
                "peak": 120.0,
                "back": 20.0,
                "expected": 100.0,
            },
            {
                "case": "background_as_internal_standard",
                "peak": 120.0,
                "back": 20.0,
                "expected": 6.0,
            },
            {
                "case": "line_internal_standard",
                "analysis_peak": 120.0,
                "analysis_back": 20.0,
                "internal_peak": 60.0,
                "internal_back": 10.0,
                "expected": 2.0,
            },
            {
                "case": "minimum_clip",
                "peak": 2.0,
                "back": 3.0,
                "expected": 1e-5,
            },
        ],
        "repeatability": {
            "values": stats_values,
            "mean": mean,
            "sample_stddev": stddev,
            "rsd_percent": min(999.0, abs(100.0 * stddev / mean)),
            "ida": 21.7147 * math.log(max(stats_values) / min(stats_values)),
        },
        "tolerance_absolute": 1e-5,
    }
    signal_path = GOLDEN_DIR / "legacy-signal-processing.json"
    write_json(signal_path, signal)
    return [gaussian_path, curve_path, signal_path]


def main() -> int:
    started = time.perf_counter()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    ACCESS_DIR.mkdir(parents=True, exist_ok=True)

    manifest, hash_duration = generate_manifest()
    legacy_inventory = generate_legacy_inventory(manifest)

    cfg = parse_ini(PROJECT_DIR / SELECTED_SAMPLES["cfg"])
    opt = parse_ini(PROJECT_DIR / SELECTED_SAMPLES["opt"])
    active_indexes = [
        int(item.strip()) - 1
        for item in opt["sections"]["CCD"]["CcdIndexs"].split(",")
        if item.strip()
    ]
    text_and_binary = {
        "cfg": cfg,
        "opt": opt,
        "sam_short": parse_sam(PROJECT_DIR / SELECTED_SAMPLES["sam_short"]),
        "sam_960": parse_sam(PROJECT_DIR / SELECTED_SAMPLES["sam_960"]),
        "pdt": parse_pdt(PROJECT_DIR / SELECTED_SAMPLES["pdt"]),
        "dat": parse_dat(PROJECT_DIR / SELECTED_SAMPLES["dat"]),
        "acq": parse_acq(
            PROJECT_DIR / SELECTED_SAMPLES["acq"], active_indexes
        ),
    }
    write_json(GENERATED_DIR / "legacy-format-probes.json", text_and_binary)

    access_results = {
        label: probe_access(label, PROJECT_DIR / relative_path)
        for label, relative_path in ACCESS_SAMPLES.items()
    }
    write_json(GENERATED_DIR / "access-probe-index.json", access_results)

    golden_paths = generate_golden()
    golden_paths.append(GENERATED_DIR / "legacy-format-probes.json")
    golden_manifest = {
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "files": [
            {
                "path": rel(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in golden_paths
        ],
    }
    write_json(GOLDEN_DIR / "manifest.json", golden_manifest)

    result = {
        "status": "S00_GENERATION_OK",
        "controlled_file_count": len(manifest),
        "controlled_total_bytes": sum(item["size"] for item in manifest),
        "legacy_file_count": len(legacy_inventory),
        "legacy_formats": sorted({item["format"] for item in legacy_inventory}),
        "access_probe_count": len(access_results),
        "golden_file_count": len(golden_paths),
        "hash_duration_seconds": hash_duration,
        "total_duration_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
