CREATE TABLE heartbeats (
    node_id TEXT PRIMARY KEY,
    node_secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_heartbeat TEXT NOT NULL,
    cpu_utilisation TEXT NOT NULL,
    logical_processors TEXT NOT NULL,
    ram_available TEXT NOT NULL,
    ram_free_percent TEXT NOT NULL,
    gpu_vram_available TEXT NOT NULL,
    gpu_name TEXT NOT NULL,
    gpu_utilisation_percent TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    tunnel_hostname TEXT NOT NULL,
    models TEXT NOT NULL DEFAULT '[]'
)