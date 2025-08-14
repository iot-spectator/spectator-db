from spectatordb import sql_connector
from spectatordb import storage


class SpectatorDB:

    def __init__(
        self, storage: storage.Storage, sql_connector: sql_connector.SQLiteConnector
    ):
        """Initialize the SpectatorDB with a storage backend.

        Parameters
        ----------
        storage : storage.Storage
            An instance of a storage backend that implements the Storage interface.
        sql_connector : sql_connector.SQLiteConnector
            An instance of the SQLiteConnector for database operations.
        """
        self._storage = storage
        self._sql_connector = sql_connector
