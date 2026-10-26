from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from core.image_detector import Detector
from core.state_machine import SafetyError


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = Detector.__new__(Detector)
        self.template = np.random.default_rng(12).integers(30, 240, (12, 12, 3), dtype=np.uint8)
        self.detector.images = {"target": self.template}
        self.detector.profile = SimpleNamespace(templates={"target": {"roi": [0, 0, 100, 100], "threshold": .99}})
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
