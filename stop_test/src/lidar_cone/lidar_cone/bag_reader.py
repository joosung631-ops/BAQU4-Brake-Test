"""Read sqlite3/zstd bags without modifying the bag directory or replaying ROS."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import subprocess
import tempfile

import numpy as np
import yaml


@contextmanager
def open_bag(bag_directory):
    directory = Path(bag_directory).resolve()
    metadata = yaml.safe_load((directory / "metadata.yaml").read_text())["rosbag2_bagfile_information"]
    if metadata["storage_identifier"] != "sqlite3":
        raise ValueError("This reader supports sqlite3 rosbag2 storage")
    mode = str(metadata.get("compression_mode", "")).upper()
    if mode not in ("", "NONE", "FILE"):
        raise ValueError("Only uncompressed or FILE/zstd bags are supported")
    compression = metadata.get("compression_format", "")
    if mode == "FILE" and compression != "zstd":
        raise ValueError("Unsupported file compression: " + compression)
    paths = metadata["relative_file_paths"]
    if not paths:
        raise ValueError("Bag has no storage files")
    # Reject metadata paths escaping the selected directory.
    sources = [(directory / name).resolve() for name in paths]
    if any(directory not in path.parents for path in sources):
        raise ValueError("Bag storage path is outside the bag directory")
    with tempfile.TemporaryDirectory(prefix="lidar-cones-") as temporary:
        connections = []
        try:
            for i, source in enumerate(sources):
                database = source
                if mode == "FILE":
                    database = Path(temporary) / (str(i) + ".db3")
                    with database.open("wb") as stream:
                        subprocess.run(["zstd", "-d", "-c", str(source)], stdout=stream, check=True)
                connection = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
                connection.execute("PRAGMA query_only = ON")
                connections.append(connection)
            yield BagReader(connections, metadata)
        finally:
            for connection in connections:
                connection.close()


class BagReader:
    def __init__(self, connections, metadata):
        self.connections = connections
        self.metadata = metadata
        self.start_ns = int(metadata["starting_time"]["nanoseconds_since_epoch"])
        self.topic_maps = [dict(connection.execute("SELECT name, id FROM topics")) for connection in connections]
        for connection in connections:
            topic = connection.execute("SELECT type FROM topics WHERE name='/lidar/points'").fetchone()
            if topic and topic[0] != "sensor_msgs/msg/PointCloud2":
                raise ValueError("/lidar/points is not sensor_msgs/msg/PointCloud2")
        camera = []
        for i, (connection, topics) in enumerate(zip(connections, self.topic_maps)):
            camera_id = topics.get("/camera/image_raw/compressed")
            if camera_id is not None:
                camera.extend((stamp, i, message_id) for stamp, message_id in connection.execute(
                    "SELECT timestamp, id FROM messages WHERE topic_id=?", (camera_id,),
                ))
        self.camera = sorted(camera)
        self.camera_times = np.array([entry[0] for entry in self.camera], dtype=np.int64)

    def clouds(self, start_s=0.0, duration_s=None, stride=1):
        """Yield original blobs in recording order, including split bag files."""
        import heapq
        lower = self.start_ns + round(start_s * 1e9)
        upper = lower + round(duration_s * 1e9) if duration_s is not None else 2 ** 63 - 1
        streams = []
        for connection, topics in zip(self.connections, self.topic_maps):
            topic_id = topics.get("/lidar/points")
            if topic_id is not None:
                streams.append(connection.execute(
                    "SELECT timestamp, data FROM messages WHERE topic_id=? AND timestamp>=? AND timestamp<? ORDER BY timestamp, id",
                    (topic_id, lower, upper),
                ))
        for index, row in enumerate(heapq.merge(*streams, key=lambda row: row[0])):
            if index % stride == 0:
                yield row

    def nearest_camera(self, timestamp_ns):
        if not self.camera:
            return None, None
        position = int(np.searchsorted(self.camera_times, timestamp_ns))
        candidates = self.camera[max(0, position - 1):min(len(self.camera), position + 1)]
        stamp, connection_index, message_id = min(candidates, key=lambda entry: abs(entry[0] - timestamp_ns))
        blob, = self.connections[connection_index].execute("SELECT data FROM messages WHERE id=?", (message_id,)).fetchone()
        return blob, (stamp - timestamp_ns) / 1e9
