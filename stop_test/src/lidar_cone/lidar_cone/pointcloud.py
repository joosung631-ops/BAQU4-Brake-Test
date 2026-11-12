"""PointCloud2 decoding, including row padding, field offsets and byte order."""
import numpy as np


FIELD_TYPES = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}


def decode_cloud(cloud):
    height, width = int(cloud.height), int(cloud.width)
    if height < 0 or width < 0 or cloud.point_step <= 0:
        raise ValueError("Invalid PointCloud2 dimensions/point_step")
    if cloud.row_step < width * cloud.point_step:
        raise ValueError("PointCloud2 row_step is shorter than one row")
    required = (height - 1) * cloud.row_step + width * cloud.point_step if height else 0
    if len(cloud.data) < required:
        raise ValueError("Truncated PointCloud2 data")
    endian = ">" if cloud.is_bigendian else "<"
    names, formats, offsets = [], [], []
    for field in cloud.fields:
        if field.name in names or field.datatype not in FIELD_TYPES or field.count < 1:
            raise ValueError("Unsupported/duplicate PointCloud2 field")
        base = np.dtype(endian + FIELD_TYPES[field.datatype])
        if field.offset < 0 or field.offset + base.itemsize * field.count > cloud.point_step:
            raise ValueError("PointCloud2 field extends beyond point_step")
        names.append(field.name)
        formats.append(base if field.count == 1 else (base, (field.count,)))
        offsets.append(field.offset)
    for name in ("x", "y", "z"):
        if name not in names:
            raise ValueError("PointCloud2 is missing " + name)
        field = next(field for field in cloud.fields if field.name == name)
        if field.count != 1 or field.datatype not in (7, 8):
            raise ValueError("XYZ must be scalar FLOAT32/FLOAT64 fields")
    dtype = np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": cloud.point_step})
    rows = np.ndarray(
        (height, width), dtype=dtype, buffer=cloud.data,
        strides=(cloud.row_step, cloud.point_step),
    )
    xyz = np.column_stack([rows[name].ravel() for name in ("x", "y", "z")])
    # Use XYZ in meters, never the vendor-specific integer range field.
    keep = np.isfinite(xyz).all(axis=1) & np.any(xyz != 0, axis=1)
    attributes = {
        name: rows[name].reshape(-1)[keep]
        for name in ("ring", "reflectivity", "intensity", "t")
        if name in names and rows[name].ndim == 2
    }
    return xyz[keep].astype(np.float64), attributes
