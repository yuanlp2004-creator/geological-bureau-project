from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parent
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.method_printing import MethodPrintService
from backend.app.modules.methods import MethodDomainError, MethodService
from backend.app.modules.spectral_lines import SpectralLineService
from backend.app.schemas import MethodCreate, MethodPrintSettings, SpectralLineInput


def line(element: str, wavelength_nm: float) -> SpectralLineInput:
    return SpectralLineInput(
        line_type="analysis",
        element=element,
        wavelength_nm=wavelength_nm,
        actual_wavelength_nm=wavelength_nm + 0.0003,
        enabled=True,
        critical_band=element in {"Fe", "Mn"},
        priority=20 if element in {"Fe", "Mn"} else 10,
        background_line_id=None,
        alignment_line_id=None,
        internal_standard_mode="none",
        internal_standard_line_id=None,
        scan_width_points=11,
        background_offset_points=0,
        peak_mode="maximum",
        peak_width_points=1,
        fit_mode="linear",
        coordinate_type="linear",
        unit="ug/g",
        value_kind="content",
        decimal_places=3,
        lower_peak=300,
        minimum_peak_ratio=1.5,
        valid_range_min=0,
        valid_range_max=1000,
        over_limit_tolerance_percent=5,
        standard_points=[
            {"name": f"{element}-STD-{index}", "value": index * 25, "active": True}
            for index in range(1, 5)
        ],
    )


def main() -> int:
    output = (
        PROJECT_ROOT
        / "docs"
        / "acceptance-reports"
        / "S05"
        / "artifacts"
        / "S05-方法参数预览.pdf"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="geospectrum-s05-") as temp:
        database = Database(Path(temp) / "sample.sqlite3")
        database.initialize()
        methods = MethodService(database)
        spectra = SpectralLineService(database)
        created = methods.create(
            MethodCreate(
                name="S05 多元素标样方法",
                description="方法条件、分析谱线和标准点的统一分页验收样例",
                work_type="routine",
            ),
            None,  # type: ignore[arg-type]
        )
        method_id = int(created["id"])
        for element, wavelength in (
            ("Fe", 254.0),
            ("Mn", 255.0),
            ("Cr", 256.0),
            ("Ni", 257.0),
            ("Cu", 258.0),
            ("Si", 259.0),
        ):
            try:
                spectra.create(method_id, line(element, wavelength), None)  # type: ignore[arg-type]
            except MethodDomainError as exc:
                raise RuntimeError(f"sample line {element} failed: {exc.detail()}") from exc

        pdf_bytes, document = MethodPrintService(database).pdf(
            method_id,
            None,
            MethodPrintSettings(
                paper="A4",
                orientation="portrait",
                margin_top_mm=12,
                margin_right_mm=12,
                margin_bottom_mm=12,
                margin_left_mm=12,
                layout="standard",
                font_size_pt=9,
            ),
            None,  # type: ignore[arg-type]
        )
        output.write_bytes(pdf_bytes)
        print(
            f"wrote {output} ({document['page_count']} pages, "
            f"{document['field_count']} fields, {len(pdf_bytes)} bytes)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
