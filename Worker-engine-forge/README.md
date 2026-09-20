# Modulogical Engine Forge

Cloudflare Worker + D1. No Python, `.venv`, PC, or inference dependency.

Development:
`wrangler dev`

Deployment:
`wrangler deploy`

Routes:
- GET /health
- POST /produce/module
- POST /produce/personality
- POST /produce/workflow
- POST /produce/webvector

Submitted code is stored as data; this Worker never executes it.
