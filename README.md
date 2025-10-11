# SpectatorDB

SpectatorDB is a Python library for managing media files (images and videos) and their metadata. It stores media files in the local file system and tracks metadata in a SQLite database, making it easy to organize, retrieve, and manage your media assets programmatically.

## Requirements

- Python 3.13+

## Installation

Clone the repository and install dependencies:

```bash
# Clone the repository
$ git clone https://github.com/iot-spectator/spectator-db.git
$ cd spectator-db
$ python -m pip install -r requirements.txt
```

## Usage

### Basic Example

```python
from spectatordb.spectatordb import SpectatorDB, MediaType
from spectatordb.connector.sqlite_connector import SQLiteConnector
from spectatordb.storage.local_storage import LocalStorage
import pathlib

# Set up storage and database connector
storage = LocalStorage("./media")
sql_connector = SQLiteConnector("./spectator.db")

# Initialize SpectatorDB
spectator_db = SpectatorDB(storage, sql_connector)

# Insert an image file
image_path = pathlib.Path("/path/to/image.jpg")
spectator_db.insert(image_path, MediaType.IMAGE)

# Insert a video file
video_path = pathlib.Path("/path/to/video.mp4")
spectator_db.insert(video_path, MediaType.VIDEO)
```
