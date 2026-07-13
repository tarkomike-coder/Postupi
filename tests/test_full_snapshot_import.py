import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))


def _reset_backend_modules():
    prefixes = ("api", "config", "database", "models", "services", "workers")
    for name in list(sys.modules):
        if name in prefixes or name.startswith(tuple(prefix + "." for prefix in prefixes)):
            del sys.modules[name]


def _prepare_source_db(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.executescript(
        """
        create table mai_snapshots (
            id integer primary key,
            status text not null,
            started_at text,
            finished_at text,
            groups_count integer,
            rows_count integer,
            unique_applications_count integer
        );
        create table mai_competition_groups (
            id integer primary key,
            group_id integer not null,
            okso_code text,
            name text not null,
            seats integer
        );
        create table mai_applicant_rows (
            id integer primary key,
            snapshot_id integer not null,
            group_id integer not null,
            application_id text not null,
            position integer,
            score integer,
            priority integer,
            consent boolean,
            category text
        );
        """
    )
    cur.execute(
        "insert into mai_snapshots values (1, 'ok', '2026-07-10 06:00:00', '2026-07-10 06:10:00', 2, 3, 2)"
    )
    cur.executemany(
        "insert into mai_competition_groups values (?, ?, ?, ?, ?)",
        [
            (1, 117494, "09.03.03", "Прикладная информатика", 1),
            (2, 117500, "09.03.04", "Программная инженерия", 1),
        ],
    )
    cur.executemany(
        """
        insert into mai_applicant_rows
        (snapshot_id, group_id, application_id, position, score, priority, consent, category)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "999999", 1, 100, 2, True, None),
            (1, 2, "999999", 1, 100, 1, True, None),
            (1, 1, "1422086", 2, 90, 1, True, None),
        ],
    )
    conn.commit()
    conn.close()


class FullSnapshotImportTests(unittest.TestCase):
    def test_full_cascade_uses_direction_outside_tracked_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source.sqlite")
            target_path = os.path.join(tmp, "target.sqlite")
            _prepare_source_db(source_path)

            os.environ["DATABASE_URL"] = f"sqlite:///{target_path}"
            os.environ["FULL_SNAPSHOT_DATABASE_URL"] = f"sqlite:///{source_path}"
            _reset_backend_modules()

            from database.migrations import ensure_schema
            from database.db import SessionLocal, engine
            from models import CompetitorSnapshot, Direction, SimulationResult, TrackedApplicant
            from services.full_snapshot_import import run_mai_full_snapshot_sync

            ensure_schema()
            run = run_mai_full_snapshot_sync(trigger="test")

            db = SessionLocal()
            try:
                self.assertEqual(run.status, "ok", run.error_message)
                self.assertEqual(run.model_version, "full_cascade_v1")
                self.assertEqual(run.coverage, "full")
                self.assertEqual(db.query(Direction).count(), 2)
                self.assertEqual(db.query(CompetitorSnapshot).count(), 3)

                applicant = db.query(TrackedApplicant).filter_by(unique_code="1422086").one()
                pi = db.query(Direction).filter_by(external_group_id=117494).one()
                sim = (
                    db.query(SimulationResult)
                    .filter_by(run_id=run.id, tracked_applicant_id=applicant.id, direction_id=pi.id)
                    .one()
                )
                self.assertTrue(sim.deterministic_admitted)
                self.assertEqual(sim.real_competitor_position, 1)
                self.assertEqual(sim.real_competitor_count, 0)
            finally:
                db.close()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
