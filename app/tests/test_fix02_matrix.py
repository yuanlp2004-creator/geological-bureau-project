import csv
import pytest
from backend.config import AppConfig
from backend.runtime import Runtime
from backend.modules.postprocessing import PostProcessingError
from tests.test_s10_spectrum_viewer import seed_database


def test_dat_matrix_exports_all_values_and_rejects_unsupported_source(tmp_path):
    database = seed_database(tmp_path / "matrix.sqlite3")
    service = Runtime(AppConfig(data_dir=tmp_path), database=database).postprocessing_service()
    for fmt in ["csv", "txt", "excel"]:
        output = service.export(
            {
                "record_ids": ["result:1"],
                "kind": "result_matrix",
                "format": fmt,
                "output_directory": str(tmp_path / "output"),
                "filename": fmt,
            }
        )
        from pathlib import Path

        text = Path(output["path"]).read_text(encoding="utf-8-sig")
        if fmt == "excel":
            import xml.etree.ElementTree as ET

            rows = [
                [cell.text or "" for cell in row.findall(".//{urn:schemas-microsoft-com:office:spreadsheet}Data")]
                for row in ET.fromstring(text).findall(".//{urn:schemas-microsoft-com:office:spreadsheet}Row")
            ]
        else:
            rows = list(csv.reader(text.splitlines(), delimiter="," if fmt == "csv" else "\t"))
        assert [float(row[rows[0].index("calculated_value")]) for row in rows[1:]] == [1, 2, 3, 4, 5, 6]
        assert [row[3] for row in rows[1:]] == ["S1", "S2", "S3"] * 2
    with pytest.raises(PostProcessingError, match="先分析或重算"):
        service.export(
            {
                "record_ids": ["sample:1"],
                "kind": "result_matrix",
                "format": "csv",
                "output_directory": str(tmp_path / "rejected"),
            }
        )
    assert not (tmp_path / "rejected").exists()

    # PDT values are peak/background pairs, never labelled as concentration.
    import json, struct

    with database.write() as db:
        source = dict(db.execute("SELECT * FROM result_matrices WHERE id=1").fetchone())
        payload = json.loads(source["payload_json"])
        payload["matrix_kind"] = "peak_back"
        source.pop("id")
        source.update(
            record_index=1,
            format="pdt",
            payload_json=json.dumps(payload),
            matrix_blob=struct.pack("<12f", *range(1, 13)),
        )
        identifier = db.execute(
            f"INSERT INTO result_matrices ({','.join(source)}) VALUES ({','.join('?' for _ in source)})",
            list(source.values()),
        ).lastrowid
    output = service.export(
        {
            "record_ids": [f"result:{identifier}"],
            "kind": "result_matrix",
            "format": "csv",
            "output_directory": str(tmp_path / "output"),
            "filename": "pdt",
        }
    )
    rows = list(csv.DictReader(Path(output["path"]).read_text(encoding="utf-8-sig").splitlines()))
    assert [float(row["peak"]) for row in rows] == [1, 3, 5, 7, 9, 11]
    assert [float(row["back"]) for row in rows] == [2, 4, 6, 8, 10, 12]
    assert all(row["calculated_value"] == "" for row in rows)
