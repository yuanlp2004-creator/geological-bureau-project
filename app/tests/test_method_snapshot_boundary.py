import ast
import hashlib
import json
from pathlib import Path

import pytest

from backend.modules.methods import MethodService, MethodDomainError
from tests.test_s18_postprocessing import _fixture, _seed_method_curve


def test_snapshots_preserve_draft_old_version_and_same_transaction(tmp_path):
    database, _ = _fixture(tmp_path)
    method_id, published_id, _ = _seed_method_curve(database)
    methods = MethodService(database)
    with database.write() as db:
        draft_id = db.execute(
            "INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (?,2,'draft',?,'draft-time')",
            (method_id, '{"conditions": {"frame_count": 7}, "lines": []}'),
        ).lastrowid
        reader = methods.bind_snapshots(db)
        statements = []
        db.set_trace_callback(statements.append)
        draft = reader.for_print(method_id)
        assert draft.version_id == draft_id and draft.state == "draft"
        assert len(statements) == 2
        assert reader.for_print(method_id, 1).version_id == published_id
        assert reader.by_id(draft_id, published_only=True) is None
        assert reader.by_id(draft_id).payload["conditions"]["frame_count"] == 7
        assert reader.by_id(98765) is None
        with pytest.raises(MethodDomainError) as missing_version:
            reader.for_print(method_id, 99)
        assert missing_version.value.code == "method_version_not_found"
        assert missing_version.value.status_code == 404
        statements.clear()
        snapshots = reader.by_ids([published_id, draft_id, published_id])
        assert len(statements) == 1 and set(snapshots) == {published_id, draft_id}
        db.set_trace_callback(None)
        db.execute("UPDATE methods SET status='deleted' WHERE id=?", (method_id,))
        with pytest.raises(MethodDomainError) as deleted:
            reader.for_print(method_id)
        assert deleted.value.code == "method_not_found"
        # Analysis may read an already referenced version even after soft deletion.
        assert reader.by_id(published_id, published_only=True).method.status == "deleted"
    # Detached values outlive the connection and cannot alter persisted content.
    draft.payload["conditions"]["frame_count"] = 999
    with database.read() as db:
        fresh = methods.bind_snapshots(db).by_id(draft_id)
        raw = db.execute("SELECT payload_json FROM method_versions WHERE id=?", (draft_id,)).fetchone()[0]
    assert fresh.payload["conditions"]["frame_count"] == 7
    assert fresh.content_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_selected_consumers_do_not_read_method_tables_or_private_snapshots():
    backend = Path(__file__).resolve().parents[1] / "backend/modules"
    files = [backend / "method_printing/service.py", *(backend / "analysis").glob("*.py"),
             *(backend / "postprocessing").glob("*.py")]
    import re
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(?:FROM|JOIN)\s+(?:methods|method_versions)\b", source, re.I), path
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"_latest_row", "_version_dict"}, path


def test_acquisition_import_owns_sql_and_cannot_open_or_commit_transactions():
    backend = Path(__file__).resolve().parents[1] / "backend/modules"
    source = (backend / "postprocessing/conversion.py").read_text(encoding="utf-8")
    assert "INSERT INTO acquisition_" not in source
    assert "UPDATE acquisition_" not in source
    tree = ast.parse((backend / "acquisition_import.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "Database"
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"write", "commit", "connect", "rollback"}
