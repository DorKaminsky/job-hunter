import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'jobs.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT,
    field       TEXT,
    description TEXT,
    requirements TEXT,
    url         TEXT,
    location    TEXT,
    min_exp     INTEGER,
    discovered  TEXT,
    source      TEXT DEFAULT 'goozali',
    scraped_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    score       INTEGER,
    keywords    TEXT,
    reason      TEXT,
    feedback    TEXT DEFAULT '',
    matched_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT NOT NULL REFERENCES jobs(id),
    status         TEXT DEFAULT 'new',
    pdf_path       TEXT,
    tailored_json  TEXT,
    interview_stage TEXT DEFAULT '',
    notes          TEXT DEFAULT '',
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_profile (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # migrations for existing DBs
    cols_jobs = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if 'source' not in cols_jobs:
        conn.execute("ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT 'goozali'")
    cols_apps = [r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()]
    if 'tailored_json' not in cols_apps:
        conn.execute("ALTER TABLE applications ADD COLUMN tailored_json TEXT")
    if 'interview_stage' not in cols_apps:
        conn.execute("ALTER TABLE applications ADD COLUMN interview_stage TEXT DEFAULT ''")
    if 'notes' not in cols_apps:
        conn.execute("ALTER TABLE applications ADD COLUMN notes TEXT DEFAULT ''")
    cols_matches = [r[1] for r in conn.execute("PRAGMA table_info(matches)").fetchall()]
    if 'feedback' not in cols_matches:
        conn.execute("ALTER TABLE matches ADD COLUMN feedback TEXT DEFAULT ''")
    conn.commit()
    conn.close()
