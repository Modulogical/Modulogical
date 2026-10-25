-- Replaces the single-column `models` table. One row per (node, model) so the
-- chat can tell which models are served by a node that is currently online.
DROP TABLE IF EXISTS models;

CREATE TABLE models (
    node_id TEXT NOT NULL,
    model   TEXT NOT NULL,
    PRIMARY KEY (node_id, model),
    FOREIGN KEY (node_id) REFERENCES inference_nodes (node_id) ON DELETE CASCADE
);

CREATE INDEX idx_models_model ON models (model);
