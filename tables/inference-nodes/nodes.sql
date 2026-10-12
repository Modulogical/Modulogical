CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offline',
    hostname TEXT NOT NULL,
    tunnel_id TEXT,
    dns_record_id TEXT NOT NULL,
    last_heartbeat REAL,
    last_success REAL,
    total_responses INTEGER DEFAULT 0,
    total_uptime_seconds INTEGER DEFAULT 0,
    app_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)