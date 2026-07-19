"""Generate Bag Doctor's deterministic synthetic ROS 2 MCAP fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from rosbags.rosbag2 import StoragePlugin, Writer
from rosbags.typesys import Stores, get_typestore

NANOSECONDS = 1_000_000_000
DEMO_DURATION_SECONDS = 14
SCAN_SILENCE_START_SECONDS = 5
SCAN_SILENCE_END_SECONDS = 9


def generate_demo_bag(destination: Path, *, storage_plugin: StoragePlugin = StoragePlugin.MCAP) -> Path:
    """Create a 14-second bag with a four-second mid-recording /scan outage."""
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)

    typestore = get_typestore(Stores.ROS2_HUMBLE)
    types = typestore.types
    Time = types["builtin_interfaces/msg/Time"]
    Header = types["std_msgs/msg/Header"]
    LaserScan = types["sensor_msgs/msg/LaserScan"]
    Odometry = types["nav_msgs/msg/Odometry"]
    TFMessage = types["tf2_msgs/msg/TFMessage"]
    Point = types["geometry_msgs/msg/Point"]
    Quaternion = types["geometry_msgs/msg/Quaternion"]
    Pose = types["geometry_msgs/msg/Pose"]
    PoseWithCovariance = types["geometry_msgs/msg/PoseWithCovariance"]
    Vector3 = types["geometry_msgs/msg/Vector3"]
    Twist = types["geometry_msgs/msg/Twist"]
    TwistWithCovariance = types["geometry_msgs/msg/TwistWithCovariance"]
    Transform = types["geometry_msgs/msg/Transform"]
    TransformStamped = types["geometry_msgs/msg/TransformStamped"]

    def header(timestamp: int, frame: str):
        return Header(Time(timestamp // NANOSECONDS, timestamp % NANOSECONDS), frame)

    def scan(timestamp: int):
        return LaserScan(
            header(timestamp, "laser"), -1.57, 1.57, 0.01, 0.0, 0.1, 0.12, 12.0,
            np.full(315, 2.0, dtype=np.float32), np.array([], dtype=np.float32),
        )

    covariance = np.zeros(36, dtype=np.float64)

    def odom(timestamp: int):
        pose = PoseWithCovariance(Pose(Point(timestamp / NANOSECONDS * 0.1, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0)), covariance)
        twist = TwistWithCovariance(Twist(Vector3(0.1, 0.0, 0.0), Vector3(0.0, 0.0, 0.0)), covariance)
        return Odometry(header(timestamp, "odom"), "base_link", pose, twist)

    def tf(timestamp: int):
        transform = TransformStamped(
            header(timestamp, "odom"), "base_link",
            Transform(Vector3(timestamp / NANOSECONDS * 0.1, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0)),
        )
        return TFMessage([transform])

    with Writer(destination, version=9, storage_plugin=storage_plugin) as writer:
        connections = {
            "/scan": writer.add_connection("/scan", "sensor_msgs/msg/LaserScan", typestore=typestore),
            "/odom": writer.add_connection("/odom", "nav_msgs/msg/Odometry", typestore=typestore),
            "/tf": writer.add_connection("/tf", "tf2_msgs/msg/TFMessage", typestore=typestore),
        }
        schedules = [
            ("/scan", 10, scan),
            ("/odom", 30, odom),
            ("/tf", 10, tf),
        ]
        events = []
        for topic, rate, factory in schedules:
            for index in range(DEMO_DURATION_SECONDS * rate + 1):
                timestamp = round(index * NANOSECONDS / rate)
                if topic == "/scan" and SCAN_SILENCE_START_SECONDS * NANOSECONDS <= timestamp < SCAN_SILENCE_END_SECONDS * NANOSECONDS:
                    continue
                events.append((timestamp, topic, factory))
        for timestamp, topic, factory in sorted(events, key=lambda event: (event[0], event[1])):
            payload = typestore.serialize_cdr(factory(timestamp), connections[topic].msgtype)
            writer.write(connections[topic], timestamp, payload)

    return destination


if __name__ == "__main__":
    generate_demo_bag(Path(__file__).parent / "data" / "failed_robot_demo")
    generate_demo_bag(Path(__file__).parent / "data" / "failed_robot_sqlite_demo", storage_plugin=StoragePlugin.SQLITE3)
