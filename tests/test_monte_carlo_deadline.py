import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))


class MonteCarloDeadlineTests(unittest.TestCase):
    def test_new_applicant_risk_is_zero_after_deadline(self):
        from services.monte_carlo import _deadline_context

        ctx = _deadline_context(
            now=datetime.fromisoformat("2026-07-25T17:00:01+03:00"),
            application_deadline_at="2026-07-25T17:00:00+03:00",
            campaign_start_at="2026-06-20T00:00:00+03:00",
        )

        self.assertEqual(ctx["time_left_ratio"], 0)
        self.assertEqual(ctx["new_applicant_risk_factor"], 0)

    def test_new_applicant_risk_uses_time_left_power(self):
        from services.monte_carlo import _deadline_context

        ctx = _deadline_context(
            now=datetime.fromisoformat("2026-07-07T20:30:00+03:00"),
            application_deadline_at="2026-07-25T17:00:00+03:00",
            campaign_start_at="2026-06-20T00:00:00+03:00",
        )

        self.assertAlmostEqual(ctx["time_left_ratio"], 0.5)
        self.assertAlmostEqual(ctx["new_applicant_risk_factor"], 0.5 ** 0.7)

    def test_expected_new_applicants_depends_on_risk_factor(self):
        from services.monte_carlo import _expected_new_applicants_by_direction

        grouped = {
            "a": [(1, 1, 280, True), (2, 2, 280, True)],
            "b": [(1, 1, 270, False)],
            "target": [(1, 1, 260, True)],
        }

        expected = _expected_new_applicants_by_direction(
            grouped,
            protected_codes={"target"},
            new_applicant_risk_factor=0.5,
            share=0.1,
        )

        self.assertAlmostEqual(expected[1], 0.1)
        self.assertAlmostEqual(expected[2], 0.05)
        self.assertEqual(
            _expected_new_applicants_by_direction(grouped, {"target"}, 0)[1],
            0,
        )


if __name__ == "__main__":
    unittest.main()
