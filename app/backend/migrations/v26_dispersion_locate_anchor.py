"""Keep a stable search origin independently of measured and saved positions."""
import sqlite3


def _migrate_v26(connection: sqlite3.Connection) -> None:
    connection.execute('ALTER TABLE dispersion_task_lines ADD COLUMN locate_anchor_position REAL')
    connection.execute('UPDATE dispersion_task_lines SET locate_anchor_position=COALESCE(located_position,expected_position)')
