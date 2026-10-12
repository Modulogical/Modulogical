CREATE TABLE accounts (     
    id TEXT PRIMARY KEY,     
    username TEXT NOT NULL UNIQUE,     
    name TEXT NOT NULL,     
    password_hash TEXT NOT NULL,     
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP , 
    account_subscription_status TEXT NOT NULL DEFAULT 'free'
    )