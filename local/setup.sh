#!/usr/bin/env bash
# ============================================================================
# Bring up the entire LOCAL stack on Docker Desktop. Idempotent.
#
#   ./setup.sh
#
# What it does, in order:
#   1. Local Docker registry (ECR stand-in) at localhost:5001
#   2. kind cluster (EKS stand-in), wired to that registry
#   3. ingress-nginx (ALB/NLB stand-in) on host :80/:443
#   4. Argo CD (same GitOps engine as prod)
#
# Prereqs (script checks them):  docker, kind, kubectl, helm
# Ollama runs on your HOST (not in-cluster); see local/app/README.
# ============================================================================
set -euo pipefail

CLUSTER="anvilops"
REG_NAME="kind-registry"
REG_PORT="5001"
HERE="$(cd "$(dirname "$0")" && pwd)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "MISSING: $1 — install it first. See local/README.md"; exit 1; }; }
echo ">> Checking prerequisites..."
need docker; need kind; need kubectl; need helm
docker info >/dev/null 2>&1 || { echo "Docker isn't running. Start Docker Desktop and retry."; exit 1; }

# --- 1. local registry ------------------------------------------------------
if [ "$(docker inspect -f '{{.State.Running}}' "$REG_NAME" 2>/dev/null || true)" != "true" ]; then
  echo ">> Starting local registry on :$REG_PORT ..."
  docker run -d --restart=always -p "127.0.0.1:${REG_PORT}:5000" --name "$REG_NAME" registry:2
else
  echo ">> Registry already running."
fi

# --- 2. kind cluster --------------------------------------------------------
if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo ">> Creating kind cluster '$CLUSTER' ..."
  kind create cluster --config "$HERE/kind-config.yaml"
else
  echo ">> kind cluster '$CLUSTER' already exists — reusing it."
fi
kubectl cluster-info --context "kind-$CLUSTER" >/dev/null

# Detect whether the control-plane node has host port mappings (80/443).
# Without them, ingress can't reach the browser and we fall back to port-forward.
HAS_PORTS="no"
if docker inspect "${CLUSTER}-control-plane" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null | grep -q '"80/tcp"'; then
  HAS_PORTS="yes"
fi
echo ">> Host port mappings on control-plane: $HAS_PORTS"
if [ "$HAS_PORTS" = "no" ]; then
  echo "   (No 80/443 mapping — ingress hostnames won't reach your browser directly."
  echo "    Either recreate with the provided config, or use kubectl port-forward — see end of output.)"
fi

# connect registry to the kind network (safe to repeat)
docker network connect "kind" "$REG_NAME" 2>/dev/null || true
# tell the cluster the registry exists (documented kind pattern)
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:5001"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF

# --- 3. ingress-nginx (ALB/NLB stand-in) ------------------------------------
echo ">> Installing ingress-nginx ..."
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  -f "$HERE/gitops/platform/ingress-nginx-values.yaml" \
  --wait --timeout 5m

# --- 4. Argo CD -------------------------------------------------------------
echo ">> Installing Argo CD ..."
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --version "${ARGOCD_CHART_VERSION:-7.7.5}" \
  -f "$HERE/gitops/platform/argocd-values-local.yaml" \
  --wait --timeout 10m

echo
echo "============================================================"
echo " Local stack is up."
echo "------------------------------------------------------------"
echo " Argo CD admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
echo
if [ "$HAS_PORTS" = "yes" ]; then
  echo " Add a hosts entry so ingress names resolve locally:"
  echo "   (Windows) add to C:\\Windows\\System32\\drivers\\etc\\hosts:"
  echo "     127.0.0.1 argocd.local anvil-app.local"
  echo
  echo " Then open:  https://argocd.local   (accept the self-signed cert)"
else
  echo " Your cluster has NO host port mappings, so reach Argo CD via port-forward:"
  echo "   kubectl -n argocd port-forward svc/argocd-server 8080:80"
  echo "   open http://localhost:8080   (user: admin)"
  echo
  echo " To get real http://argocd.local / http://anvil-app.local URLs instead,"
  echo " recreate the cluster with the provided config (30s, nothing else lost):"
  echo "   kind delete cluster --name $CLUSTER"
  echo "   kind create cluster --config $HERE/kind-config.yaml"
  echo "   ./setup.sh"
fi
echo "------------------------------------------------------------"
echo " Next: start Ollama on your host, then build + deploy the demo app:"
echo "   ollama serve   (in its own terminal)"
echo "   ollama pull llama3.2"
echo "   ./app/build.sh"
echo "============================================================"
