"""Existing v12 migration: dispersion."""

import sqlite3
import hashlib
import json
import struct
import zlib

from .sql import _require_tables, _columns


def _migrate_v12(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        12,
        (
            "dispersion_tasks",
            "dispersion_task_frames",
            "dispersion_task_lines",
            "dispersion_calibration_versions",
            "method_calibration_bindings",
        ),
    )
    columns = _columns(connection, "dispersion_task_frames")
    additions = {
        "points_blob": "BLOB",
        "points_count": "INTEGER NOT NULL DEFAULT 0",
        "dtype": "TEXT NOT NULL DEFAULT 'uint16' CHECK(dtype = 'uint16')",
        "endianness": "TEXT NOT NULL DEFAULT 'little' CHECK(endianness = 'little')",
        "compression": "TEXT NOT NULL DEFAULT 'zlib' CHECK(compression = 'zlib')",
        "points_sha256": "TEXT",
        "raw_transfer_sha256": "TEXT",
        "raw_byte_length": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE dispersion_task_frames ADD COLUMN {name} {declaration}")

    if "points_json" in columns:
        rows = connection.execute(
            "SELECT id, points_json, sha256, byte_length FROM dispersion_task_frames ORDER BY id"
        ).fetchall()
        for row in rows:
            try:
                points = json.loads(row["points_json"])
                if not isinstance(points, list) or not points or any(
                    isinstance(point, bool) or not isinstance(point, int) or point < 0 or point > 65535
                    for point in points
                ):
                    raise ValueError("invalid uint16 point array")
                raw_points = struct.pack(f"<{len(points)}H", *points)
                blob = zlib.compress(raw_points, level=9)
            except (TypeError, ValueError, json.JSONDecodeError, struct.error) as exc:
                raise sqlite3.IntegrityError(
                    f"dispersion frame {row['id']} cannot be migrated to uint16_le"
                ) from exc
            connection.execute(
                "UPDATE dispersion_task_frames SET points_blob=?, points_count=?, points_sha256=?, "
                "raw_transfer_sha256=?, raw_byte_length=? WHERE id=?",
                (
                    blob,
                    len(points),
                    hashlib.sha256(raw_points).hexdigest(),
                    row["sha256"],
                    row["byte_length"],
                    row["id"],
                ),
            )
        connection.execute("ALTER TABLE dispersion_task_frames DROP COLUMN points_json")
        connection.execute("ALTER TABLE dispersion_task_frames DROP COLUMN sha256")
        connection.execute("ALTER TABLE dispersion_task_frames DROP COLUMN byte_length")

    for row in connection.execute(
        "SELECT id, points_blob, points_count, compression, points_sha256, raw_transfer_sha256, raw_byte_length FROM dispersion_task_frames"
    ).fetchall():
        try:
            raw_points = zlib.decompress(bytes(row["points_blob"])) if row["compression"] == "zlib" else b""
        except zlib.error as exc:
            raise sqlite3.IntegrityError(f"dispersion frame {row['id']} has invalid compressed points") from exc
        if (
            int(row["points_count"]) <= 0
            or len(raw_points) != int(row["points_count"]) * 2
            or hashlib.sha256(raw_points).hexdigest() != row["points_sha256"]
            or not row["raw_transfer_sha256"]
            or int(row["raw_byte_length"]) <= 0
        ):
            raise sqlite3.IntegrityError(f"dispersion frame {row['id']} violates the v12 storage contract")
