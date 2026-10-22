"""Synthetic checkpoints for the geology schema family, isolated from user data."""

import pytest
from backend import db as database_module
from backend.db import Database
from backend.migrations import MIGRATIONS


def checkpoint(path, version):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(database_module, 'MIGRATIONS', tuple(m for m in MIGRATIONS if m[0] <= version))
        patch.setattr(database_module, 'SCHEMA_VERSION', version)
        Database(path).initialize()
    with Database(path).write() as connection:
        connection.execute("INSERT INTO app_settings VALUES ('station17-probe', '123', 'checkpoint')")
