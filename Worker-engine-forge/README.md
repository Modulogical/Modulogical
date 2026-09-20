# Modulogical Engine Forge — Cloudflare Worker

This version is deliberately Cloudflare-only for Forge operations.

## Runtime
- Cloudflare Worker
- Cloudflare D1
- No Python runtime required
- No local PC required
- No dependency on the inference server for Forge health or production

## Routes
- GET `/health`
- POST `/produce/module`
- POST `/produce/personality`
- POST `/produce/workflow`
- POST `/produce/webvector`

## Important architecture

Engine Forge stores submissions in Cloudflare D1. The `*_code` fields are
stored as data; this Worker does not execute submitted code.

The inference PC is only needed by Atlas when a model actually needs to
execute/use a module. It is intentionally not contacted by Engine Forge.

## Deployment

`wrangler.jsonc` already points at the Forge D1 database:

`28ae57bc-fdb7-4fdb-a327-1e68736be0b2`

If the existing queue tables were created without code columns, run
`existing-db-code-columns.sql` once before deploying this version.

If the database is new, use `engine-forge-schema.sql`.

## Security note

The current API preserves the existing `developer_id` request field. For a
production marketplace, the Worker should eventually derive the developer
identity from authenticated credentials rather than trusting a client-supplied
developer_id. That can be added without introducing a dependency on the
inference PC.
