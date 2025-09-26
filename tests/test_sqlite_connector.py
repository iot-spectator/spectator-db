import os
import sqlite3
import tempfile

from spectatordb.connector import sqlite_connector


def test_init_and_del():
    db_fd, db_path = tempfile.mkstemp()
    try:
        connector = sqlite_connector.SQLiteConnector(db_path)
        assert os.path.exists(db_path)
        del connector  # Should close connection without error
    finally:
        os.close(db_fd)
        os.remove(db_path)


def test_execute_query_create_insert_select():
    db_fd, db_path = tempfile.mkstemp()
    try:
        connector = sqlite_connector.SQLiteConnector(db_path)
        # Create table
        connector.execute_query("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        # Insert row
        connector.execute_query("INSERT INTO test (name) VALUES (?)", ("Alice",))
        # Select row using direct sqlite3 for verification
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM test WHERE id=1")
        row = cur.fetchone()
        assert row[0] == "Alice"
        conn.close()
    finally:
        os.close(db_fd)
        os.remove(db_path)


def test_execute_query_with_params():
    db_fd, db_path = tempfile.mkstemp()
    try:
        connector = sqlite_connector.SQLiteConnector(db_path)
        connector.execute_query(
            "CREATE TABLE test (id INTEGER PRIMARY KEY, value INTEGER)"
        )
        for i in range(3):
            connector.execute_query("INSERT INTO test (value) VALUES (?)", (i,))
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM test")
        count = cur.fetchone()[0]
        assert count == 3
        conn.close()
    finally:
        os.close(db_fd)
        os.remove(db_path)
