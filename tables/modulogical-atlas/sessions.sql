CREATE TABLE sessions (     
    token_hash TEXT PRIMARY KEY,     
    account_id TEXT NOT NULL,     
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )