from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASELINE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[3]
GENERATED_DIR = BASELINE_DIR / "generated"
GOLDEN_DIR = BASELINE_DIR / "golden"

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


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_DIR.resolve()).as_posix()


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def current_controlled_paths() -> set[str]:
    result: set[str] = set()
    for root_name in CONTROLLED_ROOTS:
        result.update(
            rel(path)
            for path in (PROJECT_DIR / root_name).rglob("*")
            if path.is_file()
        )
    result.update(CONTROLLED_FILES)
    return result


def verify_controlled_manifest() -> dict[str, Any]:
    started = time.perf_counter()
    manifest_path = GENERATED_DIR / "controlled-files.csv"
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    manifest_paths = {row["path"] for row in rows}
    actual_paths = current_controlled_paths()
    require(
        manifest_paths == actual_paths,
        "受控清单路径集合变化: "
        f"新增={sorted(actual_paths - manifest_paths)}, "
        f"缺失={sorted(manifest_paths - actual_paths)}",
    )
    total_bytes = 0
    for row in rows:
        path = PROJECT_DIR / row["path"]
        stat = path.stat()
        actual_mtime = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(timespec="microseconds")
        require(stat.st_size == int(row["size"]), f"大小变化: {row['path']}")
        require(actual_mtime == row["mtime_utc"], f"修改时间变化: {row['path']}")
        require(sha256_file(path) == row["sha256"], f"哈希变化: {row['path']}")
        total_bytes += stat.st_size
    return {
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "rehash_duration_seconds": round(time.perf_counter() - started, 3),
    }


def table_map(probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {table["name"]: table for table in probe["tables"]}


def scalar(row: dict[str, Any], name: str) -> int:
    return int(row[name])


def verify_access_probe(label: str, required_tables: set[str]) -> dict[str, Any]:
    probe = load_json(GENERATED_DIR / "access-probes" / f"{label}.json")
    require(probe["mode"] == "Read", f"{label} 不是只读探测")
    require(probe["source_sha256"] == sha256_file(PROJECT_DIR / probe["source_path"]),
            f"{label} 源哈希不一致")
    tables = table_map(probe)
    require(required_tables.issubset(tables), f"{label} 缺少表 {required_tables - tables.keys()}")
    return probe


def verify_access() -> dict[str, Any]:
    probes = {
        "mtd": verify_access_probe(
            "mtd", {"LINES", "MTD_BURN", "MTD_PRIM", "MTD_WSTC", "USER", "WSTC"}
        ),
        "cdt": verify_access_probe("cdt", {"LAYOUT", "CCD_BAND"}),
        "cmt": verify_access_probe("cmt", {"LAYOUT", "CCD_BAND"}),
        "edt": verify_access_probe("edt", {"LAYOUT", "CCD_BAND"}),
        "wdt": verify_access_probe("wdt", {"LAYOUT", "CCD_BAND"}),
        "mtd_legacy_16": verify_access_probe(
            "mtd_legacy_16", {"LINES", "MTD_BURN", "MTD_PRIM", "MTD_WSTC", "WSTC"}
        ),
        "mdb_partial_interval": verify_access_probe(
            "mdb_partial_interval", {"LAYOUT", "CCD_BAND"}
        ),
        "mdb_evaporation_dispersion": verify_access_probe(
            "mdb_evaporation_dispersion", {"LAYOUT", "CCD_BAND", "POINT_WAVE"}
        ),
    }
    mtd_tables = table_map(probes["mtd"])
    require(mtd_tables["MTD_PRIM"]["row_count"] == 3, "DIRECT.MTD 方法数不是 3")
    require(mtd_tables["LINES"]["row_count"] == 20, "DIRECT.MTD 谱线数不是 20")
    require(mtd_tables["WSTC"]["row_count"] == 5, "DIRECT.MTD 色散曲线数不是 5")
    require(mtd_tables["USER"]["row_count"] == 0, "DIRECT.MTD USER 表不是空表")

    blob_checks = 0
    for label in ("cdt", "cmt", "edt", "wdt"):
        tables = table_map(probes[label])
        layout = tables["LAYOUT"]["first_row"]
        bands = tables["CCD_BAND"]
        require(tables["LAYOUT"]["row_count"] == 1, f"{label} LAYOUT 不是单行")
        require(bands["row_count"] > 0, f"{label} CCD_BAND 为空")
        count = scalar(layout, "CcdCount")
        points = scalar(layout, "PointsPerCcd")
        first = bands["first_row"]
        if "CcdAvgs" in first and first["CcdAvgs"]:
            require(
                first["CcdAvgs"]["byte_length"] == count * points * 4,
                f"{label} CcdAvgs 不是 float32 布局",
            )
            blob_checks += 1
        if "BurnAdcs" in first and first["BurnAdcs"]:
            burn_count = scalar(layout, "BurnCount")
            require(
                first["BurnAdcs"]["byte_length"] == burn_count * count * points * 2,
                f"{label} BurnAdcs 长度不匹配",
            )
            blob_checks += 1
        if "DarkAdcs" in first and first["DarkAdcs"]:
            dark_count = scalar(layout, "DarkCount")
            require(
                first["DarkAdcs"]["byte_length"] == dark_count * count * points * 2,
                f"{label} DarkAdcs 长度不匹配",
            )
            blob_checks += 1
    current_stds = mtd_tables["LINES"]["first_row"]["Stds"]
    legacy_stds = table_map(probes["mtd_legacy_16"])["LINES"]["first_row"]["Stds"]
    require(current_stds["byte_length"] == 700, "Spec2.02/DIRECT.MTD 标准点布局不再是 50 点")
    require(legacy_stds["byte_length"] == 224, "Spec Source/Bin/DIRECT.MTD 标准点布局不再是 16 点")
    blob_checks += 2
    require(blob_checks >= 8, "Access BLOB 验证数量不足")
    partial_template = table_map(probes["mdb_partial_interval"])
    require(partial_template["LAYOUT"]["row_count"] == 0, "分时样品.mdb 不再是空模板")
    require(partial_template["CCD_BAND"]["row_count"] == 0, "分时样品.mdb 不再是空模板")
    evaporation_template = table_map(probes["mdb_evaporation_dispersion"])
    require(evaporation_template["LAYOUT"]["row_count"] == 0, "蒸发色散.mdb LAYOUT 不再为空")
    require(evaporation_template["CCD_BAND"]["row_count"] == 0, "蒸发色散.mdb CCD_BAND 不再为空")
    require(evaporation_template["POINT_WAVE"]["row_count"] == 0, "蒸发色散.mdb POINT_WAVE 不再为空")
    return {"probe_count": len(probes), "blob_checks": blob_checks}


def verify_legacy_formats() -> dict[str, Any]:
    probe = load_json(GENERATED_DIR / "legacy-format-probes.json")
    require(probe["sam_short"]["row_count"] > 0, "短 SAM 为空")
    require(probe["sam_960"]["row_count"] == 800, "测试15-5-960.sam 实际行数不再是 800")
    require(probe["sam_960"]["expanded_band_count"] == 960, "SAM 展开谱带数不是 960")
    require(probe["pdt"]["bytes_consumed"] == (PROJECT_DIR / probe["pdt"]["path"]).stat().st_size,
            "PDT 未完整消费")
    require(probe["dat"]["bytes_consumed"] == (PROJECT_DIR / probe["dat"]["path"]).stat().st_size,
            "DAT 未完整消费")
    require(probe["acq"]["byte_length"] == 24579, "ACQ 长度不是 24579")
    require(probe["acq"]["frame_count"] == 3, "ACQ 帧数不是 3")
    require(probe["acq"]["good"], "ACQ 帧头标记错误")
    require(len(probe["acq"]["mappings"]["mirror_false"]) == 5, "ACQ 有效 CCD 数不是 5")
    require("ANALYZE" in probe["cfg"]["sections"], "CFG 缺少 ANALYZE")
    require("CCD" in probe["opt"]["sections"], "OPT 缺少 CCD")

    with (GENERATED_DIR / "legacy-files.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as stream:
        legacy_rows = list(csv.DictReader(stream))
    formats = {row["format"] for row in legacy_rows}
    expected = {"mtd", "mdb", "cdt", "cmt", "edt", "wdt", "pdt", "dat", "sam", "cfg", "opt", "acq"}
    require(expected.issubset(formats), f"旧格式清单缺少 {expected - formats}")
    return {
        "inventory_count": len(legacy_rows),
        "formats": sorted(formats),
        "pdt_shape": [probe["pdt"]["line_count"], probe["pdt"]["band_count"]],
        "dat_shape": [probe["dat"]["line_count"], probe["dat"]["sample_count"]],
    }


def verify_golden() -> dict[str, Any]:
    manifest = load_json(GOLDEN_DIR / "manifest.json")
    for item in manifest["files"]:
        path = PROJECT_DIR / item["path"]
        require(path.stat().st_size == item["size"], f"黄金文件大小变化: {item['path']}")
        require(sha256_file(path) == item["sha256"], f"黄金文件哈希变化: {item['path']}")

    gaussian = load_json(GOLDEN_DIR / "legacy-gaussian.json")
    cases = {case["name"]: case for case in gaussian["cases"]}
    require(cases["three_point_symmetric"]["expected"]["ok"], "3 点高斯未成功")
    require(not cases["invalid_even"]["expected"]["ok"], "偶数点高斯未拒绝")
    require(not cases["invalid_nonpositive"]["expected"]["ok"], "非正值高斯未拒绝")

    curve = load_json(GOLDEN_DIR / "legacy-curve-fit.json")
    fits = {case["name"]: case for case in curve["least_squares_cases"]}
    require(
        all(abs(a - b) < 1e-5 for a, b in zip(
            fits["linear_exact"]["expected_coefficients_c0_to_c3_float32"],
            [2.0, 3.0, 0.0, 0.0],
        )),
        "线性黄金系数错误",
    )
    require(
        all(abs(a - b) < 1e-5 for a, b in zip(
            fits["quadratic_exact"]["expected_coefficients_c0_to_c3_float32"],
            [1.0, 2.0, 0.5, 0.0],
        )),
        "二次黄金系数错误",
    )
    signal = load_json(GOLDEN_DIR / "legacy-signal-processing.json")
    require(
        abs(signal["average_dark_subtraction"][0]["expected_float32"] - 48.0) < 1e-5,
        "暗扣除黄金值错误",
    )
    return {"golden_file_count": len(manifest["files"]), "gaussian_cases": len(cases)}


def verify_evidence_and_docs() -> dict[str, Any]:
    evidence_path = BASELINE_DIR / "evidence-ledger.csv"
    with evidence_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = {row["feature_id"] for row in rows}
    expected = {f"F{index}" for index in range(16)}
    require(ids == expected, f"证据账功能 ID 不完整: 缺少={expected - ids}, 多余={ids - expected}")
    require(all(row["primary_evidence"].strip() for row in rows), "证据账存在空主证据")
    required_docs = (
        "README.md",
        "formats-and-protocols.md",
        "golden-samples.md",
        "risks-and-decisions.md",
        "verification-report.md",
    )
    for name in required_docs:
        path = BASELINE_DIR / name
        require(path.is_file() and path.stat().st_size > 100, f"缺少 S00 文档: {name}")
    acceptance_path = PROJECT_DIR / "docs" / "acceptance-reports" / "S00" / "验收报告.md"
    require(acceptance_path.is_file() and acceptance_path.stat().st_size > 100,
            "缺少 S00 独立验收报告")
    acceptance_text = acceptance_path.read_text(encoding="utf-8")
    require("S00_VERIFICATION_OK" in acceptance_text and "passed" in acceptance_text,
            "S00 验收报告缺少通过结论")
    require(re.search(r"PLAN\.md.*?([0-9A-Fa-f]{64})", acceptance_text) is not None,
            "S00 验收报告缺少执行时的 PLAN.md SHA-256 快照")
    risk_text = (BASELINE_DIR / "risks-and-decisions.md").read_text(encoding="utf-8")
    require("PLAN.md" in risk_text and "R-S00-001" in risk_text and "截断" in risk_text,
            "未登记 PLAN.md 截断风险")
    require("1单片机控制指令.doc" in risk_text, "未登记设备协议缺失风险")
    return {"evidence_rows": len(rows), "document_count": len(required_docs) + 1}


def main() -> int:
    started = time.perf_counter()
    try:
        result = {
            "status": "S00_VERIFICATION_OK",
            "controlled_integrity": verify_controlled_manifest(),
            "legacy_formats": verify_legacy_formats(),
            "access": verify_access(),
            "golden": verify_golden(),
            "evidence_and_docs": verify_evidence_and_docs(),
        }
        result["total_duration_seconds"] = round(time.perf_counter() - started, 3)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"status": "S00_VERIFICATION_FAILED", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
