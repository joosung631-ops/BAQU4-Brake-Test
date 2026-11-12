from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lidar_cone.pointcloud import decode_cloud


@pytest.mark.parametrize("bigendian", [False, True])
def test_padding_endianness_and_field_counts(bigendian):
    fields = [
        SimpleNamespace(name=name, offset=offset, datatype=datatype, count=count)
        for name, offset, datatype, count in [
            ("x", 0, 7, 1), ("y", 8, 8, 1), ("z", 20, 7, 1),
            ("extra", 24, 4, 3), ("ring", 32, 4, 1), ("t", 36, 6, 1),
        ]
    ]
    data = bytearray(224)
    endian = ">" if bigendian else "<"
    dtype = np.dtype({
        "names": ["x", "y", "z", "ring", "t"],
        "formats": [endian + kind for kind in ("f4", "f8", "f4", "u2", "u4")],
        "offsets": [0, 8, 20, 32, 36], "itemsize": 48,
    })
    array = np.ndarray((2, 2), dtype=dtype, buffer=data, strides=(112, 48))
    array["x"] = [[1, 0], [np.nan, -3]]
    array["y"] = [[2.125, 0], [1, -4.25]]
    array["z"] = [[3, 0], [2, 0.5]]
    array["ring"] = [[2, 3], [4, 31]]
    array["t"] = [[123, 0], [0, 987654321]]
    cloud = SimpleNamespace(height=2, width=2, point_step=48, row_step=112, data=data, fields=fields, is_bigendian=bigendian)
    points, attributes = decode_cloud(cloud)
    np.testing.assert_allclose(points, [[1, 2.125, 3], [-3, -4.25, 0.5]])
    np.testing.assert_array_equal(attributes["ring"], [2, 31])
    np.testing.assert_array_equal(attributes["t"], [123, 987654321])
    cloud.data = data[:140]
    with pytest.raises(ValueError, match="Truncated"):
        decode_cloud(cloud)


def test_original_cdr_exactly_matches_exported_npz():
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import PointCloud2

    samples = Path(__file__).resolve().parents[2] / "lidar_cone_handoff" / "samples"
    for path in samples.glob("*.cdr"):
        cloud = deserialize_message(path.read_bytes(), PointCloud2)
        xyz, attributes = decode_cloud(cloud)
        with np.load(path.with_suffix(".npz")) as expected:
            raw = np.column_stack([expected[name].ravel() for name in ("x", "y", "z")])
            keep = np.isfinite(raw).all(axis=1) & np.any(raw != 0, axis=1)
            np.testing.assert_array_equal(xyz, raw[keep])
            for name, actual in attributes.items():
                np.testing.assert_array_equal(actual, expected[name].ravel()[keep])
