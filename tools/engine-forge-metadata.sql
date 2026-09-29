CREATE TABLE metadata (
    item_id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    developer_id TEXT NOT NULL,
    developer_tier TEXT NOT NULL,
    item_name TEXT NOT NULL,
    item_description TEXT NOT NULL
)