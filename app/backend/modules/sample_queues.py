from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from functools import wraps
from pathlib import Path
from typing import Any

from ..db import Database, utc_now

OLD_STANDARDS = {f"S{i}": i for i in range(10)} | {f"S{chr(ord('A') + i)}": 10 + i for i in range(6)}


class SampleQueueError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, status_code: int = 422):
        super().__init__(message)
        self.code, self.message, self.details, self.status_code = code, message, details or {}, status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def normalize_name(value: str, name_length: int = 10) -> tuple[str, bool]:
    if name_length not in {10, 12, 20}:
        raise SampleQueueError("sample_name_length_invalid", "样号长度只能选择 12 位或 20 位")
    value = value.strip()
    if value in {",", ""}:
        return "", False
    upper = value.upper()
    if upper in OLD_STANDARDS:
        number = OLD_STANDARDS[upper]
        return f"S{number}", True
    if any(char in value for char in "\\/:*?<>|\t\r\n"):
        raise SampleQueueError("sample_name_invalid", "样品名包含不允许的字符")
    try:
        length = len(value.encode("gb18030"))
    except UnicodeEncodeError as exc:
        raise SampleQueueError("sample_name_encoding", "样品名无法按 GB18030 编码") from exc
    if name_length != 10 and len(value) > name_length:
        raise SampleQueueError("sample_name_too_long", f"样号超过 {name_length} 位", details={"limit": name_length})
    if name_length == 10 and length > 10:
        raise SampleQueueError("sample_name_too_long", "样品名超过 10 字节", details={"byte_length": length, "limit": 10})
    return value, False


def _sam_text(raw: bytes, encoding: str | None = None) -> tuple[str, str]:
    # Legacy SAM has no BOM. Its Windows code page wins over ambiguous valid UTF-8 bytes.
    encoding = encoding or ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'gb18030')
    try:
        return raw.decode(encoding), encoding
    except (UnicodeDecodeError, LookupError) as exc:
        raise SampleQueueError('sam_encoding_invalid','SAM 文件编码无法识别，请选择实际文件编码') from exc


def _parse_lines(raw: bytes, encoding: str | None = None) -> list[dict[str, Any]]:
    text, _ = _sam_text(raw, encoding)
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            errors.append({"line": line_no, "original": line, "reason": "missing_tab"})
            continue
        name_raw, rep_raw = parts
        try:
            name, normalized = normalize_name(name_raw)
            repeats = int(rep_raw.strip() or 0)
            if repeats < 0 or repeats > 10:
                raise ValueError
        except (ValueError, SampleQueueError) as exc:
            reason = exc.code if isinstance(exc, SampleQueueError) else "repeat_invalid"
            errors.append({"line": line_no, "original": line, "reason": reason})
            continue
        records.append(
            {
                "source_name": name_raw.strip(),
                "name": name,
                "normalized_standard": normalized,
                "repeats": repeats,
                "line": line_no,
            }
        )
    if errors:
        raise SampleQueueError("sam_import_invalid", "SAM 导入包含无效行", details={"errors": errors})
    if len(records) > 1000:
        raise SampleQueueError("sample_queue_too_large", "样品记录超过 1000 条")
    return records


def _queue_mutation(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except sqlite3.IntegrityError as exc:
            if "queue item in use" not in str(exc):
                raise
            raise SampleQueueError(
                "queue_item_in_use", "队列项已关联采集，不能删除或修改采前参数", status_code=409
            ) from exc

    return guarded


class SampleQueueService:
    def __init__(self, database: Database):
        self.database = database

    def _items(self, db, queue_id: int) -> list[dict[str, Any]]:
        rows = db.execute("SELECT * FROM sample_queue_items WHERE queue_id=? ORDER BY position", (queue_id,)).fetchall()
        return [dict(row) for row in rows]

    def get(self, queue_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            queue = db.execute("SELECT * FROM sample_queues WHERE id=?", (queue_id,)).fetchone()
            if not queue:
                raise SampleQueueError("queue_not_found", "队列不存在", status_code=404)
            result = dict(queue)
            option = db.execute("SELECT name_length FROM sample_queue_options WHERE queue_id=?", (queue_id,)).fetchone()
            result["name_length"] = int(option[0]) if option else 10
            result["items"] = self._items(db, queue_id)
            result["record_count"] = len(result["items"])
            result["expanded_bands"] = sum(item["expanded_bands"] for item in result["items"])
            return result

    def get_item(self, queue_id: int, item_id: int) -> dict[str, Any]:
        """Public application-service lookup used by acquisition workflows."""

        with self.database.read() as db:
            row = db.execute(
                "SELECT * FROM sample_queue_items WHERE id=? AND queue_id=?",
                (item_id, queue_id),
            ).fetchone()
            if row is None:
                raise SampleQueueError("queue_item_not_found", "队列项不存在", status_code=404)
            return dict(row)

    def list(self) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM sample_queues ORDER BY updated_at DESC").fetchall()]
        return [self.get(queue_id) for queue_id in ids]

    def create(
        self, name: str, items: list[dict[str, Any]], actor: int | None, source_sha256: str | None = None,
        *, name_length: int | None = None
    ) -> dict[str, Any]:
        now = utc_now()
        normalized_items = self._validate_items(items, name_length or 10)
        with self.database.write() as db:
            cur = db.execute(
                "INSERT INTO sample_queues(name, source_sha256, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name.strip() or "未命名队列", source_sha256, actor, now, now),
            )
            queue_id = int(cur.lastrowid)
            db.execute("INSERT INTO sample_queue_options VALUES (?,?)", (queue_id, name_length or 10))
            self._replace_items(db, queue_id, normalized_items, now)
            self._audit(db, actor, "sample_queue.create", queue_id, {"record_count": len(normalized_items)})
        return self.get(queue_id)

    @_queue_mutation
    def update(
        self, queue_id: int, items: list[dict[str, Any]], actor: int | None, *, name_length: int | None = None
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.write() as db:
            if not db.execute("SELECT 1 FROM sample_queues WHERE id=?", (queue_id,)).fetchone():
                raise SampleQueueError("queue_not_found", "队列不存在", status_code=404)
            option = db.execute("SELECT name_length FROM sample_queue_options WHERE queue_id=?", (queue_id,)).fetchone()
            limit = name_length or (int(option[0]) if option else 10)
            normalized_items = self._validate_items(items, limit)
            for row in db.execute("SELECT post_name FROM sample_queue_items WHERE queue_id=?", (queue_id,)):
                if row[0]:
                    normalize_name(row[0], limit)
            db.execute(
                "INSERT INTO sample_queue_options VALUES (?,?) ON CONFLICT(queue_id) DO UPDATE SET name_length=excluded.name_length",
                (queue_id, limit),
            )
            self._replace_items(db, queue_id, normalized_items, now)
            db.execute("UPDATE sample_queues SET updated_at=? WHERE id=?", (now, queue_id))
            self._audit(db, actor, "sample_queue.update", queue_id, {"record_count": len(normalized_items)})
        return self.get(queue_id)

    def rename(self, queue_id: int, item_id: int, post_name: str, actor: int | None) -> dict[str, Any]:
        name, _ = normalize_name(post_name, self.get(queue_id)["name_length"])
        if not name:
            raise SampleQueueError("sample_name_invalid", "采集后名称不能为空")
        now = utc_now()
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM sample_queue_items WHERE id=? AND queue_id=?", (item_id, queue_id)
            ).fetchone()
            if not row:
                raise SampleQueueError("queue_item_not_found", "队列项不存在", status_code=404)
            db.execute("UPDATE sample_queue_items SET post_name=?, updated_at=? WHERE id=?", (name, now, item_id))
            db.execute("UPDATE sample_queues SET updated_at=? WHERE id=?", (now, queue_id))
            self._audit(
                db,
                actor,
                "sample_queue.rename",
                item_id,
                {
                    "queue_id": queue_id,
                    "from": row["post_name"] or row["pre_name"],
                    "to": name,
                    "spectrum_hash": row["spectrum_hash"],
                },
            )
        return self.get(queue_id)

    def rename_linked_item(
        self,
        queue_id: int,
        item_id: int,
        post_name: str,
        actor: int | None,
        *,
        connection: sqlite3.Connection,
        name_length: int | None = None,
    ) -> str:
        """Rename a queue item inside a caller-owned acquisition transaction."""

        option = connection.execute("SELECT name_length FROM sample_queue_options WHERE queue_id=?", (queue_id,)).fetchone()
        limit = name_length or (int(option[0]) if option else 10)
        name, _ = normalize_name(post_name, limit)
        # 缩短长度时检查队列所有名称，不能截断其他已录入样号。
        # 切换长度模式前核对队列全部现有名称，不能只让被改名的一项满足新限制。
        for item in connection.execute("SELECT pre_name,post_name FROM sample_queue_items WHERE queue_id=?", (queue_id,)):
            normalize_name(item[0], limit)
            if item[1]:
                normalize_name(item[1], limit)
        connection.execute(
            "INSERT INTO sample_queue_options VALUES (?,?) ON CONFLICT(queue_id) DO UPDATE SET name_length=excluded.name_length",
            (queue_id, limit),
        )
        if not name:
            raise SampleQueueError("sample_name_invalid", "采集后名称不能为空")
        row = connection.execute(
            "SELECT * FROM sample_queue_items WHERE id=? AND queue_id=?",
            (item_id, queue_id),
        ).fetchone()
        if row is None:
            raise SampleQueueError("queue_item_not_found", "队列项不存在", status_code=404)
        now = utc_now()
        # 使用采集调用方连接更新后命名和审计；这里不自行提交，保证采集改名能一起回滚。
        connection.execute(
            "UPDATE sample_queue_items SET post_name=?, updated_at=? WHERE id=?",
            (name, now, item_id),
        )
        connection.execute("UPDATE sample_queues SET updated_at=? WHERE id=?", (now, queue_id))
        self._audit(
            connection,
            actor,
            "sample_queue.rename",
            item_id,
            {
                "queue_id": queue_id,
                "from": row["post_name"] or row["pre_name"],
                "to": name,
                "spectrum_hash": row["spectrum_hash"],
            },
        )
        return name

    def attach_acquisition(
        self,
        queue_id: int,
        item_id: int,
        spectrum_hash: str,
        actor: int | None,
        *,
        connection: sqlite3.Connection,
    ) -> None:
        """Attach one completed S13 acquisition without exposing queue tables."""

        fingerprint = str(spectrum_hash).lower()
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise SampleQueueError("spectrum_hash_invalid", "采集数据哈希无效")
        row = connection.execute(
            "SELECT * FROM sample_queue_items WHERE id=? AND queue_id=?",
            (item_id, queue_id),
        ).fetchone()
        if row is None:
            raise SampleQueueError("queue_item_not_found", "队列项不存在", status_code=404)
        if row["spectrum_hash"] not in (None, fingerprint):
            raise SampleQueueError(
                "queue_item_already_acquired",
                "队列项已经关联另一份采集数据",
                details={"existing_hash": row["spectrum_hash"]},
                status_code=409,
            )
        now = utc_now()
        connection.execute(
            "UPDATE sample_queue_items SET spectrum_hash=?, updated_at=? WHERE id=?",
            (fingerprint, now, item_id),
        )
        remaining = connection.execute(
            "SELECT COUNT(*) FROM sample_queue_items WHERE queue_id=? AND spectrum_hash IS NULL",
            (queue_id,),
        ).fetchone()[0]
        queue_status = "completed" if remaining == 0 else "ready"
        connection.execute(
            "UPDATE sample_queues SET status=?, updated_at=? WHERE id=?",
            (queue_status, now, queue_id),
        )
        self._audit(
            connection,
            actor,
            "sample_queue.acquisition.attach",
            item_id,
            {"queue_id": queue_id, "spectrum_hash": fingerprint, "queue_status": queue_status},
        )

    @_queue_mutation
    def delete_item(self, queue_id: int, item_id: int, actor: int | None) -> dict[str, Any]:
        now = utc_now()
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM sample_queue_items WHERE id=? AND queue_id=?", (item_id, queue_id)
            ).fetchone()
            if not row:
                raise SampleQueueError("queue_item_not_found", "队列项不存在", status_code=404)
            self._assert_removable(db, row)
            db.execute("DELETE FROM sample_queue_items WHERE id=?", (item_id,))
            self._renumber(db, queue_id)
            db.execute("UPDATE sample_queues SET updated_at=? WHERE id=?", (now, queue_id))
            self._audit(
                db, actor, "sample_queue.item.delete", item_id, {"queue_id": queue_id, "pre_name": row["pre_name"]}
            )
        return self.get(queue_id)

    @_queue_mutation
    def clear(self, queue_id: int, actor: int | None) -> dict[str, Any]:
        now = utc_now()
        with self.database.write() as db:
            if not db.execute("SELECT 1 FROM sample_queues WHERE id=?", (queue_id,)).fetchone():
                raise SampleQueueError("queue_not_found", "队列不存在", status_code=404)
            for item in self._items(db, queue_id):
                self._assert_removable(db, item)
            db.execute("DELETE FROM sample_queue_items WHERE queue_id=?", (queue_id,))
            db.execute("UPDATE sample_queues SET updated_at=? WHERE id=?", (now, queue_id))
            self._audit(db, actor, "sample_queue.clear", queue_id, {})
        return self.get(queue_id)

    def import_sam(self, path: Path, actor: int | None, queue_name: str | None = None) -> dict[str, Any]:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise SampleQueueError("sam_source_unreadable", "无法读取 SAM 文件", details={"path": str(path)}) from exc
        return self.import_bytes(
            raw, actor, queue_name or path.stem, str(path.resolve()), source_mtime_ms=int(path.stat().st_mtime * 1000)
        )

    @_queue_mutation
    def import_bytes(
        self,
        raw: bytes,
        actor: int | None,
        queue_name: str,
        source_name: str = "upload.sam",
        *,
        source_mtime_ms: int | None = None,
        encoding: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = hashlib.sha256(raw).hexdigest()
        records = _parse_lines(raw, encoding)
        items = [
            {"source_name": record["source_name"], "pre_name": record["name"], "repeats": record["repeats"]}
            for record in records
        ]
        # 解析和全部条目校验先完成，再打开写事务；非法文件不能替换现有队列。
        normalized_items = self._validate_items(items)
        now = utc_now()
        # 哈希检查、数据变更与两类审计必须在同一写事务内完成。
        with self.database.write() as db:
            db.execute("BEGIN IMMEDIATE")
            # 源文件内容哈希用于重复导入识别，重复文件返回既有队列而不重复写条目。
            existing_hash = db.execute("SELECT id FROM sample_queues WHERE source_sha256=?", (fingerprint,)).fetchone()
            if existing_hash:
                queue_id = int(existing_hash[0])
            else:
                existing = db.execute(
                    "SELECT id FROM sample_queues WHERE name=? AND status='draft' ORDER BY id", (queue_name,)
                ).fetchone()
                if existing:
                    queue_id = int(existing[0])
                    self._replace_items(db, queue_id, normalized_items, now)
                    db.execute(
                        "UPDATE sample_queues SET source_sha256=?, updated_at=? WHERE id=?",
                        (fingerprint, now, queue_id),
                    )
                    action = "sample_queue.update"
                else:
                    cur = db.execute(
                        "INSERT INTO sample_queues(name, source_sha256, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (queue_name.strip() or "未命名队列", fingerprint, actor, now, now),
                    )
                    queue_id = int(cur.lastrowid)
                    self._replace_items(db, queue_id, normalized_items, now)
                    action = "sample_queue.create"
                self._audit(db, actor, action, queue_id, {"record_count": len(records)})
                _, encoding = _sam_text(raw, encoding)
                self._audit(
                    db,
                    actor,
                    "sample_queue.sam_import",
                    queue_id,
                    {
                        "path": source_name,
                        "sha256": fingerprint,
                        "bytes": len(raw),
                        "modified_at_ms": source_mtime_ms,
                        "encoding": encoding,
                        "parser_version": "sam-v1",
                        "records": len(records),
                        "expanded_bands": sum(item["expanded_bands"] for item in normalized_items),
                        "normalized_standards": sum(item["normalized_standard"] for item in records),
                    },
                )
        return self.get(queue_id)

    def export_sam(self, queue_id: int) -> tuple[bytes, str]:
        queue = self.get(queue_id)
        # 旧 SAM 名称槽只有 10 字节，超长新版样号不得写成不兼容文件。
        for item in queue["items"]:
            normalize_name(item["pre_name"])
        output = "".join(f"{item['pre_name']:<8}\t{item['repeats']}\r\n" for item in queue["items"])
        return output.encode("gb18030"), hashlib.sha256(output.encode("gb18030")).hexdigest()

    @staticmethod
    def _validate_items(items: list[dict[str, Any]], name_length: int = 10) -> list[dict[str, Any]]:
        normalize_name("", name_length)
        if len(items) > 1000:
            raise SampleQueueError("sample_queue_too_large", "样品记录超过 1000 条")
        normalized = []
        for item in items:
            name, normalized_standard = normalize_name(str(item.get("pre_name", item.get("name", ""))), name_length)
            if item.get("post_name"):
                normalize_name(str(item["post_name"]), name_length)
            repeats = int(item.get("repeats", 0))
            if repeats < 0 or repeats > 10:
                raise SampleQueueError("repeat_invalid", "重复次数必须在 0 到 10 之间")
            normalized.append(
                {
                    "id": item.get("id"),
                    "source_name": str(item.get("source_name", name)),
                    "pre_name": name,
                    "repeats": repeats,
                    "expanded_bands": repeats if repeats else 1,
                    "post_name": item.get("post_name"),
                    "spectrum_hash": item.get("spectrum_hash"),
                    "normalized_standard": normalized_standard,
                }
            )
        return normalized

    @staticmethod
    def _assert_removable(db, item) -> None:
        if item["spectrum_hash"]:
            raise SampleQueueError("queue_item_in_use", "队列项已关联采集，不能删除、清空或替换", status_code=409)

    @staticmethod
    def _replace_items(db, queue_id: int, items: list[dict[str, Any]], now: str) -> None:
        previous = {
            row["id"]: row for row in db.execute("SELECT * FROM sample_queue_items WHERE queue_id=?", (queue_id,))
        }
        ids = [item["id"] for item in items if item.get("id") is not None]
        if len(ids) != len(set(ids)) or any(identifier not in previous for identifier in ids):
            raise SampleQueueError("queue_item_identity_invalid", "队列项 ID 重复或不属于当前队列")
        for identifier, old in previous.items():
            if identifier not in ids:
                SampleQueueService._assert_removable(db, old)
                db.execute("DELETE FROM sample_queue_items WHERE id=?", (identifier,))
        # Move retained rows beyond the final range before applying the requested order.
        offset = max([row["position"] for row in previous.values()] + [0]) + len(items) + 1
        db.execute("UPDATE sample_queue_items SET position=position+? WHERE queue_id=?", (offset, queue_id))
        for position, item in enumerate(items):
            identifier = item.get("id")
            if identifier is None:
                db.execute(
                    (
                        "INSERT INTO sample_queue_items(queue_id,position,source_name,pre_name,post_name,"
                        "repeats,expanded_bands,spectrum_hash,created_at,updated_at) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?)"
                    ),
                    (
                        queue_id,
                        position,
                        item["source_name"],
                        item["pre_name"],
                        item.get("post_name"),
                        item["repeats"],
                        item["expanded_bands"],
                        item.get("spectrum_hash"),
                        now,
                        now,
                    ),
                )
            else:
                old = previous[identifier]
                if old["spectrum_hash"] and (item["pre_name"] != old["pre_name"] or item["repeats"] != old["repeats"]):
                    raise SampleQueueError(
                        "queue_item_in_use", "已关联采集项仅可排序；改名请使用采后命名", status_code=409
                    )
                db.execute(
                    "UPDATE sample_queue_items SET position=?,pre_name=?,repeats=?,expanded_bands=?,updated_at=? WHERE id=?",
                    (position, item["pre_name"], item["repeats"], item["expanded_bands"], now, identifier),
                )

    @staticmethod
    def _renumber(db, queue_id: int) -> None:
        rows = db.execute(
            "SELECT id FROM sample_queue_items WHERE queue_id=? ORDER BY position, id", (queue_id,)
        ).fetchall()
        for position, row in enumerate(rows):
            db.execute("UPDATE sample_queue_items SET position=? WHERE id=?", (position, row["id"]))

    @staticmethod
    def _audit(db, actor: int | None, action: str, target_id: int, details: dict[str, Any]) -> None:
        db.execute(
            (
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                "details_json, created_at) VALUES (?, ?, 'sample_queue', ?, ?, ?)"
            ),
            (actor, action, target_id, json.dumps(details, ensure_ascii=False, separators=(",", ":")), utc_now()),
        )

    def release_acquisition(self, queue_id: int, item_id: int, fingerprint: str | None, *, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT spectrum_hash FROM sample_queue_items WHERE queue_id=? AND id=?", (queue_id, item_id)).fetchone()
        if row is not None and row[0] == fingerprint and fingerprint is not None:
            connection.execute("UPDATE sample_queue_items SET spectrum_hash=NULL, updated_at=? WHERE id=?", (utc_now(), item_id))
            connection.execute("UPDATE sample_queues SET status='ready', updated_at=? WHERE id=?", (utc_now(), queue_id))
