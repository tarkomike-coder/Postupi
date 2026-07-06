import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))


class StartupCatchupTests(unittest.TestCase):
    def test_catchup_needed_when_service_starts_after_missed_slot(self):
        from workers.scheduler import needs_startup_catchup

        now = datetime(2026, 7, 6, 13, 12)
        last_ok_started_at = datetime(2026, 7, 5, 21, 0)

        self.assertTrue(
            needs_startup_catchup(
                now=now,
                last_ok_started_at=last_ok_started_at,
                schedule_times=["09:00", "21:00"],
            )
        )

    def test_catchup_not_needed_when_latest_due_slot_already_ran(self):
        from workers.scheduler import needs_startup_catchup

        now = datetime(2026, 7, 6, 13, 12)
        last_ok_started_at = datetime(2026, 7, 6, 9, 0)

        self.assertFalse(
            needs_startup_catchup(
                now=now,
                last_ok_started_at=last_ok_started_at,
                schedule_times=["09:00", "21:00"],
            )
        )

    def test_catchup_not_needed_before_first_daily_slot(self):
        from workers.scheduler import needs_startup_catchup

        now = datetime(2026, 7, 6, 8, 30)
        last_ok_started_at = datetime(2026, 7, 5, 21, 0)

        self.assertFalse(
            needs_startup_catchup(
                now=now,
                last_ok_started_at=last_ok_started_at,
                schedule_times=["09:00", "21:00"],
            )
        )


if __name__ == "__main__":
    unittest.main()
