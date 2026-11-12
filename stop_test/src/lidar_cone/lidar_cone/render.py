"""Fast OpenCV review panels: camera, original XYZ, XY and XZ with boxes."""
from itertools import product

import cv2
import numpy as np


BG = (24, 19, 15)
PANEL = (36, 29, 23)
GRID = (67, 57, 47)
TEXT = (234, 234, 228)
MUTED = (166, 158, 145)
ORANGE = (40, 176, 255)
RED, GREEN, BLUE = (83, 87, 255), (137, 214, 69), (255, 164, 60)


def text(canvas, label, xy, scale=0.48, color=TEXT, thickness=1):
    cv2.putText(canvas, label, tuple(map(int, xy)), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


class ReviewRenderer:
    width, height = 1600, 1000

    def __init__(self, config=None):
        self.iso_matrix = np.array([[0.7071, -0.7071, 0], [0.35, 0.35, 0.868]])
        self.x_bounds = (config.x_min, max(5.0, config.x_max)) if config else (-30.0, 5.0)
        self.y_bounds = (-config.y_abs_max, config.y_abs_max) if config else (-8.0, 8.0)
        self.z_bounds = (config.z_min, config.z_max) if config else (-3.0, 4.0)
        corners = np.array(list(product(self.x_bounds, self.y_bounds, self.z_bounds)))
        projected = corners @ self.iso_matrix.T
        self.iso_bounds = (
            projected[:, 0].min() - 2, projected[:, 0].max() + 2,
            projected[:, 1].min() - 2, projected[:, 1].max() + 2,
        )

    @staticmethod
    def _project(points, rect, bounds):
        x, y, width, height = rect
        low_x, high_x, low_y, high_y = bounds
        points = np.asarray(points)
        u = x + (points[:, 0] - low_x) * width / (high_x - low_x)
        v = y + height - (points[:, 1] - low_y) * height / (high_y - low_y)
        # Numeric clipping also prevents absurd input coordinates overflowing int.
        return np.column_stack([np.clip(u, -10000, 10000), np.clip(v, -10000, 10000)]).astype(np.int32)

    @staticmethod
    def _draw_points(canvas, pixels, colors, rect):
        x, y, width, height = rect
        keep = (pixels[:, 0] > x) & (pixels[:, 0] < x + width) & (pixels[:, 1] > y) & (pixels[:, 1] < y + height)
        pixels = pixels[keep]
        if np.ndim(colors) == 2:
            colors = colors[keep]
        canvas[pixels[:, 1], pixels[:, 0]] = colors

    @staticmethod
    def _panel(canvas, rect, title):
        x, y, width, height = rect
        cv2.rectangle(canvas, (x, y), (x + width, y + height), PANEL, -1)
        text(canvas, title, (x + 14, y + 25), 0.53, TEXT, 1)

    def _cartesian(self, canvas, rect, bounds, dimensions, frame, title):
        self._panel(canvas, rect, title)
        x, y, width, height = rect
        plot = (x + 52, y + 44, width - 75, height - 80)
        project = lambda points: self._project(np.asarray(points)[:, dimensions], plot, bounds)
        low_x, high_x, low_y, high_y = bounds
        for value in np.arange(np.ceil(low_x / 5) * 5, high_x + 0.1, 5):
            ends = self._project([[value, low_y], [value, high_y]], plot, bounds)
            cv2.line(canvas, tuple(ends[0]), tuple(ends[1]), GRID, 1)
            text(canvas, str(int(value)), ends[0] + [-8, 19], 0.36, MUTED)
        step = 2 if dimensions == (0, 1) else 1
        for value in np.arange(np.ceil(low_y / step) * step, high_y + 0.1, step):
            ends = self._project([[low_x, value], [high_x, value]], plot, bounds)
            cv2.line(canvas, tuple(ends[0]), tuple(ends[1]), GRID, 1)
            text(canvas, str(int(value)), ends[0] + [-29, 4], 0.36, MUTED)
        if frame is not None:
            pixels = project(frame.roi_points)
            colors = np.tile(np.array([152, 115, 73], dtype=np.uint8), (len(pixels), 1))
            colors[~frame.ground_mask] = [186, 174, 143]
            self._draw_points(canvas, pixels, colors, plot)
            for i, cone in enumerate(frame.cones):
                cone_pixels = project(cone.points)
                self._draw_points(canvas, cone_pixels, ORANGE, plot)
                low, high = cone.center - cone.size / 2, cone.center + cone.size / 2
                box = project(np.array([low, high]))
                if not (plot[0] <= box[0, 0] <= plot[0] + plot[2]):
                    continue
                cv2.rectangle(canvas, tuple(box[0]), tuple(box[1]), ORANGE, 2)
                anchor = (int(box[0, 0]) - 5, min(int(box[0, 1]), int(box[1, 1])) - 6)
                text(canvas, "C" + str(i + 1), anchor, 0.35, ORANGE)
        origin = project(np.array([[0, 0, 0]]))[0]
        for vector, label, color in [([4, 0, 0], "+X", RED), ([0, 4, 0], "+Y", GREEN), ([0, 0, 1.5], "+Z", BLUE)]:
            if (dimensions == (0, 1) and label == "+Z") or (dimensions == (0, 2) and label == "+Y"):
                continue
            end = project(np.array([vector]))[0]
            cv2.arrowedLine(canvas, tuple(origin), tuple(end), color, 2, cv2.LINE_AA, tipLength=0.15)
            text(canvas, label, end + [4, -4], 0.43, color, 1)
        front = project(np.array([[-6, 0, 0]]))[0]
        cv2.arrowedLine(canvas, tuple(origin), tuple(front), ORANGE, 2, cv2.LINE_AA, tipLength=0.13)
        text(canvas, "front -X", front + [-55, -10], 0.40, ORANGE)
        text(canvas, "X [m]", (x + width - 54, y + height - 8), 0.36, MUTED)
        return canvas

    def _isometric(self, canvas, rect, frame):
        x, y, width, height = rect
        target = canvas
        canvas = np.full((height, width, 3), PANEL, dtype=np.uint8)
        self._panel(canvas, (0, 0, width, height), "XYZ | os_lidar | boxes bound observed cone points")
        plot = (20, 44, width - 40, height - 58)
        bounds = self.iso_bounds
        project = lambda points: self._project(np.asarray(points) @ self.iso_matrix.T, plot, bounds)
        grid_lines = []
        for value in np.arange(np.ceil(self.x_bounds[0] / 5) * 5, self.x_bounds[1] + 0.1, 5):
            grid_lines.append([[value, self.y_bounds[0], 0], [value, self.y_bounds[1], 0]])
        for value in np.arange(np.ceil(self.y_bounds[0] / 2) * 2, self.y_bounds[1] + 0.1, 2):
            grid_lines.append([[self.x_bounds[0], value, 0], [self.x_bounds[1], value, 0]])
        for points in grid_lines:
            pixels = project(points)
            visible, start, end = cv2.clipLine(plot, tuple(pixels[0]), tuple(pixels[1]))
            if visible:
                cv2.line(canvas, start, end, GRID, 1)
        if frame is not None:
            colors = np.tile(np.array([152, 115, 73], dtype=np.uint8), (len(frame.roi_points), 1))
            colors[~frame.ground_mask] = [186, 174, 143]
            # Back-to-front order improves the sense of depth in this orthographic view.
            order = np.argsort(frame.roi_points[:, 0] + frame.roi_points[:, 1])
            self._draw_points(canvas, project(frame.roi_points[order]), colors[order], plot)
            for i, cone in enumerate(frame.cones):
                low, high = cone.center - cone.size / 2, cone.center + cone.size / 2
                vertices = np.array(list(product(*zip(low, high))))
                pixels = project(vertices)
                for start in range(8):
                    for bit in (1, 2, 4):
                        end = start ^ bit
                        if start < end:
                            cv2.line(canvas, tuple(pixels[start]), tuple(pixels[end]), ORANGE, 1, cv2.LINE_AA)
                self._draw_points(canvas, project(cone.points), ORANGE, plot)
                anchor = project(np.array([cone.center]))[0]
                text(canvas, "C" + str(i + 1), anchor + [3, -7], 0.34, ORANGE)
        origin = project([[0, 0, 0]])[0]
        for vector, label, color in [([5, 0, 0], "+X", RED), ([0, 5, 0], "+Y", GREEN), ([0, 0, 3], "+Z", BLUE), ([-7, 0, 0], "front -X", ORANGE)]:
            end = project([vector])[0]
            cv2.arrowedLine(canvas, tuple(origin), tuple(end), color, 2, cv2.LINE_AA, tipLength=0.15)
            text(canvas, label, end + [4, -3], 0.44, color)
        # All 3D geometry is clipped to this panel, including off-screen grid.
        target[y:y + height, x:x + width] = canvas

    def render(self, frame, source, camera=None, error=None):
        canvas = np.empty((self.height, self.width, 3), np.uint8)
        canvas[:] = BG
        cones = len(frame.cones) if frame else 0
        text(canvas, "LiDAR CONE REVIEW / ORIGINAL SENSOR AXES", (24, 31), 0.77, TEXT, 2)
        text(canvas, "t={:.2f}s  |  cones={}  |  forward=-X  left~=-Y  |  frame={}".format(
            source["bag_relative_s"], cones, source["frame_id"],
        ), (24, 62), 0.52, ORANGE)
        text(canvas, "base_link: " + ("calibrated" if source.get("control_valid") else "uncalibrated / valid=false"), (1050, 33), 0.46, MUTED)
        stamp = source["header_stamp"]
        text(canvas, "source stamp: {}.{:09d}".format(stamp["sec"], stamp["nanosec"]), (1050, 61), 0.46, MUTED)
        camera_rect = (20, 82, 765, 425)
        self._panel(canvas, camera_rect, "Camera reference | nearest recording time; no image projection")
        if camera is not None:
            available_width, available_height = 737, 350
            ratio = min(available_width / camera.shape[1], available_height / camera.shape[0])
            image = cv2.resize(camera, (round(camera.shape[1] * ratio), round(camera.shape[0] * ratio)))
            left = 20 + (765 - image.shape[1]) // 2
            top = 122 + (350 - image.shape[0]) // 2
            canvas[top:top + image.shape[0], left:left + image.shape[1]] = image
        delta = source.get("camera_bag_delta_s")
        caption = "camera dt={:+.3f}s (bag clock)".format(delta) if delta is not None else "No camera frame"
        text(canvas, caption, (35, 493), 0.42, MUTED)
        self._isometric(canvas, (800, 82, 780, 425), frame)
        self._cartesian(canvas, (20, 522, 765, 445), (*self.x_bounds, *self.y_bounds), (0, 1), frame, "XY | original X / Y [m] | orange = cone AABB")
        self._cartesian(canvas, (800, 522, 780, 445), (*self.x_bounds, *self.z_bounds), (0, 2), frame, "XZ | original X / Z [m] | sensor origin Z=0")
        if error:
            text(canvas, "Processing failed: " + error[:160], (24, 990), 0.42, RED)
        else:
            text(canvas, "Observed extents only; no deskew. Geometry candidates are not ground-truth labels. Sensor clock is preserved.", (24, 990), 0.42, MUTED)
        return canvas
