from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from core.image_detector import Detector, Profile
from core.state_machine import SafetyError


class DetectorTests(unittest.TestCase):
    def test_user_similarity_applies_to_all_templates(self):
        profile = Profile.__new__(Profile)
        profile.templates = {"button": {"threshold": .9}, "item": {"threshold": .97}}
        profile.apply_similarity(87.5)
        self.assertTrue(all(spec["threshold"] == .875 for spec in profile.templates.values()))
        for invalid in (True, 49, 101, float('nan')):
            with self.assertRaises(SafetyError):
                profile.apply_similarity(invalid)

    def test_page_arrow_ignores_changing_translucent_background(self):
        template = np.full((30, 20, 3), 20, dtype=np.uint8)
        cv2.polylines(template, [np.array([[4, 4], [15, 15], [4, 26]])], False, (200, 200, 200), 2)
        search = template.copy()
        search[np.all(template == 20, axis=2)] = 80
        detector = Detector.__new__(Detector)
        score = detector.match_scores(search, template, "page_two")
        self.assertGreater(1 - float(score[0, 0]), .99)
        blank = np.full_like(search, 80)
        self.assertLess(1 - float(detector.match_scores(blank, template, "page_two")[0, 0]), .97)
        self.assertGreater(1 - float(detector.match_scores(search, template, "shop_menu")[0, 0]), .99)

    def setUp(self):
        self.detector = Detector.__new__(Detector)
        self.template = np.random.default_rng(12).integers(30, 240, (12, 12, 3), dtype=np.uint8)
        self.detector.images = {"target": self.template}
        self.detector.profile = SimpleNamespace(resolution=(2560, 1440), templates={"target": {"roi": [0, 0, 100, 100], "threshold": .99}})
        self.frame = np.zeros((100, 100, 3), dtype=np.uint8)

    def test_single_exact_icon(self):
        self.frame[20:32, 30:42] = self.template
        self.assertEqual(self.detector.one(self.frame, "target"), (36, 26))

    def test_ambiguous_match_stops(self):
        self.frame[20:32, 30:42] = self.template
        self.frame[60:72, 60:72] = self.template
        with self.assertRaises(SafetyError):
            self.detector.one(self.frame, "target")

    def test_missing_match_stops(self):
        with self.assertRaises(SafetyError):
            self.detector.one(self.frame, "target")

    def test_roi_excludes_unrelated_inventory(self):
        self.frame[20:32, 30:42] = self.template
        self.assertEqual(self.detector.find_all(self.frame, "target", [50, 50, 50, 50]), [])

    def test_diagnostic_reports_location_and_threshold(self):
        self.frame[20:32, 30:42] = self.template
        result = self.detector.diagnose(self.frame, "target")
        self.assertEqual(result["matches"], [(36, 26)])
        self.assertGreater(result["similarity"], .99)
        self.assertEqual(result["threshold"], .99)
        self.assertEqual(result["best"], (30, 20, 12, 12))

    def test_diagnostic_reports_failure_without_lowering_threshold(self):
        result = self.detector.diagnose(self.frame, "target")
        self.assertEqual(result["matches"], [])
        self.assertLess(result["similarity"], result["threshold"])

    def test_diagnostic_rejects_region_outside_screen(self):
        with self.assertRaises(SafetyError):
            self.detector.diagnose(self.frame, "target", [-1, 0, 50, 50])
