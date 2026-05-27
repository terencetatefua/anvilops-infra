# anvilops-infra

A real, working **EKS-style platform** built locally on `kind`, with hardened
containers, Helm charts, and full GitOps via ArgoCD. The architecture mirrors
a production AWS deployment — the local stack uses free equivalents so the
move to AWS later is a config change, not a rewrite.

## What this repo contains

```
anvilops-infra/
├── local/              The local stack: kind cluster + ingress + ArgoCD + demo app
│   ├── README.md       In-depth walkthrough of the local stack
│   ├── kind-config.yaml
│   ├── setup.sh        One-shot installer
│   ├── app/            Demo workload (Python; AI backend pluggable)
│   │   └── README.md   App endpoints + how to call them
│   └── gitops/         Helm values used by setup.sh (platform components)
│
└── gitops/             The GitOps root — ArgoCD watches this folder
    ├── charts/
    │   └── anvil-app/  The demo app as a Helm chart
    ├── apps/           (reserved for per-environment values overrides)
    └── argocd/
        └── anvil-app-dev.yaml   ArgoCD Application resource
```

## What works end-to-end today

Editing a value in `gitops/charts/anvil-app/values.yaml`, committing, and
pushing causes the cluster to update itself — no `kubectl`, no `helm`, no
manual deploy commands. ArgoCD watches the repo, sees the change, and
reconciles the cluster.

That's the loop:

```
edit values.yaml → git push → ArgoCD detects → Helm renders → kubectl applies → cluster updated
```

Rollback is `git revert`. The cluster mirrors Git.

## The architecture (AWS ↔ local mapping)

| AWS production component | Local stand-in | Status |
|---|---|---|
| Amazon EKS | `kind` (Kubernetes in Docker) | ✅ Running |
| ALB / NLB | ingress-nginx | ✅ Routing `argocd.local` and `anvil-app.local` |
| Amazon ECR | Local `registry:2` container | ✅ Receiving image pushes |
| AWS Load Balancer Controller | Built into ingress-nginx | ✅ |
| Amazon Bedrock | Ollama (on host) | ✅ Via `AI_BACKEND=ollama` |
| ArgoCD | ArgoCD | ✅ Same on both — watches Git, syncs cluster |
| GitOps repo | This repo (`gitops/` tree) | ✅ ArgoCD synced to `main` |

What's intentionally *not* here (deferred to the AWS layer): IAM/IRSA, KMS,
CloudTrail, real TLS, VPC isolation, Aurora/DynamoDB/S3 data services. Those
come back as Terraform when this moves to AWS.

## Quick start

Prereqs: Docker Desktop (≥ 6 GB memory), `kind`, `kubectl`, `helm`, `ollama`.
Run all `.sh` from Git Bash, not PowerShell.

```bash
git clone https://github.com/terencetatefua/anvilops-infra.git
cd anvilops-infra/local

# 1. Bring up the cluster (3 nodes, port 80/443 mapped to host)
kind create cluster --name anvilops --config kind-config.yaml
kubectl label node anvilops-control-plane ingress-ready=true --overwrite

# 2. Install registry + ingress-nginx + ArgoCD
./setup.sh

# 3. Wire registry routing into the kind nodes (one-time)
#    See local/README.md §5.2 for the exact `containerd` config block.

# 4. Build + push the demo image
docker build -t localhost:5001/anvil-app:dev local/app
docker push localhost:5001/anvil-app:dev

# 5. Start Ollama on your host (separate terminal)
ollama serve
ollama pull llama3.2

# 6. Tell ArgoCD to deploy the chart from Git
kubectl apply -f gitops/argocd/anvil-app-dev.yaml

# 7. Add hosts entries:
#    127.0.0.1 argocd.local anvil-app.local
#    (Windows: C:\Windows\System32\drivers\etc\hosts, edit as administrator)
```

Then visit:

- `https://argocd.local` — ArgoCD UI (admin password: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`)
- `http://anvil-app.local/healthz` — demo app

## Walkthroughs

For the *why* behind each file, including the GitOps loop in detail:

- [`local/README.md`](local/README.md) — local stack walkthrough; what every file
  does, why it's there, and how it maps to the AWS equivalent
- [`local/app/README.md`](local/app/README.md) — the demo app's HTTP endpoints
  and how the AI backend swap works

## What this proves

This repo is a working demonstration of:

- **Multi-stage Docker images** with non-root numeric UIDs, read-only root
  filesystem, dropped capabilities, and `seccomp` defaults
- **Parameterized Helm charts** with conditional resources, backend-swap env
  injection, and proper standard labels (`app.kubernetes.io/*`)
- **GitOps via ArgoCD** with auto-sync, self-heal, and prune enabled
- **A cluster that is a reflection of Git** — reproducible from `kubectl apply -f gitops/argocd/`
