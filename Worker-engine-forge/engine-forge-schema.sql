CREATE TABLE IF NOT EXISTS module_queue (
title TEXT NOT NULL, developer_id TEXT NOT NULL, developer_tier TEXT NOT NULL,
module_id TEXT NOT NULL, schema TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
display TEXT NOT NULL DEFAULT '', module_version TEXT NOT NULL, module_price TEXT NOT NULL,
module_dependencies TEXT NOT NULL, module_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personality_queue (
title TEXT NOT NULL, developer_id TEXT NOT NULL, developer_tier TEXT NOT NULL,
personality_id TEXT NOT NULL, schema TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
display TEXT NOT NULL DEFAULT '', personality_version TEXT NOT NULL, personality_price TEXT NOT NULL,
personality_dependencies TEXT NOT NULL, personality_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_queue (
title TEXT NOT NULL, developer_id TEXT NOT NULL, developer_tier TEXT NOT NULL,
workflow_id TEXT NOT NULL, schema TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
display TEXT NOT NULL DEFAULT '', workflow_version TEXT NOT NULL, workflow_price TEXT NOT NULL,
workflow_dependencies TEXT NOT NULL, workflow_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webvector_queue (
title TEXT NOT NULL, developer_id TEXT NOT NULL, developer_tier TEXT NOT NULL,
webvector_id TEXT NOT NULL, schema TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
display TEXT NOT NULL DEFAULT '', webvector_version TEXT NOT NULL, webvector_price TEXT NOT NULL,
webvector_dependencies TEXT NOT NULL, webvector_code TEXT NOT NULL
);
