import sqlite3


class SQLiteConnector:
    """A class to handle SQLite database connections and operations."""

    def __init__(self, db_path: str):
        """Initialize the SQLite connector with a database path.

        Parameters
        ----------
        db_path : str
            The file path to the SQLite database.
        """
        self._db_path = db_path
        self._connection = sqlite3.connect(self._db_path)
        self._cursor = self._connection.cursor()

    def execute_query(self, query: str, params: tuple = ()):
        """Execute a SQL query with optional parameters.

        Parameters
        ----------
        query : str
            The SQL query to execute.
        params : tuple, optional
            Parameters to bind to the query.
        """
        self._cursor.execute(query, params)
        self._connection.commit()
