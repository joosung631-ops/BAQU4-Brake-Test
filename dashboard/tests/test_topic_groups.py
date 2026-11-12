import tempfile
import unittest
from pathlib import Path

from dashboard.topic_groups import TopicGroups


CONFIG = '''
groups:
  - name: 카메라
    topics: ["/camera/image", "/camera/info"]
  - name: 라이다
    topics: ["/lidar/points"]
  - name: 추가 분류
    topics: []
'''


def topic(name, retained=False):
    return {"name": name, "hz": None if retained else 10.0, "retained": retained, "received": True}


def missing(name):
    return {"name": name, "hz": None, "retained": False, "received": False}


class TopicGroupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.yaml"
        self.path.write_text(CONFIG, encoding="utf-8")
        self.config = TopicGroups(self.path)

    def test_order_membership_health_and_unconfigured_exceptions(self):
        rows = [topic("/camera/info"), topic("/unknown"), topic("/camera/image")]
        groups = self.config.classify(rows)
        self.assertEqual([g["name"] for g in groups], ["카메라", "라이다", "추가 분류", "예외"])
        self.assertEqual(groups[0]["status"], "ok")
        self.assertEqual([t["name"] for t in groups[0]["topics"]], ["/camera/image", "/camera/info"])
        self.assertEqual(groups[1]["status"], "error")
        self.assertEqual(groups[1]["topics"], [missing("/lidar/points")])
        self.assertEqual(groups[2]["status"], "empty")
        self.assertIsNone(groups[3]["status"])
        self.assertEqual(groups[3]["topics"], [topic("/unknown")])
        self.assertIsNone(self.config.error)

    def test_partial_receipt_and_loss_are_errors_not_sticky_success(self):
        self.config.classify([topic("/camera/image"), topic("/camera/info")])
        partial = self.config.classify([topic("/camera/image")])
        self.assertEqual(partial[0]["status"], "error")
        self.assertEqual(partial[0]["required_topics"], ["/camera/image", "/camera/info"])
        self.assertEqual(partial[0]["topics"], [topic("/camera/image"), missing("/camera/info")])
        empty = self.config.classify([])
        self.assertEqual(empty[0]["topics"], [missing("/camera/image"), missing("/camera/info")])
        self.assertEqual(empty[1]["topics"], [missing("/lidar/points")])
        self.assertTrue(all(not row["received"] and row["hz"] is None for group in empty for row in group["topics"]))
        self.assertEqual(empty[-1]["topics"], [])
        self.assertEqual(empty[0]["status"], "error")
        self.assertIsNone(empty[-1]["status"])

    def test_save_reload_and_invalid_edit_preserves_last_valid_configuration(self):
        self.config.classify([])
        self.path.write_text(CONFIG + '\n  - name: IMU\n    topics: ["/imu"]\n')
        groups = self.config.classify([topic("/imu")])
        self.assertEqual(groups[-2]["name"], "IMU")
        self.assertEqual(groups[-2]["status"], "ok")
        self.assertEqual(groups[-1]["topics"], [])
        self.path.write_text('groups: [\n')
        self.assertEqual(self.config.classify([topic("/imu")]), groups)
        self.assertIsNotNone(self.config.error)
        self.path.write_text(CONFIG)
        self.assertEqual(len(self.config.classify([])), 4)
        self.assertIsNone(self.config.error)

    def test_duplicate_and_reserved_groups_or_topics_rejected(self):
        invalid = [
            None, [], "invalid",
            {"groups": [{"name": "예외", "topics": []}]},
            {"groups": [{"name": "A", "topics": []}, {"name": "A", "topics": []}]},
            {"groups": [{"name": "A", "topics": ["/x"]}, {"name": "B", "topics": ["/x"]}]},
            {"groups": [{"name": "A", "topics": ["/x", "/x"]}]},
            {"groups": [{"name": "A", "topics": ["no_slash"]}]},
            {"groups": [{"name": "A", "topics": [{"name": "/x", "required": "false"}]}]},
            {"groups": [{"name": "A", "topics": [{"name": "/x", "required": 1}]}]},
            {"groups": [{"name": "A", "topics": [{"name": "/x", "required": None}]}]},
            {"groups": [{"name": "A", "topics": ["/x", {"name": "/x", "required": False}]}]},
        ]
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                TopicGroups.validate(config)

    def test_invalid_yaml_root_keeps_last_valid_configuration(self):
        expected = self.config.classify([])
        for text in ("", "null", "- not-a-mapping", "!!python/object:builtins.object {}"):
            with self.subTest(text=text):
                self.path.write_text(text)
                self.assertEqual(self.config.classify([]), expected)
                self.assertIsNotNone(self.config.error)

    def test_only_required_positive_hz_controls_health(self):
        self.path.write_text('''
groups:
  - name: 라이다
    topics:
      - name: /points
        required: true
      - name: /metadata
        required: false
''')
        healthy = self.config.classify([topic("/points")])[0]
        self.assertEqual(healthy["status"], "ok")
        self.assertEqual(healthy["required_topics"], ["/points"])
        self.assertEqual(healthy["topics"], [topic("/points"), missing("/metadata")])
        self.assertEqual(self.config.classify([topic("/metadata")])[0]["status"], "error")
        for hz in (None, 0, -1, float("nan"), float("inf"), True):
            with self.subTest(hz=hz):
                row = {**topic("/points", retained=True), "hz": hz}
                self.assertEqual(self.config.classify([row])[0]["status"], "error")
        self.assertEqual(self.config.classify([{**topic("/points"), "hz": 0.1}])[0]["status"], "ok")

    def test_optional_only_group_and_required_flag_reload(self):
        optional = 'groups:\n  - name: 기타\n    topics:\n      - name: /tf_static\n        required: false\n'
        self.path.write_text(optional)
        self.assertEqual(self.config.classify([])[0]["status"], "empty")
        self.assertEqual(self.config.classify([topic("/tf_static", retained=True)])[0]["status"], "empty")
        self.path.write_text(optional.replace('required: false', 'required: true'))
        self.assertEqual(self.config.classify([topic("/tf_static", retained=True)])[0]["status"], "error")
        self.assertEqual(self.config.classify([topic("/tf_static")])[0]["status"], "ok")

    def test_modes_have_independent_membership_requirements_and_order(self):
        self.path.write_text('''
default_mode: bag
modes:
  live:
    label: 실시간
    groups:
      - name: 카메라
        topics:
          - name: /raw
            required: true
          - name: /compressed
            required: false
  bag:
    label: ROS bag
    groups:
      - name: 녹화 카메라
        topics:
          - name: /compressed
            required: true
''')
        rows = [topic("/compressed"), topic("/other")]
        live = self.config.classify(rows, "live")
        bag = self.config.classify(rows, "bag")
        self.assertEqual(list(self.config.modes), ["live", "bag"])
        self.assertEqual(live[0]["status"], "error")
        self.assertEqual(live[0]["topics"][0], missing("/raw"))
        self.assertEqual(bag[0]["status"], "ok")
        self.assertEqual(self.config.classify(rows), bag)
        self.assertEqual(self.config.classify(rows, "removed"), bag)
        bag = self.config.classify([topic("/raw")], "bag")
        self.assertEqual(bag[0]["status"], "error")
        self.assertEqual(bag[-1]["topics"], [topic("/raw")])
        self.path.write_text('modes: {live: {groups: []}, bag: {groups: invalid}}')
        self.assertEqual(self.config.classify([topic("/raw")], "bag"), bag)
        self.assertIsNotNone(self.config.error)

    def test_invalid_mode_definitions_rejected(self):
        for config in (
            {"modes": {}}, {"modes": []},
            {"modes": {"live": {"groups": []}}, "default_mode": "missing"},
            {"modes": {"live": {"groups": []}}, "default_mode": []},
            {"modes": {1: {"groups": []}}},
            {"modes": {"live": None}},
            {"modes": {"live": {"label": "", "groups": []}}},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                TopicGroups.validate_modes(config)

    def test_camera_rates_are_isolated_by_live_and_bag_source(self):
        self.path.write_text('''
modes:
  live:
    groups: [{name: camera, topics: [{name: /camera/image, image: true}]}]
  bag:
    groups: [{name: camera, topics: [{name: /camera/image, image: true}]}]
''')
        live_row = {**topic('/camera/image'), 'hz': 30}
        bag_row = {**topic('/dashboard/bag/camera/image'), 'hz': 10}
        live = self.config.classify([live_row, bag_row], 'live')
        bag = self.config.classify([live_row, bag_row], 'bag')
        self.assertEqual(live[0]['topics'][0]['hz'], 30)
        self.assertEqual(bag[0]['topics'][0]['hz'], 10)
        self.assertEqual(bag[0]['topics'][0]['name'], '/camera/image')
        self.assertEqual(live[-1]['topics'], [])
        self.assertEqual(bag[-1]['topics'], [])
        stopped = self.config.classify([live_row], 'bag')
        self.assertEqual(stopped[0]['status'], 'error')
        self.assertFalse(stopped[0]['topics'][0]['received'])

    def test_image_selection_and_camera_settings_validation(self):
        self.path.write_text('''
camera: {fps: 15, max_width: 480, jpeg_quality: 60}
groups:
  - name: 영상
    topics:
      - {name: /raw, image: true, required: false}
      - {name: /points}
      - {name: /compressed, image: true}
''')
        self.config.reload()
        self.assertIsNone(self.config.error)
        self.assertEqual(self.config.image_topics('live'), ['/raw', '/compressed'])

        self.assertEqual(self.config.image_topics('missing'), [])
        self.assertEqual(self.config.camera, {'fps': 15, 'max_width': 480, 'jpeg_quality': 60})
        self.assertEqual(TopicGroups.validate_camera({'camera': {'fps': 30}})['fps'], 30)
        for settings in ({'fps': 0}, {'fps': 31}, {'fps': 1.5}, {'fps': True}, {'max_width': 10000}, {'jpeg_quality': 100}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                TopicGroups.validate_camera({'camera': settings})
        self.path.write_text('camera: {fps: 0}\ngroups: []')
        self.config.reload()
        self.assertIsNotNone(self.config.error)
        self.assertEqual(self.config.image_topics('live'), ['/raw', '/compressed'])

    def test_traffic_smoothing_reload_and_invalid_value_retention(self):
        self.config.reload()
        self.assertEqual(self.config.traffic['smoothing_samples'], 10)
        self.path.write_text('traffic: {smoothing_samples: 7}\n' + CONFIG)
        self.config.reload()
        self.assertEqual(self.config.traffic['smoothing_samples'], 7)
        self.assertIsNone(self.config.error)
        for value in ('0', '-1', '3601', '1.5', 'true', '"10"'):
            self.path.write_text('traffic: {smoothing_samples: ' + value + '}\n' + CONFIG)
            self.config.reload()
            self.assertIsNotNone(self.config.error)
            self.assertEqual(self.config.traffic['smoothing_samples'], 7)
        self.path.write_text(CONFIG)
        self.config.reload()
        self.assertIsNone(self.config.error)
        self.assertEqual(self.config.traffic['smoothing_samples'], 10)


if __name__ == "__main__":
    unittest.main()
