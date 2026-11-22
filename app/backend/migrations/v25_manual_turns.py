"""Standalone manual turns have no inferred wavelength or method association."""
import sqlite3


def _migrate_v25(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE hardware_tasks ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'automatic' CHECK(execution_mode IN ('automatic','manual'))")
    # Rebuild with foreign keys disabled by the migration runner, preserving IDs,
    # dependent evidence, indexes and immutable-plan triggers in one transaction.
    schema = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='hardware_plan_steps'").fetchone()[0]
    schema = schema.replace('hardware_plan_steps', 'hardware_plan_steps_new', 1).replace('wavelength_nm REAL NOT NULL', 'wavelength_nm REAL')
    dependents = [row[0] for row in connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='hardware_plan_steps' AND type IN ('index','trigger') AND sql IS NOT NULL")]
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='hardware_plan_steps'").fetchone()
    connection.execute(schema)
    connection.execute('INSERT INTO hardware_plan_steps_new SELECT * FROM hardware_plan_steps')
    connection.execute('DROP TABLE hardware_plan_steps')
    connection.execute('ALTER TABLE hardware_plan_steps_new RENAME TO hardware_plan_steps')
    if sequence:
        connection.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='hardware_plan_steps'", (sequence[0],))
    for sql in dependents:
        connection.execute(sql)
    connection.execute("CREATE TRIGGER hardware_execution_mode_immutable BEFORE UPDATE OF execution_mode ON hardware_tasks BEGIN SELECT RAISE(ABORT,'hardware execution mode is immutable'); END")


_migrate_v25.requires_foreign_keys_off = True
