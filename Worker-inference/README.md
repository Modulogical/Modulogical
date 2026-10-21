# Modulogical Inference Worker

Python Cloudflare Worker using FastAPI and `pyproject.toml`.

## Requirements
- Python 3.13+
- `uv`
- Node.js (Wrangler tooling)
- Cloudflare zone for `modulogical.com`
- Existing D1 database

## Configure
1. In `wrangler.jsonc`, replace `database_name` with the exact name of your existing D1 database. The database ID is set to the Modulogical D1 ID from the existing project context.
2. Add secrets (never commit them to source control):

   ```powershell
   uv run pywrangler secret put CLOUDFLARE_API_TOKEN
   uv run pywrangler secret put CLOUDFLARE_ACCOUNT_ID
   uv run pywrangler secret put CLOUDFLARE_ZONE_ID
   ```

3. Apply the migration, replacing the database name:

   ```powershell
   npx wrangler d1 execute YOUR_D1_DATABASE_NAME --remote --file=migrations/0001_inference_nodes.sql
   ```

## Run locally
```powershell
uv lock
uv run pywrangler dev
```

## Deploy
```powershell
uv run pywrangler deploy
```

## Initial routes
- `GET /health`
- `POST /v1/nodes/register` — registers a node and provisions its Cloudflare Tunnel.
- `POST /v1/nodes/{node_id}/heartbeat` — refreshes node status, hardware, and installed models.
- `POST /v1/nodes/{node_id}/disconnect` — marks a node offline.
- `POST /v1/nodes/select` — returns the best fresh online hostname for an installed model.

Node selection request:

```json
{
   "model": "gemma3:latest",
   "requirements": {
      "ram_gb": 8,
      "vram_mb": 4096,
      "cpu_cores": 4,
      "gpu": true
   }
}
```

`requirements` is optional; each numeric field defaults to zero and `gpu` defaults to `false`. Selection requires a heartbeat within 90 seconds and an exact case-insensitive installed-model match. The response includes `node_id`, `hostname`, `model`, and a hardware score. No eligible node returns HTTP 404.

## Security
- The Cloudflare API token stays in Worker secrets.
- A caller-supplied `account_id` is never proof of account ownership.
- Authenticate the user's existing Modu session before provisioning a tunnel.
- Per-node credentials are separate from the Cloudflare API token.
- Provisioning must be idempotent to prevent duplicate tunnels on retries.
- Hostnames are not an authentication boundary.
