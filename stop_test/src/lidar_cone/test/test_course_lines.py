"""Adversarial geometry checks; these do not establish vehicle performance."""
import math
import json
from pathlib import Path
import unittest
import numpy as np
from lidar_cone.course_lines import extract_course_lines


def course(stop=None, theta=0., missing=None, slope=0.):
    p = [[s, q, -1.] for s in (2, 5, 8, 11, 14, 17, 20) for q in (-2., 2.) if q != missing]
    if stop is not None:
        p += [[stop + slope * q, q, -1.] for q in (-1.2, -.4, .4, 1.2)]
    p = np.array(p)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    p[:, :2] = -(p[:, :2] @ rotation.T)
    return p


class CourseLineTests(unittest.TestCase):
    def test_recorded_end_row_with_irregular_observed_spacing(self):
        fixture=json.loads((Path(__file__).parent/'data/day_end_row.json').read_text())
        r=extract_course_lines(fixture['centers'],[0,0,-1.2])
        self.assertEqual(r['stop_state'],'candidate')
        self.assertAlmostEqual(r['width_cm'],579,delta=10)
        self.assertAlmostEqual(r['stop_distance_cm'],1499,delta=15)
        self.assertGreaterEqual(r['lines']['stop']['cones'],5)

    def test_two_side_cones_at_each_station_are_not_a_stop_barrier(self):
        r = extract_course_lines(course(), [0, 0, -1.2])
        self.assertEqual(r['state'], 'paired')
        self.assertEqual(set(r['lines']), {'left', 'right', 'center'})
        self.assertEqual(r['width_cm'], 400)
        self.assertEqual(r['stop_state'], 'none')

    def test_cross_row_clips_center_and_preserves_ground_height(self):
        plane = [.04, -.01, -1.2]
        r = extract_course_lines(course(14, math.radians(12), slope=.1), plane)
        self.assertEqual(r['stop_state'], 'candidate')
        self.assertAlmostEqual(r['stop_distance_cm'], 1400, delta=5)
        self.assertEqual(r['heading_deg'], 12.)
        for v in r['lines'].values():
            p = np.array(v['points_cm']).reshape(2, 3) * .01
            np.testing.assert_allclose(p[:, 2], p[:, :2] @ plane[:2] + plane[2] + .08, atol=.012)
        end = np.array(r['lines']['center']['points_cm'][3:5]) * -.01
        self.assertLessEqual(np.linalg.norm(end), 14.05)

    def test_one_side_does_not_create_center_or_stop(self):
        r = extract_course_lines(course(missing=-2), [0, 0, -1.2])
        self.assertEqual(r['state'], 'partial')
        self.assertEqual(set(r['lines']), {'left'})

    def test_single_interior_false_detection_cannot_close_course(self):
        p = np.vstack((course(), [[-14, 0, -1.]]))
        self.assertNotIn('stop', extract_course_lines(p, [0, 0, -1.2])['lines'])

    def test_short_side_fragments_do_not_create_path(self):
        r = extract_course_lines([[-2, -2, -1], [-3, -2, -1], [-2, 2, -1]], [0, 0, -1.2])
        self.assertEqual(r['lines'], {})

    def test_nearby_clutter_outside_corridor_does_not_move_reference(self):
        p = np.vstack((course(20), [[-3, 6, -1], [-9, -7, -1], [-12, 6, -1]]))
        r = extract_course_lines(p, [0, 0, -1.2])
        self.assertEqual(r['width_cm'], 400)
        self.assertEqual(r['stop_distance_cm'], 2000)

    def test_long_unobserved_gap_is_not_bridged(self):
        p = [[-s, q, -1] for s in (2, 3, 20, 21) for q in (-2, 2)]
        self.assertNotIn('center', extract_course_lines(p, [0, 0, -1.2])['lines'])

    def test_competing_parallel_corridors_are_marked_ambiguous(self):
        p = [[-s, q, -1] for s in (2, 5, 8, 11, 14, 17, 20) for q in (-3, -2, 2, 3)]
        r = extract_course_lines(p, [0, 0, -1.2])
        self.assertEqual(r['state'], 'ambiguous')
        self.assertNotIn('center', r['lines'])
        self.assertNotIn('stop', r['lines'])

    def test_too_sparse_cross_row_is_not_closed_by_extrapolation(self):
        p = np.vstack((course(), [[-14, -1.4, -1], [-14, 1.4, -1]]))
        self.assertNotIn('stop', extract_course_lines(p, [0, 0, -1.2])['lines'])

    def test_empty_and_invalid_geometry(self):
        self.assertEqual(extract_course_lines([], [0, 0, -1.2])['state'], 'none')
        with self.assertRaises(ValueError):
            extract_course_lines([[float('nan'), 0, 0]], [0, 0, -1.2])


if __name__ == '__main__':
    unittest.main()
