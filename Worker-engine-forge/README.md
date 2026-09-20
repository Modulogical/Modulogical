# Modulogical Engine Forge

Cloudflare Python Worker for submitting Module, Personality, Workflow, and WebVector items to the Engine Forge D1 queue.

## Runtime
- Cloudflare Workers Python runtime
- FastAPI + ASGI
- Cloudflare D1
- Cloudflare Python dependencies bundled in `.venv` using the same working structure as the Modulogical backend
- No dependency on the inference PC

## Routes
- `GET /health`
- `GET /`
- `POST /produce/module`
- `POST /produce/personality`
- `POST /produce/workflow`
- `POST /produce/webvector`

## Architecture

Engine Forge operations run entirely on Cloudflare. The inference PC is not contacted by this Worker and is not required for `/health` or `/produce/*`.

The submitted code is stored as data in D1. This Worker does not execute submitted code.

## Deployment

From this directory:

```text
wrangler deploy
```

The Worker uses Engine Forge D1:

`28ae57bc-fdb7-4fdb-a327-1e68736be0b2`

If existing queue tables do not have their `*_code` columns, run `existing-db-code-columns.sql` against the remote D1 database once. For a new database, use `engine-forge-schema.sql`.

## Important

The `.venv` directory is intentionally included because this project follows the same Cloudflare Python Worker packaging structure as the working Modulogical backend. Do not remove it before deployment.
