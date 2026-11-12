"""Apply the detector to original handoff samples or a complete ROS 2 bag."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
import yaml

from .detector import ConeDetector, DetectorConfig
from .geometry import aabb, load_calibration, transform_points


def sample_frames(directory):
    for path in sorted(Path(directory).glob("frame_*.npz")):
        metadata = json.loads(path.with_suffix(".json").read_text())
        with np.load(path) as data:
            xyz = np.column_stack([data[name].ravel() for name in ("x", "y", "z")])
            keep = np.isfinite(xyz).all(axis=1) & np.any(xyz != 0, axis=1)
            attributes = {name: data[name].ravel()[keep] for name in ("ring", "t", "reflectivity", "intensity") if name in data}
        camera_path = path.with_name(path.stem + "_camera.jpg")
        camera = camera_path.read_bytes() if camera_path.exists() else None
        yield path.stem, metadata, xyz[keep], attributes, camera


def bag_frames(directory, start_s=0.0, duration_s=None, stride=1):
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import CompressedImage, PointCloud2
    from .bag_reader import open_bag
    from .pointcloud import decode_cloud

    print("Opening original bag read-only (zstd is decompressed into a temporary directory)", flush=True)
    with open_bag(directory) as reader:
        for index, (timestamp_ns, blob) in enumerate(reader.clouds(start_s, duration_s, stride)):
            cloud = deserialize_message(blob, PointCloud2)
            metadata = {
                "bag_timestamp_ns": timestamp_ns,
                "bag_relative_s": (timestamp_ns - reader.start_ns) / 1e9,
                "header_stamp": {"sec": cloud.header.stamp.sec, "nanosec": cloud.header.stamp.nanosec},
                "frame_id": cloud.header.frame_id,
            }
            try:
                xyz, attributes = decode_cloud(cloud)
            except ValueError as error:
                xyz, attributes = None, {}
                metadata["decode_error"] = str(error)
            camera_blob, metadata["camera_bag_delta_s"] = reader.nearest_camera(timestamp_ns)
            camera = bytes(deserialize_message(camera_blob, CompressedImage).data) if camera_blob is not None else None
            yield "frame_{:05d}".format(index), metadata, xyz, attributes, camera


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--samples", type=Path)
    inputs.add_argument("--bag", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    options = parser.parse_args(args)
    if options.stride < 1 or options.start < 0 or (options.duration is not None and options.duration <= 0):
        parser.error("stride must be >= 1, start >= 0, duration > 0")
    config = DetectorConfig.from_dict(yaml.safe_load(options.config.read_text()) or {}) if options.config else DetectorConfig()
    detector = ConeDetector(config)
    transform = load_calibration(options.calibration) if options.calibration else None
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    input_path = (options.bag or options.samples).resolve()
    if output == input_path or input_path in output.parents:
        parser.error("output must be outside the original input directory")
    renderer, cv2 = None, None
    if not options.no_render:
        import cv2
        from .render import ReviewRenderer
        renderer = ReviewRenderer(config)
    source_sha256 = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path(__file__).parent.glob("*.py")
    }
    # 10Hz is the recorded mode; stride changes video playback spacing only.
    fps = 10.0 / options.stride
    writer = None
    counts, durations, failures = [], [], []
    snapshots = {}
    targets = [8.0, 18.0, 35.0]
    if options.bag:
        frames = bag_frames(options.bag, options.start, options.duration, options.stride)
    else:
        frames = sample_frames(options.samples)
    (output / "detector_config.yaml").write_text(yaml.safe_dump(asdict(config), sort_keys=False))
    invocation = [sys.executable, "-m", "lidar_cone.offline"] + (list(args) if args is not None else sys.argv[1:])
    (output / "command.json").write_text(json.dumps(invocation, indent=2) + "\n")
    try:
        with (output / "detections.jsonl").open("w") as stream:
            for index, (name, source, xyz, attributes, camera_bytes) in enumerate(frames):
                started = perf_counter()
                frame, error = None, None
                try:
                    if source["frame_id"] != "os_lidar":
                        raise ValueError("Unexpected frame: " + source["frame_id"])
                    if xyz is None:
                        raise ValueError(source["decode_error"])
                    frame = detector.detect(xyz, attributes)
                except ValueError as exception:
                    error = str(exception)
                    failures.append({"frame": name, "error": error})
                elapsed_ms = (perf_counter() - started) * 1000
                control = {"timestamp": source["header_stamp"], "valid": False, "objects": []}
                if frame is not None and transform is not None:
                    objects = []
                    for cone in frame.cones:
                        center, size = aabb(transform_points(cone.points, transform))
                        objects.append({"center": center.tolist(), "size": size.tolist()})
                    control.update(valid=True, objects=objects)
                record = {
                    "frame": name, "source": source, "diagnostic_frame": "os_lidar",
                    "processing_ok": frame is not None, "processing_ms": elapsed_ms,
                    "cones": [cone.to_dict() for cone in frame.cones] if frame else [],
                    "ground_plane_z_abc": frame.plane.tolist() if frame else None,
                    "statistics": frame.statistics if frame else {},
                    "control_result": control, "error": error,
                }
                stream.write(json.dumps(record, allow_nan=False) + "\n")
                counts.append(len(frame.cones) if frame else 0)
                durations.append(elapsed_ms)
                if renderer is not None:
                    camera = cv2.imdecode(np.frombuffer(camera_bytes, np.uint8), cv2.IMREAD_COLOR) if camera_bytes else None
                    view = renderer.render(frame, {**source, "control_valid": control["valid"]}, camera, error)
                    if not options.no_video and options.bag:
                        if writer is None:
                            writer = cv2.VideoWriter(str(output / "cone_review.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (renderer.width, renderer.height))
                            if not writer.isOpened():
                                raise RuntimeError("OpenCV could not create the review MP4")
                        writer.write(view)
                    if options.samples:
                        if not cv2.imwrite(str(output / (name + "_cones.png")), view):
                            raise RuntimeError("Could not write sample review image")
                    else:
                        for target in targets:
                            distance = abs(source["bag_relative_s"] - target)
                            if target not in snapshots or distance < snapshots[target]["distance_s"]:
                                snapshots[target] = {"distance_s": distance, "source": source, "cones": counts[-1]}
                                if not cv2.imwrite(str(output / ("frame_{:03d}s_cones.png".format(int(target)))), view):
                                    raise RuntimeError("Could not write review image")
                if index % 100 == 0:
                    print("frame={} t={:.2f}s cones={} processing={:.1f}ms".format(index, source["bag_relative_s"], counts[-1], elapsed_ms), flush=True)
    finally:
        if writer is not None:
            writer.release()
    if not counts:
        raise RuntimeError("No PointCloud2 frames matched the selected input/time range")
    summary = {
        "input": str(input_path), "processed_frames": len(counts), "failed_frames": len(failures),
        "failures": failures, "frames_with_cones": sum(count > 0 for count in counts),
        "total_cone_observations": sum(counts),
        "cones_per_frame_min_median_max": [min(counts), float(np.median(counts)), max(counts)],
        "processing_ms_p50_p95_max": np.percentile(durations, [50, 95, 100]).tolist(),
        "diagnostic_frame": "os_lidar", "vehicle_forward_axis": "-X",
        "base_link_calibrated": transform is not None,
        "control_valid_without_calibration": False,
        "timestamp_policy": "unchanged PointCloud2.header.stamp; not synchronized to the control clock",
        "deskew": False, "ground_truth_available": False,
        "source_sha256": source_sha256,
        "snapshots": {str(target): snapshot for target, snapshot in snapshots.items()},
        "python": sys.version, "numpy": np.__version__,
        "opencv": cv2.__version__ if cv2 else None,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key not in ("source_sha256", "snapshots", "failures")}, indent=2), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
