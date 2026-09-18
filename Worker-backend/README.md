# Modulogical Python Backend Worker

This is the Atlas backend converted to a Cloudflare Python Worker.

It uses:

- FastAPI for the existing Python API
- Cloudflare D1 for accounts, sessions, conversations, memories, modules and config
- Argon2 for the existing Atlas password hashes
- `https://inference.modulogical.com/generate` for inference

## D1

Configured D1 database:

- Name: `modulogical-atlas`
- ID: `60274c4e-362a-4dda-ac2c-222ddbbe9e1a`
- Binding: `DB`

## Important migration change

The old backend's filesystem storage has been removed. The Worker does not use
`data/accounts`, `IDUser_dictionary.json`, or local JSON files. D1 is the source
of truth.

Existing Argon2 hashes in `accounts.password_hash` are verified directly with
`argon2-cffi`, so existing accounts can continue to use their passwords.

## Inference

Inference is intentionally separate from this Worker. The Worker sends a
non-streaming JSON request to:

`https://inference.modulogical.com/generate`

Your PC therefore only needs to be available when an inference request is made.

## Module registry

If your repository has `module_registry.py`, place it beside `src/main.py` or
adjust the import/package layout. The Worker has a safe fallback so the backend
can still deploy when the registry is not included; module execution will then
return `Module not found` until the registry is added.

## Deploy

From this directory, with Node.js and `uv` installed:

```powershell
uv run pywrangler dev
```

Then deploy:

```powershell
uv run pywrangler deploy
```

Cloudflare documents FastAPI Python Workers and D1 bindings here:
https://developers.cloudflare.com/workers/languages/python/packages/fastapi/
https://developers.cloudflare.com/d1/examples/query-d1-from-python-workers/
