"""Database connectivity: the platform requires PostgreSQL 17 (ADR-0002, ADR-0006)."""

import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_is_postgresql_17() -> None:
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        row = cursor.fetchone()
    assert row is not None
    major = int(row[0]) // 10000
    assert major == 17, f"expected PostgreSQL 17, connected to major version {major}"
