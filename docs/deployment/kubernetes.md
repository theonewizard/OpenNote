# Kubernetes and OpenShift

OpenNote ships a Helm chart (`infrastructure/helm/opennote`), a kustomize base (`infrastructure/kubernetes/base`) and an OpenShift overlay of that base (`infrastructure/openshift`). They deploy the API, the background worker and the web app.

**Status.** CI lints the chart, renders every variant and validates the output against the Kubernetes schemas (the `manifests` job), and deploys the chart and the OpenShift overlay to throwaway kind clusters at Kubernetes 1.29 and 1.37 in a namespace that enforces Pod Security `restricted`, with what OpenShift's `restricted-v2` SCC does to a pod simulated (the `deploy` job, see [Deployment test](#deployment-test)). Neither has run on a real OpenShift cluster yet: the Route and real SCC admission are unverified. **No images are published yet:** build them from `infrastructure/containers` and push them to a registry your cluster can pull from (see [Images](#images)).

## What is deployed

| Object | Helm name (release `opennote`) | kustomize name | Notes |
|---|---|---|---|
| Deployment | `opennote-api` | `api` | uvicorn on port 8000. Startup and liveness probes on `/healthz`, readiness on `/readyz` (database, Valkey and both volumes) |
| Deployment | `opennote-worker` | `worker` | The api image with `python -m app.workers`. No probes in Phase 0 (no HTTP endpoint). 60 s grace period: on SIGTERM the worker waits up to 50 s for running jobs; a job still running after that is delivered again |
| Deployment | `opennote-watcher` | `watcher` | The api image with `python -m app.vaults`: watches every vault, imports the notes already in a registered folder and commits edits made outside OpenNote. Always one replica, `Recreate` strategy (a second copy would wait on a PostgreSQL advisory lock). No probes (no HTTP endpoint). On a volume that delivers no inotify events (NFS and most RWX types) external edits are found by the full rescan every 15 minutes |
| Deployment | `opennote-web` | `web` | nginx on port 8080, probes on `/`. Serves the web app and forwards `/api/`, `/healthz` and `/readyz` to the api Service |
| Service | `opennote-api`, `opennote-web` | `api`, `web` | Port 80 to the containers' `http` port |
| PersistentVolumeClaim | `opennote-vaults`, `opennote-history` | `vaults`, `history` | `ReadWriteMany`, 10 GiB each by default; mounted by api, worker and watcher at `/var/lib/opennote/vaults` and `/var/lib/opennote/history`. The chart keeps them on `helm uninstall` |
| ConfigMap | `opennote`, `opennote-web` | `opennote`, `web` | The non-secret settings: `OPENNOTE_ENVIRONMENT=production`, `OPENNOTE_LOG_LEVEL`, the two volume paths, `OPENNOTE_MIGRATE_ON_START=false`; for web, `OPENNOTE_API_UPSTREAM` |
| Job | `opennote-migrate` | `migrate` | `alembic upgrade head`, reading only the database URL from the Secret. In the chart it is a `pre-install,pre-upgrade` hook |
| ServiceAccount | `opennote` | (the namespace's `default`) | No API token is mounted into any pod |
| Ingress | `opennote` (off by default) | — | To web |
| Route | `opennote-web` (with `openshift.enabled=true`) | `web` (overlay) | Edge TLS to web, HTTP redirected to HTTPS |

PostgreSQL and Valkey are not part of these manifests: point OpenNote at a PostgreSQL server with the pgvector extension available and at a Valkey (or Redis-protocol) server. The migration runs `CREATE EXTENSION IF NOT EXISTS vector` and `pg_trgm`, so the database role must be allowed to create them, or an administrator creates them first.

## Before you install

1. **Kubernetes 1.29 or newer (OpenShift 4.16 or newer).** The chart declares `kubeVersion: ">=1.29.0-0"` and Helm refuses older clusters.
2. **A `ReadWriteMany` storage class** (for example NFS, CephFS, Azure Files or EFS), the cluster default or named with `persistence.storageClassName`. The api and the worker mount both volumes at the same time, possibly on different nodes. The images run as UID 1001 in group 0; on Kubernetes every pod sets `fsGroup: 1001`, so the volumes are group-writable for it. Every pod also sets `fsGroupChangePolicy: OnRootMismatch`, so the kubelet changes the group of a volume's files only when the volume's root does not already have it, instead of at every start of a pod with a large vault. A storage driver that ignores `fsGroup` (some NFS drivers) needs the export writable by that UID or group instead. The vault volume should also support `renameat2` with `RENAME_EXCHANGE` (local filesystems such as ext4, XFS and Btrfs do; NFS and some other RWX types do not): OpenNote swaps a saved note into place in one step and checks what it displaced, so an external save racing the write is never lost. Without it, the api logs `vault filesystem lacks RENAME_EXCHANGE` once and falls back to check-then-rename, which leaves a short window in which such a racing external save can be overwritten (storage contract §4).
3. **A namespace that enforces the Pod Security `restricted` profile**, which the manifests are written for: non-root, no privilege escalation, all capabilities dropped, `RuntimeDefault` seccomp. Beyond that profile, every container has a read-only root filesystem with an `emptyDir` at `/tmp`, and no pod sets `runAsUser`:

   ```bash
   kubectl create namespace opennote
   kubectl label namespace opennote pod-security.kubernetes.io/enforce=restricted
   ```

4. **The Secret `opennote`** with the two connection URLs. The manifests reference it and never contain a secret value:

   ```bash
   kubectl -n opennote create secret generic opennote \
     --from-literal=OPENNOTE_DATABASE_URL=<database-url> \
     --from-literal=OPENNOTE_VALKEY_URL=<valkey-url>
   ```

   `<database-url>` has the form `postgresql+psycopg://<user>:<password>@<host>:5432/<database>`, and `<valkey-url>` the form `redis://<host>:6379/0`; put a URL that contains shell metacharacters such as `$`, `&` or `!` in single quotes (`--from-literal='OPENNOTE_DATABASE_URL=<database-url>'`). `--from-literal` leaves the values in your shell history; `--from-file=OPENNOTE_DATABASE_URL=<file>` reads one from a file instead. Another Secret name is set with `existingSecret` (chart only). The api and worker pods mount the Secret read-only as files under `/run/secrets/opennote` and read them through `OPENNOTE_DATABASE_URL_FILE` and `OPENNOTE_VALKEY_URL_FILE` (the migration Job mounts only the `OPENNOTE_DATABASE_URL` key and reads only the first), the `*_FILE` convention described in `infrastructure/compose/.env.example`, so the URLs never appear in a process's environment.

### Images

From the repository root:

```bash
docker build -f infrastructure/containers/api/Containerfile -t <registry>/opennote-api:0.1.0 .
docker build -f infrastructure/containers/web/Containerfile -t <registry>/opennote-web:0.1.0 .
docker push <registry>/opennote-api:0.1.0
docker push <registry>/opennote-web:0.1.0
```

The defaults name `ghcr.io/theonewizard/opennote-api` and `ghcr.io/theonewizard/opennote-web` with the tag `0.1.0`, the chart's `appVersion` and the version string, which the tag in the commands above follows; those images do not exist yet. A private registry needs a pull secret: `imagePullSecrets` in the chart.

## Install with Helm

```bash
helm install opennote infrastructure/helm/opennote --namespace opennote \
  --set image.apiRepository=<registry>/opennote-api \
  --set image.webRepository=<registry>/opennote-web
```

Helm runs the migration Job first and creates the other objects only after it succeeds; `helm upgrade` does the same. The last Job is kept until the next upgrade, so its logs stay readable (`kubectl -n opennote logs job/opennote-migrate`); `helm uninstall` leaves it, and the two volumes, in place. Without an Ingress or Route, reach the web app with `kubectl -n opennote port-forward service/opennote-web 8080:80` and http://127.0.0.1:8080.

The values (`infrastructure/helm/opennote/values.yaml` describes each one; `values.schema.json` beside it makes Helm refuse an unknown value or one of the wrong type):

| Value | Default | |
|---|---|---|
| `image.apiRepository`, `image.webRepository`, `image.tag`, `image.pullPolicy` | `ghcr.io/theonewizard/opennote-api`, `…/opennote-web`, the chart's `appVersion`, `IfNotPresent` | |
| `imagePullSecrets` | `[]` | |
| `existingSecret` | `opennote` | Keys `OPENNOTE_DATABASE_URL`, `OPENNOTE_VALKEY_URL` |
| `logLevel` | `INFO` | `OPENNOTE_LOG_LEVEL`, one of CRITICAL, ERROR, WARNING, INFO, DEBUG; `OPENNOTE_ENVIRONMENT` is always `production` |
| `clusterDomain` | `cluster.local` | Used for web's `OPENNOTE_API_UPSTREAM`, `<fullname>-api.<namespace>.svc.<clusterDomain>:80`, where `<fullname>` is the release name if it contains `opennote`, else `<release>-opennote`. nginx's resolver ignores the resolv.conf search list, so the name must be fully qualified |
| `fsGroup` | `1001` | Left out when `openshift.enabled` is true. `fsGroupChangePolicy: OnRootMismatch` is not a value: every pod sets it, on OpenShift too |
| `openshift.enabled`, `openshift.route.host`, `openshift.route.annotations` | `false`, empty (the router generates a host), `{}` | Annotations go on the Route, see [OpenShift](#openshift) |
| `networkPolicy.enabled` | `false` | Only web may connect to the API, nothing to the worker, see [Network policy](#network-policy) |
| `ingress.enabled`, `ingress.className`, `ingress.annotations`, `ingress.host`, `ingress.tlsSecretName` | `false`, empty, `{}`, empty (any host), empty (no TLS) | |
| `persistence.accessMode`, `persistence.storageClassName`, `persistence.vaults.size`, `persistence.history.size` | `ReadWriteMany`, empty (the default class), `10Gi`, `10Gi` | |
| `api.replicas`, `worker.replicas`, `web.replicas` | `1` | |
| `api.resources`, `worker.resources` | requests 250m CPU and 256Mi, limits 1 CPU and 512Mi | The migration Job uses `api.resources` |
| `watcher.resources` | requests 100m CPU and 256Mi, limits 1 CPU and 512Mi | The watcher always runs one replica, so it has no `replicas` value |
| `web.resources` | requests 50m and 64Mi, limits 250m and 128Mi | |

An Ingress, for an ingress controller you already run:

```bash
helm upgrade opennote infrastructure/helm/opennote --namespace opennote --reuse-values \
  --set ingress.enabled=true --set ingress.className=<class> --set ingress.host=<host> \
  --set ingress.tlsSecretName=<tls-secret>
```

Without `ingress.tlsSecretName` the Ingress serves plain HTTP: set it, or terminate TLS at the ingress controller, before exposing OpenNote.

### Network policy

With `networkPolicy.enabled=true` the chart adds two NetworkPolicies: the API accepts connections only from the release's web pods (web proxies `/api/`, `/healthz` and `/readyz` to it), and the worker, which listens on no port, accepts none. web stays reachable for the router or ingress controller, whose namespace differs from cluster to cluster. Egress is not restricted, because PostgreSQL and Valkey are external and their addresses are yours; add an egress policy for them if your cluster requires one. The policies need a network plugin that enforces NetworkPolicy (OpenShift's OVN-Kubernetes does; the `deploy` CI job checks them on kind). Turn them on in production.

## Apply with kustomize

```bash
kubectl apply -k infrastructure/kubernetes/base
```

The base deploys into the namespace `opennote` and uses the default image names; change them in an overlay (`images:`). Another namespace must also change `OPENNOTE_API_UPSTREAM` in the `web` ConfigMap (`api.opennote.svc.cluster.local:80` in the base), for the reason given for `clusterDomain` above. Unlike the chart, the base:

- **does not keep the volumes:** `kubectl delete -k` deletes the `vaults` and `history` PersistentVolumeClaims too (there is no `helm.sh/resource-policy: keep`), and with a `Delete` reclaim policy the data on them;
- **does not restart the pods after a ConfigMap change** (there is no checksum annotation): run `kubectl -n opennote rollout restart deployment` after changing one;
- **has no ordering:** the migration Job runs alongside the Deployments. A Job's pod template cannot change, so delete the Job before applying a new image: `kubectl -n opennote delete job migrate --ignore-not-found`.

## OpenShift

Either install the chart with `--set openshift.enabled=true`, or apply the overlay:

```bash
oc apply -k infrastructure/openshift
```

Both differ from plain Kubernetes in two ways:

- **No `fsGroup`.** The `restricted-v2` SCC assigns each pod a UID and an `fsGroup` from the namespace's ranges and refuses a fixed `fsGroup` outside them. The images run with any UID in group 0, and the volumes get the SCC's group. The pods leave out only `fsGroup` and keep `fsGroupChangePolicy: OnRootMismatch`.
- **A Route to web** with edge TLS (the router's default certificate) and HTTP redirected to HTTPS: `oc -n opennote get route`. With the chart, `openshift.route.host` sets a host name and `openshift.route.annotations` adds router annotations.

The cluster must run Kubernetes 1.29 or newer (OpenShift 4.16 or newer), the chart's `kubeVersion`.

### Production on OpenShift

What the chart expects, and what to set, for a namespace that holds real vaults (`CLAUDE.md` §11 treats it as production):

1. **No extra SCC.** Every pod runs under the default `restricted-v2` SCC: no `anyuid`, no privileged container, no host path. Do not grant the service account another SCC.
2. **ReadWriteMany storage** for the two volumes (OpenShift Data Foundation's CephFS, or NFS). On NFS and some other RWX filesystems the vault writes fall back from `renameat2(RENAME_EXCHANGE)` to check-then-rename and log a warning once ([IMPLEMENTATION_STATUS.md, Known limits](../IMPLEMENTATION_STATUS.md#known-limits)).
3. **The network policy on:** `--set networkPolicy.enabled=true`.
4. **HSTS and timeouts on the Route**, for example:

   ```bash
   helm upgrade opennote infrastructure/helm/opennote --namespace opennote --reuse-values \
     --set-string 'openshift.route.annotations.haproxy\.router\.openshift\.io/hsts_header=max-age=31536000' \
     --set-string 'openshift.route.annotations.haproxy\.router\.openshift\.io/timeout=60s'
   ```

   The Route uses the router's default certificate. A host name outside the cluster's apps domain needs a certificate for it: on the router (the cluster's ingress controller) or, if your cluster's policy prefers it, a Route you create yourself instead of the chart's (`openshift.enabled` keeps `fsGroup` out either way; the Route is the only object it adds).
5. **Backups** of the database, the history volume and the vault volume together (roadmap item P8-04).

## Deployment test

`scripts/kind-deploy-test.sh` deploys to the cluster of the current `kubectl` context and checks the result; the `deploy` job runs it on kind at Kubernetes 1.29.14 (the chart's floor, OpenShift 4.16) and 1.37.0. It creates the namespaces `opennote-test` and `opennote`, refuses a cluster that already has either, and deletes them afterwards. In each namespace Pod Security `restricted` is enforced and a pod without a security context is first checked to be refused. PostgreSQL and Valkey run there as test fixtures from the repository's images.

1. **Helm chart**, Kubernetes variant, network policy on, RWO volumes (kind's local-path provisioner has no RWX): a server-side dry run of every template, migration hook included, must draw no PodSecurity warning; `helm install --wait` must bring every pod up after the migration Job succeeded; the smoke test passes through web; the worker never restarts; a pod labelled as web reaches the API and any other pod does not; `helm upgrade` runs a new migration Job and rolls the pods; `helm uninstall` leaves both volumes.
2. **OpenShift overlay**, with what `restricted-v2` adds to every pod (`runAsUser` and `fsGroup` 1000870000 from a typical namespace range) and without the Route: no PodSecurity warning, the migration Job completes, all three Deployments roll out, the api runs as UID 1000870000, the smoke test passes.

Locally, with Docker, kind 0.33.0 and Helm 4.3.1:

```bash
docker compose -f infrastructure/compose/compose.yaml build
kind create cluster --name opennote --image kindest/node:v1.37.0
kind load docker-image --name opennote opennote-api:dev opennote-web:dev opennote-postgres:dev opennote-valkey:dev
scripts/kind-deploy-test.sh
kind delete cluster --name opennote
```

What it does not show: the OpenShift router and Route, real SCC admission (the UID and group come from a patch, not from the SCC), RWX storage across nodes, and a multi-node cluster.

## Validation

The `manifests` job of `.github/workflows/containers.yml` runs whenever that workflow does (docs/development/setup.md, "Continuous integration"):

- `helm lint --strict --kube-version 1.29.0` for the defaults, `openshift.enabled=true`, and an Ingress with a host and TLS plus the network policy, and a `helm template --kube-version 1.28.9` that must fail (the chart's `kubeVersion` floor);
- `helm template --kube-version 1.29.0` of the same three variants, and `kubectl kustomize` of the base and the OpenShift overlay;
- a check of what kubeconform cannot see: no render contains a Secret, `secretKeyRef` or `secretRef`; the four pods set `fsGroup: 1001` on Kubernetes and none does on OpenShift, and all four set `fsGroupChangePolicy: OnRootMismatch` and `readOnlyRootFilesystem: true` (on their containers) in every render; `automountServiceAccountToken: false` appears twice in each chart render (the ServiceAccount and the migration Job) and on all four pods in each kustomize render; web's `OPENNOTE_API_UPSTREAM` is the api Service's fully qualified name on port 80;
- `kubeconform -strict` of all five renders against the Kubernetes 1.29.0 schemas and the newest ones, with the Route schema from the community CRD catalog (`datreeio/CRDs-catalog`, OpenShift 4.15).

The same locally, with Helm 4.3.1, kustomize and kubeconform installed (Helm 3 needs `--kube-version` too: without it Helm 3 renders for Kubernetes 1.20, which the chart refuses):

```bash
set -o pipefail   # a failed render fails the line, not only kubeconform
helm lint --strict infrastructure/helm/opennote --kube-version 1.29.0
helm lint --strict infrastructure/helm/opennote --kube-version 1.29.0 --set openshift.enabled=true
route='https://raw.githubusercontent.com/datreeio/CRDs-catalog/501527ab9c40c827144c8f45945b25a023e344ce/openshift/v4.15-strict/{{.ResourceKind}}_{{.Group}}_{{.ResourceAPIVersion}}.json'
helm template opennote infrastructure/helm/opennote --kube-version 1.29.0 | kubeconform -strict -summary -kubernetes-version 1.29.0
helm template opennote infrastructure/helm/opennote --kube-version 1.29.0 --set openshift.enabled=true |
  kubeconform -strict -summary -kubernetes-version 1.29.0 -schema-location default -schema-location "$route"
kustomize build infrastructure/kubernetes/base | kubeconform -strict -summary -kubernetes-version 1.29.0
kustomize build infrastructure/openshift |
  kubeconform -strict -summary -kubernetes-version 1.29.0 -schema-location default -schema-location "$route"
```

The job also lints and renders the Ingress variant, checks that the 1.28.9 render fails, runs the check of the third item on the saved renders, and repeats kubeconform with `-kubernetes-version master`.

The Pod Security `restricted` profile is checked by the `deploy` job ([Deployment test](#deployment-test)): its namespaces enforce the profile and its server-side dry run fails on any PodSecurity warning.
