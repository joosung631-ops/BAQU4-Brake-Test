"""Integration check in an isolated ROS domain; does not command vehicle topics."""

import base64
import json
import os
import socket
import struct
import threading
import time
from urllib.parse import urlparse

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String


def run():
    rclpy.init()
    node = Node("dashboard_smoke", enable_rosout=False, start_parameter_services=False)
    publisher = node.create_publisher(String, "/dashboard_check/active", 10)
    silent = node.create_publisher(String, "/dashboard_check/silent", 10)
    timer = node.create_timer(0.1, lambda: publisher.publish(String(data="test")))
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    url = urlparse(os.environ["DASHBOARD_URL"])
    sock = socket.create_connection((url.hostname, url.port), timeout=5)
    stream = sock.makefile("rb")
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(("GET /ws/traffic HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                      f"Sec-WebSocket-Key: {key}\r\n\r\n").encode())
        assert b"101 Switching Protocols" in stream.readline()
        while stream.readline() != b"\r\n":
            pass

        def receive():
            header = stream.read(2)
            assert header[0] == 0x81, header
            length = header[1] & 127
            if length == 126:
                length = struct.unpack("!H", stream.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", stream.read(8))[0]
            data = json.loads(stream.read(length))
            data["topics"] = [row for group in data["topic_groups"] for row in group["topics"] if row["received"]]
            return data

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            topics = {row["name"]: row["hz"] for row in receive()["topics"]}
            assert "/dashboard_check/silent" not in topics, topics
            hz = topics.get("/dashboard_check/active")
            if hz is not None and 8 <= hz <= 12:
                print(f"Actual ROS -> collector -> HTTP -> WebSocket: {hz} Hz", flush=True)
                break
        else:
            raise AssertionError("Published topic did not arrive at dashboard")

        timer.cancel()  # Keep publisher registered, but stop real messages.
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            topics = receive()["topics"]
            if not topics:
                print("Silent publisher excluded; stopped messages expired to empty list", flush=True)
                break
        else:
            raise AssertionError("Stopped topic remained visible")
    finally:
        stream.close()
        sock.close()
        executor.shutdown(timeout_sec=2)
        worker.join(timeout=2)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    run()
