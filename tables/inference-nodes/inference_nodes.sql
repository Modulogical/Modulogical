CREATE TABLE inference_nodes (
    node_id TEXT PRIMARY KEY,
    node_secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata_json TEXT NOT NULL,
    cpu TEXT NOT NULL,
    os TEXT NOT NULL,
    logical_processors TEXT NOT NULL,
    physical_cores TEXT NOT NULL,
    gpu TEXT NOT NULL,
    vram TEXT NOT NULL,
    ram TEXT NOT NULL,
    total_storage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    tunnel_id TEXT NOT NULL,
    tunnel_status TEXT NOT NULL DEFAULT 'pending',
    tunnel_created_at TEXT NOT NULL,
    tunnel_hostname TEXT NOT NULL
)

#tunnel_id, tunnel_status, tunnel_created_at