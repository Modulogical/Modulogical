CREATE TABLE inference_nodes (
    node_id TEXT PRIMARY KEY,
    node_secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL
)