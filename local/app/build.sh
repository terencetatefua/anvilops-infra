#!/usr/bin/env bash
# Build the demo app and push to the local registry, then (re)deploy.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="localhost:5001/anvil-app:dev"

echo ">> Building $IMAGE ..."
docker build -t "$IMAGE" "$HERE"
echo ">> Pushing to local registry ..."
docker push "$IMAGE"

echo ">> Creating namespace + applying manifests ..."
kubectl create namespace anvil --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$HERE/../gitops/apps/anvil-app.yaml"
kubectl -n anvil rollout restart deploy/anvil-app
kubectl -n anvil rollout status deploy/anvil-app --timeout=120s

echo
echo ">> Done. Test it:"
echo "   curl http://anvil-app.local/healthz"
echo "   curl -X POST http://anvil-app.local/chat -H 'Content-Type: application/json' -d '{\"prompt\":\"say hi in one sentence\"}'"
