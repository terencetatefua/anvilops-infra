# GitOps configs (managed by ArgoCD)
# anvil-app

A minimal HTTP service that exposes a chat endpoint backed by a **pluggable
AI provider**. Local development uses Ollama; on AWS the same code talks to
Bedrock — the application doesn't change, only an environment variable does.

## Endpoints

The app exposes three HTTP endpoints on port `8000`.

### `GET /`

Sanity check / app metadata.

**Response — 200 OK:**
```json
{
  "app": "anvil-app",
  "backend": "ollama",
  "try": "POST /chat {\"prompt\": \"hello\"}"
}
```

The `backend` field reflects the current `AI_BACKEND` env var so you can
verify which provider this pod is configured for.

---

### `GET /healthz`

Liveness/readiness probe. Used by Kubernetes `readinessProbe` and by Docker
`HEALTHCHECK`. Returns immediately without contacting the AI backend.

**Response — 200 OK:**
```json
{
  "status": "ok",
  "backend": "ollama"
}
```

This endpoint is intentionally **shallow** — it does not call the AI provider.
A "healthy" pod means the HTTP server is up; it does *not* guarantee Ollama or
Bedrock is reachable. That's by design — pod readiness shouldn't depend on
upstream dependencies, or one slow Ollama would mark every pod unhealthy.

---

### `POST /chat`

The actual chat endpoint — sends a prompt to the configured AI backend and
returns the response.

**Request body:**
```json
{ "prompt": "say hi in one sentence" }
```

**Response — 200 OK:**
```json
{
  "backend": "ollama",
  "response": "Hi there! How can I help you today?"
}
```

**Errors:**

| Status | Body | Cause |
|---|---|---|
| 400 | `{"error": "missing 'prompt'"}` | No `prompt` field in request body |
| 502 | `{"error": "ollama backend failed", "detail": "..."}` | AI backend unreachable or returned an error |
| 404 | `{"error": "not found"}` | Path other than `/`, `/healthz`, `/chat` |

## Call examples

Once the chart is deployed and `anvil-app.local` is in your hosts file:

```bash
# Sanity check
curl http://anvil-app.local/

# Health probe
curl http://anvil-app.local/healthz

# Real call (requires Ollama running on the host)
curl -X POST http://anvil-app.local/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "explain Kubernetes namespaces in one sentence"}'
```

If `anvil-app.local` doesn't resolve, fall back to port-forward:

```bash
kubectl -n anvil port-forward svc/anvil-app-dev-anvil-app 8000:80
# in another terminal:
curl http://localhost:8000/healthz
```

## The AI-backend swap

This is the architectural feature of the app. One function in `main.py`
dispatches based on `AI_BACKEND`:

```python
def ask(prompt: str) -> str:
    return ask_bedrock(prompt) if AI_BACKEND == "bedrock" else ask_ollama(prompt)
```

The Helm chart picks which env vars to inject based on the same `ai.backend`
value (see `gitops/charts/anvil-app/templates/deployment.yaml`):

| `AI_BACKEND` value | Required env vars | Implementation |
|---|---|---|
| `ollama` | `OLLAMA_URL`, `OLLAMA_MODEL` | HTTP POST to `/api/generate` |
| `bedrock` | `BEDROCK_MODEL_ID` (+ AWS creds via IRSA) | `boto3` client, `converse` API |

**On AWS, the only change is one line in values:**
```yaml
ai:
  backend: bedrock
```

Nothing in `main.py`, the Dockerfile, the Service, or the Ingress changes.

## Building the image

```bash
docker build -t localhost:5001/anvil-app:dev .
docker push localhost:5001/anvil-app:dev
```

Production characteristics of the image:

- **Multi-stage build** — builder stage installs deps; runtime stage is a
  minimal `python:3.12.8-slim` with only what's needed
- **Non-root user** — runs as UID/GID `10001`, declared numerically so
  Kubernetes `runAsNonRoot: true` can verify
- **Pinned base tag** — `python:3.12.8-slim` (not `:latest`) for reproducibility
- **`HEALTHCHECK` baked in** — `docker ps` shows healthy/unhealthy
- **Exec-form `CMD`** — Python runs as PID 1 and receives signals directly

The matching Pod-level security context in the chart enforces this from
the cluster side: `runAsUser: 10001`, `readOnlyRootFilesystem: true`,
`capabilities: drop ["ALL"]`, `seccompProfile: RuntimeDefault`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `AI_BACKEND` | `ollama` | Which provider to call — `ollama` or `bedrock` |
| `PORT` | `8000` | HTTP listen port |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama server URL (only used when `AI_BACKEND=ollama`) |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model name |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-haiku-20240307-v1:0` | Bedrock model (only used when `AI_BACKEND=bedrock`) |
