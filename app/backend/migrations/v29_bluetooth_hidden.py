"""Device-list exclusions; never remove a Windows pairing or historical profile."""
import sqlite3


def _migrate_v29(connection: sqlite3.Connection) -> None:
    connection.execute('''CREATE TABLE device_bluetooth_hidden (
        address TEXT PRIMARY KEY CHECK(length(address)=12 AND address NOT GLOB '*[^0-9A-F]*'),
        name TEXT NOT NULL,
        hidden_at TEXT NOT NULL,
        actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL)''')
