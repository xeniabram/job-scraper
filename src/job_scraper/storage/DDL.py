_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    company     TEXT,
    description TEXT,
    source      TEXT,
    scraped_at  TEXT DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS matched (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    company     TEXT,
    description TEXT,
    match_pct   INTEGER,
    cv_about    TEXT,
    cv_keywords TEXT,
    scraped_at  TEXT
);

CREATE TABLE IF NOT EXISTS rejected (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    company     TEXT,
    description TEXT,
    match_pct   INTEGER,
    reason      TEXT,
    scraped_at  TEXT
);

CREATE TABLE IF NOT EXISTS learn (
    url           TEXT PRIMARY KEY,
    title         TEXT,
    company       TEXT,
    match_pct     INTEGER,
    reason        TEXT,
    user_note     TEXT,
    correct_label TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date     TEXT PRIMARY KEY DEFAULT (date('now')),
    scraped  INTEGER NOT NULL DEFAULT 0,
    matched  INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0
);

"""