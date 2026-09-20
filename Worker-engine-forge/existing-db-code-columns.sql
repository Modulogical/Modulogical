-- Run this only against an existing Forge database whose queue tables
-- already exist without the *_code columns.
-- If a column already exists, skip that ALTER statement.

ALTER TABLE module_queue ADD COLUMN module_code TEXT NOT NULL DEFAULT '';
ALTER TABLE personality_queue ADD COLUMN personality_code TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_queue ADD COLUMN workflow_code TEXT NOT NULL DEFAULT '';
ALTER TABLE webvector_queue ADD COLUMN webvector_code TEXT NOT NULL DEFAULT '';
