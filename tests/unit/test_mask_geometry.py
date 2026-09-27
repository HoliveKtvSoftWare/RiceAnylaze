import os
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[2]
os.environ.setdefault("YOLO_CONFIG_DIR", str(BACKEND_DIR / ".ultralytics"))


def require_mask_geometry():
    try:
        from app.domain.geometry import mask_geometry
    except ImportError as exc:
        raise AssertionError("mask topology post-processing is not implemented") from exc
    return mask_geometry


class MaskTopologyTests(unittest.TestCase):
    def test_extract_topology_keeps_hole_and_drops_tiny_island(self):
        extract_topology_contours = require_mask_geometry().extract_topology_contours

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[10:90, 10:90] = 1
        mask[30:70, 30:70] = 0
        mask[2:4, 2:4] = 1

        contours = extract_topology_contours(mask)

        self.assertEqual([item["role"] for item in contours], ["outer", "hole"])
        self.assertEqual({item["component_id"] for item in contours}, {0})

    def test_topology_geometry_subtracts_holes_and_counts_both_boundaries(self):
        topology_geometry = require_mask_geometry().topology_geometry

        shapes = [
            {
                "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                "flags": {"mask_topology": True, "contour_role": "outer"},
            },
            {
                "points": [[2, 2], [4, 2], [4, 4], [2, 4]],
                "flags": {"mask_topology": True, "contour_role": "hole"},
            },
        ]

        area, perimeter = topology_geometry(shapes)

        self.assertEqual(area, 96.0)
        self.assertEqual(perimeter, 48.0)


class SideAssignmentTests(unittest.TestCase):
    def test_reassigns_only_bundles_clearly_inside_the_other_side(self):
        reassign_side_bundle_labels = require_mask_geometry().reassign_side_bundle_labels

        side1 = np.zeros((20, 20), dtype=np.uint8)
        side2 = np.zeros((20, 20), dtype=np.uint8)
        side1[:, :8] = 1
        side2[:, 12:] = 1
        labels = ["side1", "side2", "side1_small", "side2_big", "side1_big"]
        boxes = np.array([
            [0, 0, 8, 20],
            [12, 0, 20, 20],
            [14, 4, 18, 8],
            [14, 10, 18, 14],
            [8, 4, 12, 8],
        ], dtype=np.float32)

        corrected, corrections = reassign_side_bundle_labels(
            labels, boxes, {"side1": side1, "side2": side2}
        )

        self.assertEqual(corrected[2], "side2_small")
        self.assertEqual(corrected[3], "side2_big")
        self.assertEqual(corrected[4], "side1_big")
        self.assertEqual(corrections, {2: "side1_small"})

    def test_assignment_uses_outer_envelope_and_nearest_side(self):
        from app.domain.geometry.mask_geometry import reassign_side_bundle_labels

        side1 = np.zeros((30, 30), dtype=np.uint8)
        side2 = np.zeros((30, 30), dtype=np.uint8)
        side1[2:12, 2:12] = 1
        side1[5:9, 5:9] = 0
        side2[18:28, 18:28] = 1
        labels = ["side1", "side2", "side1_small", "side1_big"]
        boxes = np.array([
            [2, 2, 12, 12],
            [18, 18, 28, 28],
            [6, 6, 8, 8],
            [15, 22, 17, 26],
        ], dtype=np.float32)

        corrected, corrections = reassign_side_bundle_labels(
            labels, boxes, {"side1": side1, "side2": side2}
        )

        self.assertEqual(corrected[2], "side1_small")
        self.assertEqual(corrected[3], "side2_big")
        self.assertEqual(corrections, {3: "side1_big"})


class LabelMeConversionTests(unittest.TestCase):
    def test_preview_preparation_removes_dense_stair_steps(self):
        from app.services import yolo_inference

        prepare_preview_points = getattr(yolo_inference, "prepare_preview_points", None)
        self.assertIsNotNone(prepare_preview_points, "preview contour simplification is not implemented")

        points = [
            [0, 10], [2, 9], [4, 10], [6, 9], [8, 10], [10, 9],
            [12, 10], [14, 9], [16, 10], [18, 9], [20, 10],
            [20, 20], [0, 20],
        ]

        prepared = prepare_preview_points(points, iterations=1)

        self.assertLess(len(prepared), len(points))
        self.assertEqual(points[0], [0, 10])

    def test_region_json_contains_outer_and_hole_without_merging_island(self):
        from app.services.yolo_inference import convert_to_labelme_format

        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[10:90, 10:90] = 1
        mask[30:70, 30:70] = 0
        mask[2:4, 2:4] = 1
        fallback_polygon = np.array([[2, 2], [90, 10], [90, 90], [10, 90]])

        try:
            data = convert_to_labelme_format(
                "sample.tif",
                (100, 100),
                [[fallback_polygon]],
                [["side1"]],
                {0: "side1"},
                smooth=False,
                embed_image=False,
                raw_masks_list=[{0: mask}],
                topology_labels=("side1",),
            )
        except TypeError as exc:
            self.fail(f"topology-aware LabelMe conversion is not implemented: {exc}")

        self.assertEqual(len(data["shapes"]), 2)
        self.assertEqual(
            {shape["flags"]["contour_role"] for shape in data["shapes"]},
            {"outer", "hole"},
        )
        self.assertTrue(all(shape["flags"]["mask_topology"] for shape in data["shapes"]))

    def test_preview_smoothing_does_not_mutate_measurement_points(self):
        from app.services.yolo_inference import draw_polygons_on_image

        points = [[10, 10], [50, 10], [50, 50], [10, 50]]
        shapes = [{"label": "side1_small", "points": points, "flags": {}}]
        image = Image.new("RGB", (64, 64), "white")

        try:
            result = draw_polygons_on_image(
                image,
                shapes,
                colors={"side1_small": (255, 0, 0, 255)},
                preview_smooth=True,
                smooth_iterations=1,
            )
        except TypeError as exc:
            self.fail(f"preview-only smoothing is not implemented: {exc}")

        self.assertEqual(shapes[0]["points"], points)
        self.assertEqual(result.getpixel((10, 10)), (255, 255, 255))
        self.assertEqual(result.getpixel((20, 10)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
