CREATE TABLE IF NOT EXISTS inference_nodes (
    node_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'online', 'idle', 'busy', 'offline', 'suspended')),
    hostname TEXT UNIQUE,
    tunnel_id TEXT UNIQUE,
    dns_record_id TEXT,
    hardware_json TEXT NOT NULL DEFAULT '{}',
    telemetry_json TEXT NOT NULL DEFAULT '{}',
    app_version TEXT,
    protocol_version INTEGER NOT NULL DEFAULT 1,
    last_heartbeat_at TEXT,
    last_success_at TEXT,
    total_responses INTEGER NOT NULL DEFAULT 0,
    total_uptime_seconds INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inference_nodes_account ON inference_nodes(account_id);
CREATE INDEX IF NOT EXISTS idx_inference_nodes_status ON inference_nodes(status);

CREATE TABLE IF NOT EXISTS inference_node_events (
    event_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES inference_nodes(node_id)
);
CREATE INDEX IF NOT EXISTS idx_inference_node_events_node_time
    ON inference_node_events(node_id, created_at);
