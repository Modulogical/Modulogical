# Modulogical Worker-backend — D1 version

This version makes the Worker-backend the application backend and uses the
Cloudflare D1 binding `DB` for accounts, conversations, memories, modules,
configs, and sessions.

## Before deploying

Edit `wrangler.jsonc` and replace:

`https://YOUR-INFERENCE-WORKER-URL`

with the deployed URL of `modulogical-inference` (or your chosen inference
gateway).

## Important authentication note

The existing Atlas client/backend contract must send the same password hash
format stored in `accounts.password_hash`. This Worker does not hash a
plaintext password. If the existing frontend sends plaintext passwords,
authentication must be adapted to use a supported password-hashing service
before production.

## Routes

POST /register
POST /login
GET/POST /auth/check
POST /logout
GET/POST /context
POST /chat
GET/POST /modules

The Worker does not modify the migrated D1 data except when a normal runtime
operation calls the corresponding endpoint.
