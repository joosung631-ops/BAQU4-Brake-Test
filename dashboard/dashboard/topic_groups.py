"""User-editable exact topic groups; keep the last valid config while editing."""

import math
import os
from pathlib import Path

import yaml


BAG_CAMERA_PREFIX = '/dashboard/bag'


def camera_source_topic(mode, topic):
    """Display names stay stable; replay images use a separate ROS source."""
    return BAG_CAMERA_PREFIX + topic if mode == 'bag' else topic


class TopicGroups:
    def __init__(self, path=None):
        self.path = path if path is not None else Path(os.environ.get(
            "DASHBOARD_TOPIC_CONFIG", str(Path(__file__).resolve().parents[1] / "config.yaml")))
        self.groups = []
        self.modes = {"live": {"label": "실시간", "groups": []}}
        self.default_mode = "live"
        self.camera = self.validate_camera({})
        self.traffic = self.validate_traffic({})
        self.error = None
        self.last_text = None

    @staticmethod
    def validate(config):
        if not isinstance(config, dict):
            raise ValueError("groups 목록을 포함한 YAML 설정을 입력하세요.")
        groups = config.get("groups")
        if not isinstance(groups, list) or len(groups) > 64:
            raise ValueError("groups 목록을 설정하세요 (최대 64개).")
        names, topics_seen, validated = set(), set(), []
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("분류 형식이 올바르지 않습니다.")
            name, topics = group.get("name"), group.get("topics")
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError("분류 이름은 1~80자로 입력하세요.")
            if name in names or name == "예외":
                raise ValueError(f"중복되거나 예약된 분류 이름: {name}")
            if not isinstance(topics, list) or len(topics) > 1024:
                raise ValueError(f"{name}: topics는 토픽 이름 목록이어야 합니다.")
            rules = []
            for entry in topics:
                if isinstance(entry, str):
                    topic, required, image = entry, True, False
                elif isinstance(entry, dict):
                    topic, required = entry.get("name"), entry.get("required", True)
                    image = entry.get("image", False)
                else:
                    raise ValueError(f"{name}: 토픽 이름 또는 name/required 항목을 입력하세요.")
                if type(required) is not bool:
                    raise ValueError(f"{name}: required는 true 또는 false여야 합니다.")
                if type(image) is not bool:
                    raise ValueError(f"{name}: image는 true 또는 false여야 합니다.")
                if not isinstance(topic, str) or not topic.startswith("/") or len(topic) > 256 or any(c.isspace() for c in topic):
                    raise ValueError(f"{name}: 토픽의 전체 이름을 입력하세요.")
                if topic in topics_seen:
                    raise ValueError(f"중복 등록된 토픽: {topic}")
                topics_seen.add(topic)
                rules.append({"name": topic, "required": required, "image": image})
            names.add(name)
            validated.append({"name": name, "topics": rules})
        return validated

    @staticmethod
    def validate_traffic(config):
        settings = config.get("traffic", {}) if isinstance(config, dict) else {}
        if not isinstance(settings, dict):
            raise ValueError("traffic은 데이터 사용량 설정이어야 합니다.")
        samples = settings.get("smoothing_samples", 10)
        if type(samples) is not int or not 1 <= samples <= 3600:
            raise ValueError("traffic.smoothing_samples는 1~3600 정수여야 합니다.")
        return {"smoothing_samples": samples}

    @staticmethod
    def validate_camera(config):
        settings = config.get("camera", {}) if isinstance(config, dict) else {}
        if not isinstance(settings, dict):
            raise ValueError("camera는 영상 전송 설정이어야 합니다.")
        limits = {"fps": (15, 5, 30), "max_width": (640, 160, 1920),
                  "jpeg_quality": (65, 10, 95)}
        result = {}
        for key, (default, low, high) in limits.items():
            value = settings.get(key, default)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"camera.{key}는 {low}~{high} 정수여야 합니다.")
            result[key] = value
        if result['fps'] not in (5,10,15,20,25,30):
            raise ValueError('camera.fps는 5~30의 5단위여야 합니다.')
        return result

    def image_topics(self, mode):
        return [rule["name"] for group in self.modes.get(mode, {}).get("groups", [])
                for rule in group["topics"] if rule.get("image", False)]

    @classmethod
    def validate_modes(cls, config):
        if not isinstance(config, dict) or "modes" not in config:
            return {"live": {"label": "실시간", "groups": cls.validate(config)}}, "live"
        modes = config["modes"]
        if not isinstance(modes, dict) or not 1 <= len(modes) <= 16:
            raise ValueError("modes에 1~16개의 모드를 설정하세요.")
        validated = {}
        for key, mode in modes.items():
            if not isinstance(key, str) or not key or len(key) > 40 or not all(
                    c in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in key):
                raise ValueError("모드 키는 영문 소문자, 숫자, 밑줄, 하이픈으로 입력하세요.")
            if not isinstance(mode, dict):
                raise ValueError(f"{key}: label과 groups를 설정하세요.")
            label = mode.get("label", key)
            if not isinstance(label, str) or not label.strip() or len(label) > 80:
                raise ValueError(f"{key}: label은 1~80자로 입력하세요.")
            validated[key] = {"label": label, "groups": cls.validate(mode)}
        default = config.get("default_mode", next(iter(validated)))
        if not isinstance(default, str) or default not in validated:
            raise ValueError("default_mode는 modes에 등록된 모드여야 합니다.")
        return validated, default

    def reload(self):
        try:
            text = self.path.read_text(encoding="utf-8")
            if text != self.last_text:
                config = yaml.safe_load(text)
                modes, default = self.validate_modes(config)
                camera = self.validate_camera(config)
                traffic = self.validate_traffic(config)
                self.modes, self.default_mode = modes, default
                self.camera = camera
                self.traffic = traffic
                self.groups = modes[default]["groups"]
                self.last_text = text
            self.error = None
        except (OSError, ValueError, yaml.YAMLError) as error:
            self.error = f"분류 설정 오류: {error}"

    def classify(self, topics, mode=None, *, reload=True):
        if reload:
            self.reload()
        selected = mode if mode in self.modes else self.default_mode
        rules = self.modes[selected]["groups"]
        images = {name for key in self.modes for name in self.image_topics(key)}
        received = {}
        for row in topics:
            name = row['name']
            if name.startswith(BAG_CAMERA_PREFIX + '/'):
                if selected != 'bag':
                    continue
                name = name[len(BAG_CAMERA_PREFIX):]
            elif selected == 'bag' and name in images:
                continue  # Live camera traffic never makes replay appear healthy.
            received[name] = {**row, 'name': name, 'received': True}
        assigned = set()
        result = []
        for group in rules:
            expected = [rule["name"] for rule in group["topics"]]
            required = [rule["name"] for rule in group["topics"] if rule["required"]]
            rows = [received.get(name, {"name": name, "hz": None, "retained": False,
                                        "received": False}) for name in expected]
            def has_hz(name):
                hz = received.get(name, {}).get("hz")
                return type(hz) in (int, float) and math.isfinite(hz) and hz > 0

            status = ("ok" if all(has_hz(name) for name in required) else "error") if required else "empty"
            result.append({"name": group["name"], "status": status, "topics": rows,
                           "required_topics": required})
            assigned.update(expected)
        result.append({"name": "예외", "status": None,
                       "topics": [received[name] for name in sorted(received.keys() - assigned)]})
        return result
