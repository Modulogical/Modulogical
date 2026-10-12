CREATE TABLE memories (     
    id INTEGER PRIMARY KEY AUTOINCREMENT,     
    account_id TEXT NOT NULL,     
    content TEXT NOT NULL,     
    category TEXT,     
    confidence REAL,     
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )