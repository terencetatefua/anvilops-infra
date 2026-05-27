# AnvilOps Local Stack — A Working Reference

> **Why this README exists.** Anyone can run `./setup.sh` and end up with a
> green cluster. This document is for understanding **what's actually
> happening and why each piece is there** — so you can explain every
> decision in your own words, to a teammate, an interviewer, or your future
> self looking at this code in six months.

---

## Table of contents

1. [The big idea](#1-the-big-idea)
2. [The architecture and its local twin](#2-the-architecture-and-its-local-twin)
3. [Folder layout, file by file](#3-folder-layout-file-by-file)
4. [How a request flows through the stack](#4-how-a-request-flows-through-the-stack)
5. [Section-by-section walkthrough](#5-section-by-section-walkthrough)
6. [What's NOT here (and where it lives in the AWS version)](#6-whats-not-here-and-where-it-lives-in-the-aws-version)
7. [The path from here to "enterprise GitOps"](#7-the-path-from-here-to-enterprise-gitops)
8. [Cheat sheet — commands you'll actually use](#8-cheat-sheet--commands-youll-actually-use)
9. [Glossary](#9-glossary)

---

## 1. The big idea

This project recreates the **AnvilOps AWS architecture** — the EKS / Bedrock
/ GitOps platform — using free, local equivalents instead of AWS services.
The structure is **identical**: same components in the same roles, same
traffic flow, same separation of concerns. Only the backends change.

Two reasons for doing it this way:

- **Practical:** running real EKS costs money. A `kind` cluster costs
  nothing.
- **Engineering:** if backends are swappable, the move to AWS isn't a
  rewrite — it's a configuration change. That's a property worth
  practicing, because it's exactly how production systems are built
  (dev → staging → prod, each with different backends but the same code).

If the architecture and the local stack feel like "the same thing, twice" —
that's the point. They are.

---

## 2. The architecture and its local twin

Every box in the AWS diagram has a local counterpart:

| AWS production component | Local stand-in | Why this works as a substitute |
|---|---|---|
| **Amazon EKS** (managed Kubernetes) | **`kind`** (Kubernetes in Docker) | Real K8s API; same `kubectl`, same manifests, same Helm charts. Differences are at the *infrastructure* level (managed control plane, auto-scaling), not the *Kubernetes* level. |
| **ALB / NLB** | **ingress-nginx** | Both route HTTP traffic to in-cluster services based on hostname/path. Identical `Ingress` resources work on both. |
| **Amazon ECR** | **local `registry:2` container** | Both speak the OCI registry protocol. `docker push` works identically. |
| **AWS Load Balancer Controller** | Built into ingress-nginx | The LB Controller's job is "watch `Ingress` resources, configure AWS LBs." Locally, ingress-nginx watches the same resources and configures itself. |
| **Amazon Bedrock** | **Ollama** (on your host) | Both speak HTTP. The app uses an abstraction layer (`AI_BACKEND` env var) so the call site is identical — only the URL changes. |
| **ArgoCD on EKS** | **ArgoCD on kind** | Not a stand-in — it's the *same component*. ArgoCD runs identically on either cluster. |
| **IAM / KMS / IRSA** | (nothing — local doesn't need cloud auth) | Comes back as Terraform on the AWS move. |
| **CloudTrail / CloudWatch / S3** | (nothing — out of scope for the pilot's spine) | Added later, on either side. |

That table is the most important table in this document. If you understand
it, you understand the whole project: **local and AWS are the same
architecture with different backends.**

---

## 3. Folder layout, file by file

```
local/
├── README.md                          ← you are here
├── kind-config.yaml                   ← the local cluster (EKS stand-in)
├── setup.sh                           ← bootstrap: registry + ingress + ArgoCD
├── app/                               ← the demo workload
│   ├── Dockerfile                     ← how the image is built
│   ├── .dockerignore                  ← what to keep OUT of the image
│   ├── requirements.txt               ← Python deps (empty locally)
│   ├── main.py                        ← the app code
│   └── build.sh                       ← build → push → deploy
└── gitops/                            ← K8s manifests (the "what to deploy")
    ├── platform/
    │   ├── ingress-nginx-values.yaml  ← Helm values for ingress-nginx
    │   └── argocd-values-local.yaml   ← Helm values for ArgoCD
    └── apps/
        └── anvil-app.yaml             ← K8s manifests for the demo app
```

Two folder names worth pausing on:

- **`gitops/`** — chosen deliberately. The eventual goal is that
  *everything in this folder lives in Git* and ArgoCD applies it
  automatically. Today `setup.sh` applies the platform pieces and
  `build.sh` applies the app piece. Tomorrow, ArgoCD does both.

- **`platform/` vs `apps/`** — a real-world distinction. *Platform*
  components (ingress, monitoring, the GitOps engine itself) are the
  foundation; they change rarely and only platform engineers touch them.
  *Apps* are workloads that change frequently and that product teams own.
  Mixing them in one folder works fine on day one and becomes painful on
  day fifty.

---

## 4. How a request flows through the stack

Following a single `POST /chat` request end-to-end is the fastest way to see
why every piece exists:

```
1. Browser hits  https://anvil-app.local/chat
              │
              ▼
2. C:\Windows\System32\drivers\etc\hosts  →  127.0.0.1
              │
              ▼
3. Docker Desktop port mapping  →  kind control-plane container, port 80
   (this is extraPortMappings in kind-config.yaml)
              │
              ▼
4. Inside the control-plane node  →  ingress-nginx pod is listening
   (it's there because we labeled that node ingress-ready=true)
              │
              ▼
5. ingress-nginx reads Host header (anvil-app.local), matches an Ingress
              │
              ▼
6. Routes to the anvil-app Service on port 80
              │
              ▼
7. Service load-balances to one of N anvil-app Pods, port 8000
              │
              ▼
8. Python app reads AI_BACKEND=ollama, calls host.docker.internal:11434
   (Ollama on your host machine)
              │
              ▼
9. Response travels back the same chain in reverse.
```

In AWS, the *same* nine steps happen — they just use Route 53, an ALB, the
AWS Load Balancer Controller, and Bedrock instead of `/etc/hosts`, port
mappings, ingress-nginx, and Ollama. The *shape* of the flow is identical.

---

## 5. Section-by-section walkthrough

### 5.1 The cluster — `kind-config.yaml`

**What it does.** Defines a 3-node Kubernetes cluster running inside Docker
containers: one control-plane (runs the K8s "brain": API server, scheduler,
etcd) and two workers (run your pods). Maps host ports 80 and 443 through
to the control-plane container.

**Why this shape.** Real EKS gives you a separate managed control plane
and worker node groups. Three nodes here mirrors that conceptually — one
control-plane-ish node and two worker-ish nodes — without paying for them.

**The port mapping is the load-bearing piece.** Without `extraPortMappings`,
port 80 on your laptop has no way to reach pods inside kind. You'd be
stuck running `kubectl port-forward` for everything. With it, traffic to
`localhost:80` is forwarded into the control-plane container, where
ingress-nginx is listening. This *single config option* is what lets you
visit `https://argocd.local` in a browser.

**About what we removed.** The original config had a `kubeadmConfigPatches`
block that labeled the control-plane `ingress-ready=true` automatically.
Kubernetes 1.35 didn't like the way `kind` formatted that patch, and the
kubelet refused to start. We took the patch out and added the label by
hand after cluster creation (`kubectl label node …`). Same result, no
crash. In production you'd use a kind release that supports your K8s
version cleanly — this is a local-only quirk.

### 5.2 The bootstrap — `setup.sh`

**What it does.** Idempotently installs the four things every other piece
depends on, in dependency order: local registry → registry-to-cluster
wiring → ingress-nginx → ArgoCD.

**Why a shell script and not Terraform.** Two reasons. First, this runs
*once per machine*, so a tool with a state file would be overkill.
Second, bootstrapping ArgoCD with anything *other than* a one-shot
command creates a chicken-and-egg problem (you can't use the GitOps
engine to install itself). On the AWS side, the equivalent is a small
Terraform module — same job, different idiom.

**Why each piece, in order:**

1. **Local registry (`docker run registry:2`).** ECR stand-in. The demo
   app needs somewhere to push its image to that kind can pull from.
   Without this, you'd be tied to public Docker Hub.

2. **`local-registry-hosting` ConfigMap.** Tells the cluster "there's a
   registry at `localhost:5001`." Documented kind convention — without
   it, kind nodes don't know how to resolve `localhost:5001` (inside a
   node, `localhost` means the node itself, not your laptop).

3. **ingress-nginx.** ALB stand-in. Installed via Helm with values from
   `gitops/platform/ingress-nginx-values.yaml`.

4. **ArgoCD.** The GitOps engine. Same install pattern.

**The detection worth understanding.** The script asks Docker whether the
control-plane container has port mappings. If yes, it tells you to use
hostnames; if no, it falls back to `kubectl port-forward`. This is
defensive — works correctly regardless of how the user created the
cluster.

### 5.3 The ingress — `gitops/platform/ingress-nginx-values.yaml`

This is one of two **Helm values files** in the project. A quick concept
check, since values files appear everywhere from here on:

> **What is a Helm chart?** A Helm chart is a templated bundle of
> Kubernetes manifests. Templates have placeholders
> (e.g. `replicas: {{ .Values.replicas }}`), and you supply the values in
> a YAML file. So you can deploy the *same* chart to dev, staging, and
> prod with different settings — only the values change. It's the
> Kubernetes-native answer to "config per environment."

**What this file does.** Overrides ingress-nginx's chart defaults so the
controller (a) runs on the node with our port mappings and (b) tolerates
being scheduled there even though it's the control-plane.

The five settings, decoded:

```yaml
controller:
  hostPort:
    enabled: true       # bind directly to the node's ports 80/443
  service:
    type: NodePort      # don't try to provision a cloud LoadBalancer
                        #   (there is none — we're local)
  nodeSelector:
    ingress-ready: "true"     # only run on the labeled node
  tolerations:
    - key: node-role.kubernetes.io/control-plane
      operator: Equal
      effect: NoSchedule      # accept the control-plane's "stay away" taint
  watchIngressWithoutClass: true  # be default for Ingress resources
                                  #   that don't specify ingressClassName
```

The **taint** point is worth knowing as a K8s concept: by default,
Kubernetes adds a taint to control-plane nodes that says "don't schedule
workloads here." Most workloads should respect that. ingress-nginx, in
our setup, *needs* to ignore it because the control-plane is the only
node with the host port mappings. That's what `tolerations` does — it's
not "ignore safety," it's "this specific pod has a reason to land
exactly there."

**In AWS land**, none of these settings exist. You'd install the AWS Load
Balancer Controller instead, which provisions a real ALB per Ingress and
doesn't care about node pinning.

### 5.4 The GitOps engine — `gitops/platform/argocd-values-local.yaml`

**What it does.** Configures the ArgoCD Helm chart for local use:
single-replica everything, no SSO, exposed via ingress at
`https://argocd.local`.

**The key concept: GitOps.** ArgoCD's whole job is to make this true:

> The state of the cluster equals the state of a Git repository.

You commit a manifest to Git → ArgoCD notices → ArgoCD applies it. If
someone runs `kubectl delete` directly on the cluster, ArgoCD notices
*that* too and puts it back (**self-healing**). The cluster becomes a
*reflection* of Git, not an independent source of truth.

This matters in production because it means the cluster is **auditable**
(Git history = deployment history), **reproducible** (any cluster applied
to the same repo produces the same state), and **rollback is `git
revert`**.

We're not using the self-heal / Git-sync features *yet* — we're running
ArgoCD as a UI for now. Section 7 is where we wire up the actual GitOps
loop.

**One subtle gotcha worth noting.** The values file defines `server:`
once (with both `replicas` and `ingress` nested under it). YAML silently
allows duplicate top-level keys but keeps only the last one — an earlier
draft of this file had `server:` listed twice, which would have silently
dropped our ingress config. The lesson: trust your editor's "duplicate
key" warnings.

### 5.5 The application image — `app/`

Five files, each doing one job.

#### `app/main.py` — the application logic

A minimal Python HTTP server, three endpoints:

- `GET /` — sanity check
- `GET /healthz` — used by Kubernetes for liveness/readiness probes and
  by Docker for `HEALTHCHECK`
- `POST /chat` — calls the configured AI backend

**The thing to notice.** The function `ask(prompt)` checks `AI_BACKEND`
and dispatches to either `ask_ollama` or `ask_bedrock`. Both functions
have the same signature: take a string, return a string. The rest of the
app doesn't know or care which is in use.

This is the **swap point**. Today, `AI_BACKEND=ollama`. On AWS,
`AI_BACKEND=bedrock` in the Deployment — *nothing else in the code
changes*. That's what we mean by "same architecture, different backends."

#### `app/requirements.txt` — Python dependencies

Currently effectively empty (`boto3` commented out for local; uncomment
on AWS). It exists as its own file even when empty for a reason — see
the Dockerfile next.

#### `app/Dockerfile` — how the image is built

Several production patterns at once. Walking through it:

```dockerfile
FROM python:3.12.8-slim AS builder
```
**Two things.** `python:3.12.8-slim` (not `:latest`) — pinning the tag
means the build is reproducible; if Python releases 3.12.9 tomorrow your
image doesn't silently change. `AS builder` names this stage so the next
one can copy from it.

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
```
**Copy `requirements.txt` first, *before* the app code.** Caching trick:
Docker builds in layers; layers are cached based on their inputs. If the
app code changes but `requirements.txt` doesn't, Docker reuses the
cached "install dependencies" layer and skips the slow `pip install`.
This is why even empty `requirements.txt` files matter — the *layer
structure* does.

`--no-cache-dir` tells pip not to keep its download cache in the image
(smaller image). `--prefix=/install` puts everything in one directory
so the next stage can copy just that.

```dockerfile
FROM python:3.12.8-slim AS runtime
```
**Multi-stage, stage 2.** Start a fresh, minimal image — none of the
build tooling carries over. The final image only contains what we
explicitly copy in.

```dockerfile
RUN groupadd --system app && useradd --system --gid app --no-create-home app
```
**Create an unprivileged user.** Default user in a container is root.
If an attacker exploits an app vulnerability, they're root inside the
container. Dedicated low-privilege user → defense in depth.

```dockerfile
COPY --from=builder /install /usr/local
COPY --chown=app:app main.py .
USER app
```
**Bring in deps from builder, copy code last, drop privileges.** `--chown`
ensures the app user owns its own files. `USER app` is what makes the
previous step actually meaningful.

```dockerfile
HEALTHCHECK ... CMD python -c "..."
```
**Container-level health probe.** Independent of Kubernetes — even
`docker ps` shows "healthy" or "unhealthy." Uses only the standard
library so no extra packages needed.

```dockerfile
CMD ["python", "main.py"]
```
**Exec form, not shell form.** Written this way, `python` is PID 1 in
the container — it receives signals (`SIGTERM`) directly. Shell form
(`CMD python main.py`) wraps it in a shell that often swallows signals
and breaks graceful shutdown.

#### `app/.dockerignore` — what *not* to put in the build context

Mirrors `.gitignore`, but for `docker build`. Anything listed here is
not sent to the Docker daemon. Keeps builds fast (no shipping `.git/`)
and prevents accidental secret leaks (e.g. a stray `.env`).

#### `app/build.sh` — the build pipeline, locally

Three steps: build → push to local registry → apply K8s manifests. In
production, **these three are normally separate systems**: a CI runner
does build/push (GitLab in the AWS diagram); ArgoCD does the apply. We
have them in one script for now because we're still doing the manual
loop. Once we wire up real GitOps in section 7, this script becomes
"build + push" only — ArgoCD takes over deploy.

### 5.6 The application manifest — `gitops/apps/anvil-app.yaml`

Three Kubernetes resources, separated by `---`. Reading them in the
order traffic hits them is easiest.

#### `Ingress` (the rule)

```yaml
host: anvil-app.local
backend: service anvil-app, port 80
```
"When ingress-nginx sees traffic with `Host: anvil-app.local`, send it
to the `anvil-app` Service on port 80." This resource is the *intent*;
the ingress controller is what *enforces* it.

#### `Service` (the address)

A Service is a stable virtual IP + DNS name for a set of pods. Pods come
and go (scaling, restarts, rescheduling); the Service stays put.
`selector: app: anvil-app` means "any pod with that label is fair game."

The Service listens on port 80 and forwards to the pod's port 8000. The
gap (80 → 8000) is intentional — external port doesn't have to match
internal port.

#### `Deployment` (the workload)

A Deployment manages a set of identical pods. `replicas: 2` says "keep
two running at all times." If one dies, K8s replaces it. If the cluster
reboots, the Deployment restores both.

The notable part of this Deployment is the **`securityContext`** — it
enforces, at the cluster level, the same posture the Dockerfile sets up:

```yaml
securityContext:                # pod-level
  runAsNonRoot: true            # refuse to start if image runs as root
  seccompProfile:               # apply default syscall whitelist
    type: RuntimeDefault
```

And on the container:

```yaml
allowPrivilegeEscalation: false # process can't gain new privileges
readOnlyRootFilesystem: true    # filesystem is read-only at runtime
capabilities: { drop: ["ALL"] } # no Linux capabilities at all
```

These belong here (not just in the Dockerfile) because **the cluster
should enforce its own security posture**. A compromised image lying
about its user can't bypass `runAsNonRoot: true` — Kubernetes won't even
start it. "Trust nothing" in practice.

The `env` block is where the **backend swap** actually lives in the
running system. Today: `AI_BACKEND=ollama`. On AWS: change two lines,
no rebuild.

---

## 6. What's NOT here (and where it lives in the AWS version)

The local stack faithfully copies the **runtime architecture**. Several
layers from the AWS diagram are deliberately absent:

| Missing locally | Why | Lives in AWS as |
|---|---|---|
| Network isolation (VPCs, subnets, AZs) | kind is one Docker network | Terraform `modules/vpc/` |
| Identity & secrets (IAM, IRSA, KMS) | No cloud calls = no auth needed | Terraform IAM + IRSA roles |
| Observability (Prometheus, Grafana, Loki, CloudTrail) | Not the spine — we prove the path first | Helm charts via ArgoCD + AWS managed services |
| Data services (Aurora, S3, DynamoDB, MSK, FSx) | Heavy + each needs its own design | Terraform per service + K8s operators |
| Real TLS certs (not self-signed) | Self-signed is fine for `*.local` | cert-manager + ACM |
| CI (the build half of CI/CD) | We build manually for now | GitLab pipelines |

Don't read this table as "incomplete" — read it as **scope discipline**.
Build the spine first, prove it, then add layers. Adding everything at
once is how projects fail.

---

## 7. The path from here to "enterprise GitOps"

Right now, ArgoCD is *installed* but we're not *using* it as a deployment
engine. We're using it as a pretty dashboard. The work of deploying
still happens through `./app/build.sh`. The real GitOps loop closes
when:

1. **The app becomes a Helm chart**, not a folder of raw YAML. Helm
   charts give us templating (`{{ .Values.image.tag }}`), versioning,
   and a standard install/upgrade/rollback story.

2. **The Helm chart and platform configs live in a Git repo.** Right now
   they live on your laptop. Git is the source of truth in real GitOps.

3. **ArgoCD `Application` resources point at the Git repo**, telling
   ArgoCD what to watch and where to deploy it.

4. **Sync is automatic.** A push to Git → ArgoCD detects the change →
   it applies. No human in the deploy loop.

5. **The `Application` resources themselves are managed by ArgoCD**
   (the **"app-of-apps"** pattern). One root Application creates all
   the others. You bootstrap the root by hand once; from then on,
   adding a new app means committing a new `Application` YAML to Git.

We'll work through these in order, one step at a time. Each step is
useful on its own and survives the next one being added later.

---

## 8. Cheat sheet — commands you'll actually use

```bash
# Cluster health
kubectl get nodes
kubectl get pods -A                            # all namespaces

# Drilling into a pod
kubectl describe pod -n <ns> <pod-name>
kubectl logs -n <ns> <pod-name>
kubectl logs -n <ns> -l app=anvil-app --tail=50   # by label

# Reaching things when ingress is broken
kubectl port-forward -n argocd svc/argocd-server 8080:80
kubectl port-forward -n anvil  svc/anvil-app    8000:80

# Rebuild + redeploy the app
./app/build.sh

# Recover the ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d

# Look at what's deployed where
kubectl get all -n anvil
kubectl get ingress -A

# Tear down (start over)
kind delete cluster --name anvilops
docker rm -f kind-registry
```

---

## 9. Glossary

- **Pod** — smallest deployable unit in K8s; one or more containers
  sharing a network namespace.
- **Deployment** — controller maintaining N replicas of a pod template.
- **Service** — stable network address (and DNS name) for a set of pods.
- **Ingress** — rule for routing external HTTP(S) traffic to a Service.
- **Ingress controller** — the thing (e.g. ingress-nginx) that actually
  *enforces* Ingress rules. An Ingress resource without a controller is
  just text.
- **Helm chart** — templated bundle of Kubernetes manifests.
- **Helm values file** — inputs to a chart's templates.
- **Namespace** — logical partition in a cluster; same name allowed in
  different namespaces.
- **Taint / Toleration** — a node's "stay away" sign, and a pod's permit
  to ignore it.
- **GitOps** — using a Git repo as the single source of truth for what a
  cluster runs.
- **IRSA** (IAM Roles for Service Accounts) — AWS-specific; gives pods
  AWS credentials without storing them in the cluster. Doesn't apply
  locally.
