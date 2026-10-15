CREATE TABLE heartbeats (
    node_id TEXT PRIMARY KEY,
    node_secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_heartbeat TEXT NOT NULL
)