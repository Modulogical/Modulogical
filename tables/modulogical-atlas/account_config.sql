CREATE TABLE account_config (
    account_id TEXT PRIMARY KEY,     
    model TEXT NOT NULL DEFAULT 'gemma3:latest',     
    personality TEXT NOT NULL DEFAULT '',     
    system_instructions TEXT NOT NULL DEFAULT '',     
)