"""Closed-course sparse returns, counterexamples, and temporal identity."""
import unittest
import numpy as np

from lidar_cone.stop_row import detect_stop_row, StopRowTracker


def corridor():
    return dict(state='paired', heading_deg=0., lines={
        'left': dict(points_cm=[-200, -200, -112, -1700, -200, -112]),
        'right': dict(points_cm=[-200, 200, -112, -1700, 200, -112])})


def scene(distance=30):
    x, y = np.meshgrid(np.linspace(-44, -1, 120), np.linspace(-5, 5, 40))
    road = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, -1.2)))
    row = np.array([[-distance, -1.2, -.8], [-distance, 0, -.8], [-distance, 1.2, -.8]])
    return road, row


def candidate(distance=30):
    ground, row = scene(distance)
    return detect_stop_row(np.concatenate((ground, row)), [0, 0, -1.2], corridor())


class SparseRowTests(unittest.TestCase):
    def test_three_returns_without_height_extent_are_a_candidate(self):
        row = candidate()
        self.assertEqual(row['state'], 'candidate')
        self.assertEqual(row['support_cells'], 3)
        self.assertEqual(row['distance_cm'], 3000)
        self.assertEqual(row['span_cm'], 240)
        self.assertEqual(row['ground'], 'near_verified')
        self.assertTrue(all(v == -108 for v in row['points_cm'][2::3]))

    def test_floor_and_normal_boundary_pair_do_not_make_stop_row(self):
        ground, _ = scene()
        sides = [[-s, q, -.8] for s in (5, 8, 11, 14, 17, 30) for q in (-2, 2)]
        for xyz in (ground, np.concatenate((ground, sides))):
            self.assertEqual(detect_stop_row(xyz, [0, 0, -1.2], corridor())['state'], 'none')

    def test_many_returns_from_one_object_are_not_three_cones(self):
        ground, _ = scene()
        points = np.random.default_rng(8).uniform([-30.1, -.2, -.9], [-29.9, .2, -.7], (100, 3))
        self.assertEqual(detect_stop_row(np.concatenate((ground, points)), [0, 0, -1.2], corridor())['state'], 'none')

    def test_low_biased_plane_is_rejected_by_independent_near_ground(self):
        ground, _ = scene()
        row = detect_stop_row(ground, [0, 0, -1.4], corridor())
        self.assertEqual(row['state'], 'none')
        self.assertEqual(row['reason'], 'ground_unreliable')

    def test_missing_or_ambiguous_boundaries_cannot_invent_corridor(self):
        ground, points = scene()
        for course in ({}, dict(corridor(), state='ambiguous'), dict(corridor(), state='partial')):
            self.assertEqual(detect_stop_row(np.concatenate((ground, points)), [0, 0, -1.2], course)['reason'], 'no_corridor')


class TrackingTests(unittest.TestCase):
    def test_distinct_scans_at_35kph_confirm_with_range_rate(self):
        tracker = StopRowTracker()
        speed = 35 / 3.6
        self.assertEqual(tracker.update(candidate(), 0, 10, speed)['state'], 'candidate')
        row = tracker.update(candidate(30 - speed * .1), .1, 11, speed)
        self.assertEqual(row['state'], 'confirmed')
        self.assertEqual(row['observations'], 2)

    def test_repeated_evaluation_of_paused_scan_cannot_confirm(self):
        tracker = StopRowTracker()
        for _ in range(5):
            self.assertEqual(tracker.update(candidate(), 1, 10, 0)['state'], 'candidate')
        self.assertEqual(len(tracker.history), 1)

    def test_reordered_duplicate_cannot_add_a_new_observation(self):
        tracker = StopRowTracker()
        tracker.update(candidate(), 0, 10, None)
        tracker.update(candidate(), .1, 11, 0)
        row = tracker.update(candidate(), .2, 10, 0)
        self.assertEqual(row['state'], 'candidate')
        self.assertEqual(row['reason'], 'duplicate_scan')
        self.assertEqual(len(tracker.history), 2)

    def test_one_missed_scan_allowed_but_two_clear_evidence(self):
        tracker = StopRowTracker()
        absent = dict(state='none', reason='no_transverse_support')
        tracker.update(candidate(), 0, 1, 0)
        self.assertEqual(tracker.update(absent, .1, 2, 0)['state'], 'none')
        self.assertEqual(tracker.update(candidate(), .2, 3, 0)['state'], 'confirmed')
        tracker.update(absent, .3, 4, 0); tracker.update(absent, .4, 5, 0)
        self.assertEqual(tracker.update(candidate(), .5, 6, 0)['state'], 'candidate')

    def test_speed_missing_range_jump_time_gap_and_backward_time_do_not_confirm(self):
        for time, distance, speed in ((.1, 30, None), (.1, 27, 0), (.5, 30, 0), (-1, 30, 0)):
            tracker = StopRowTracker(); tracker.update(candidate(), 0, 1, 0)
            row = tracker.update(candidate(distance), time, 2, speed)
            self.assertEqual(row['state'], 'candidate')

    def test_invalid_first_speed_cannot_be_used_as_witness(self):
        tracker = StopRowTracker(); tracker.update(candidate(), 0, 1, None)
        self.assertEqual(tracker.update(candidate(), .1, 2, 0)['state'], 'candidate')
        self.assertEqual(tracker.update(candidate(), .2, 3, 0)['state'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
