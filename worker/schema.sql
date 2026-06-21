CREATE TABLE IF NOT EXISTS youtube_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    thumbnail_url TEXT,
    channel_name TEXT,
    channel_url TEXT,
    video_url TEXT NOT NULL,
    duration TEXT,
    published_at TEXT,
    grade_animal_friendly TEXT CHECK(grade_animal_friendly IN ('friendly', 'partial', 'not_friendly')),
    grade_scientific TEXT CHECK(grade_scientific IN ('accurate', 'partial', 'inaccurate')),
    grade_emotional_manipulation TEXT CHECK(grade_emotional_manipulation IN ('yes', 'no')),
    summary TEXT,
    raw_gemini_response TEXT,
    grading_method TEXT CHECK(grading_method IN ('api', 'browser')),
    status TEXT DEFAULT 'graded' CHECK(status IN ('graded', 'skipped', 'error')),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS instagram_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT UNIQUE NOT NULL,
    title TEXT,
    thumbnail_url TEXT,
    post_url TEXT NOT NULL,
    media_type TEXT CHECK(media_type IN ('image', 'video', 'reel', 'carousel')),
    username TEXT,
    profile_url TEXT,
    published_at TEXT,
    grade_animal_friendly TEXT CHECK(grade_animal_friendly IN ('friendly', 'partial', 'not_friendly')),
    grade_scientific TEXT CHECK(grade_scientific IN ('accurate', 'partial', 'inaccurate')),
    grade_emotional_manipulation TEXT CHECK(grade_emotional_manipulation IN ('yes', 'no')),
    summary TEXT,
    raw_gemini_response TEXT,
    grading_method TEXT CHECK(grading_method IN ('api', 'browser')),
    status TEXT DEFAULT 'graded' CHECK(status IN ('graded', 'skipped', 'error')),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL CHECK(platform IN ('youtube', 'instagram')),
    search_query TEXT NOT NULL,
    total_results INTEGER DEFAULT 0,
    relevant_count INTEGER DEFAULT 0,
    irrelevant_count INTEGER DEFAULT 0,
    strategy_notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('youtube', 'instagram')),
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'graded', 'error')),
    created_at TEXT DEFAULT (datetime('now'))
);
