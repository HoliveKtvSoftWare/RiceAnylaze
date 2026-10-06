import unittest


class LeafMetricTopologyTests(unittest.TestCase):
    def test_leaf_metrics_use_net_topology_area(self):
        analysis_data = {
            "shapes": [
                {
                    "label": "side1",
                    "group_id": 7,
                    "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "flags": {"mask_topology": True, "contour_role": "outer"},
                },
                {
                    "label": "side1",
                    "group_id": 7,
                    "points": [[2, 2], [4, 2], [4, 4], [2, 4]],
                    "flags": {"mask_topology": True, "contour_role": "hole"},
                },
            ]
        }

        from app.domain.analysis.families import leaf as leaf_metrics
        metrics = leaf_metrics.compute(analysis_data, "um", 1.0)

        self.assertEqual(metrics["side1Area"], 96.0)
        self.assertEqual(metrics["side1Perimeter"], 48.0)


if __name__ == "__main__":
    unittest.main()
