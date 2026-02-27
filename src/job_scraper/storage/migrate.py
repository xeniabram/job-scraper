"""Migrate from v1 (old multi-table) schema to the current target schema.

v1 schema (prod)
-----------------
jobs              url, title, company, description, scraped_at (datetime), filtered_at
matched_jobs      url, title, company, skillset_match_percent, matched_at,
                  cv_about_me, cv_keywords, optimized_at, applied_at
rejected_jobs     url, role, reason, skillset_match_percent, rejected_at
rejected_manually url, title, company, skillset_match_percent, reason, rejected_at
failed_jobs       url, failed_at
learn             url, title, company, reason, user_note, correct_label,
                  skillset_match_percent, reviewed_at

Target schema
--------------
jobs          url, title, company, description, source, scraped_at  (pending only)
matched       url, title, company, description, match_pct, cv_about, cv_keywords, scraped_at
rejected      url, title, company, description, match_pct, reason, scraped_at
learn         url, title, company, match_pct, reason, user_note, correct_label
daily_stats   date, scraped, matched, rejected

Run from the project root:
    python -m job_scraper.storage.migrate
"""

import sqlite3
import sys
from pathlib import Path

from job_scraper.config import settings
from job_scraper.storage.DDL import _DDL

DB_PATH: Path = settings.data_dir / "results.db"

def migrate() -> None:
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    old_tables = ["jobs", "failed_jobs", "learn", "matched_jobs", "rejected_jobs", "rejected_manually"]

    # 1. rename old tables
    for table in old_tables:
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
    conn.commit()

    # 2. create new tables
    conn.executescript(_DDL)

    # 3. migrate pending jobs (unfiltered only)
    conn.execute("""
        INSERT INTO jobs (url, title, company, description, scraped_at)
        SELECT url, title, company, description, date(scraped_at)
        FROM jobs_old
        WHERE filtered_at IS NULL
    """)

    # 4. migrate matched_jobs -> matched
    conn.execute("""
        INSERT INTO matched (url, title, company, description, match_pct, cv_about, cv_keywords, scraped_at)
        SELECT mj.url, mj.title, mj.company, j.description,
               mj.skillset_match_percent, mj.cv_about_me, mj.cv_keywords, date(j.scraped_at)
        FROM matched_jobs_old mj
        LEFT JOIN jobs_old j ON mj.url = j.url
    """)

    # 5. migrate rejected_jobs -> rejected
    conn.execute("""
        INSERT INTO rejected (url, title, company, description, match_pct, reason, scraped_at)
        SELECT rj.url, j.title, j.company, j.description,
               rj.skillset_match_percent, rj.reason, date(j.scraped_at)
        FROM rejected_jobs_old rj
        LEFT JOIN jobs_old j ON rj.url = j.url
    """)

    # 6. migrate learn
    conn.execute("""
        INSERT INTO learn (url, title, company, match_pct, reason, user_note, correct_label)
        SELECT url, title, company, skillset_match_percent, reason, user_note, correct_label
        FROM learn_old
    """)

    # 7. migrate rejected_manually -> learn
    conn.execute("""
        INSERT OR IGNORE INTO learn (url, title, company, match_pct, reason, correct_label)
        SELECT url, title, company, skillset_match_percent, reason, 'rejected'
        FROM rejected_manually_old
    """)

    # 8. populate daily_stats from historical data
    conn.execute("""
        INSERT INTO daily_stats (date, scraped, matched, rejected)
        SELECT
            date(j.scraped_at)  AS d,
            COUNT(*)            AS scraped,
            COUNT(mj.url)       AS matched,
            COUNT(rj.url) + COUNT(rm.url) AS rejected
        FROM jobs_old j
        LEFT JOIN matched_jobs_old mj  ON j.url = mj.url
        LEFT JOIN rejected_jobs_old rj ON j.url = rj.url
        LEFT JOIN rejected_manually_old rm ON j.url = rm.url
        WHERE j.scraped_at IS NOT NULL
        GROUP BY date(j.scraped_at)
    """)

    conn.commit()

    # print summary
    print("Migration complete. New table counts:")
    for table in ["jobs", "matched", "rejected", "learn", "daily_stats"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")

    # 9. drop old tables
    for table in old_tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}_old")
    conn.commit()

    conn.close()
    print("Old tables dropped. Done!")


if __name__ == "__main__":
    migrate()
