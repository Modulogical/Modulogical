CREATE TABLE conversations (     
    id INTEGER PRIMARY KEY AUTOINCREMENT,     
    account_id TEXT NOT NULL,     
    message TEXT NOT NULL,     
    response TEXT NOT NULL,     
    model TEXT,     
    temperature REAL,     
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,   
)