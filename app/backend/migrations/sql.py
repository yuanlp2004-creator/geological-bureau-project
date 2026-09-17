"""SQLite schema helpers; never commit the caller transaction."""

import sqlite3


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a multi-statement script without sqlite3.executescript's implicit commit."""

    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        raise sqlite3.OperationalError("incomplete schema statement")


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _require_tables(connection: sqlite3.Connection, version: int, names: tuple[str, ...]) -> None:
    existing = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    missing = sorted(set(names) - existing)
    if missing:
        raise sqlite3.OperationalError(f"schema v{version} is missing tables: {', '.join(missing)}")
