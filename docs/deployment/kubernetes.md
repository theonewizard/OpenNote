# Kubernetes and OpenShift

OpenNote ships a Helm chart (`infrastructure/helm/opennote`), a kustomize base (`infrastructure/kubernetes/base`) and an OpenShift overlay of that base (`infrastructure/openshift`). They deploy the API, the background worker and the web app.

**Status (Phase 0).** These are skeletons. CI lints the chart, renders every variant and validates the output against the Kubernetes schemas (the `manifests` job, see [Validation](#validation)), but the manifests have not been applied to a cluster yet. **No images are published yet:** build them from `infrastructure/containers` and push them to a registry your cluster can pull from (see [Images](#images)).

## What is deployed

| Object | Helm name (release `opennote`) | kustomize name | Notes |
|---|---|---|---|
| Deployment | `opennote-api` | `api` | uvicorn on port 8000. Startup and liveness probes on `/healthz`, readiness on `/readyz` (database, Valkey and both volumes) |
| Deployment | `opennote-worker` | `worker` | The api image with `python -m app.workers`. No probes in Phase 0 (no HTTP endpoint). 60 s grace period: on SIGTERM the worker waits up to 50 s for running jobs; a job still running after that is delivered again |
| Deployment | `opennote-web` | `web` | nginx on port 8080, probes on `/`. Serves the web app and forwards `/api/`, `/healthz` and `/readyz` to the api Service |
| Service | `opennote-api`, `opennote-web` | `api`, `web` | Port 80 to the containers' `http` port |
| PersistentVolumeClaim | `opennote-vaults`, `opennote-history` | `vaults`, `history` | `ReadWriteMany`, 10 GiB each by default; mounted by api and worker at `/var/lib/opennote/vaults` and `/var/lib/opennote/history`. The chart keeps them on `helm uninstall` |
| ConfigMap | `opennote`, `opennote-web` | `opennote`, `web` | The non-secret settings: `OPENNOTE_ENVIRONMENT=production`, `OPENNOTE_LOG_LEVEL`, the two volume paths, `OPENNOTE_MIGRATE_ON_START=false`; for web, `OPENNOTE_API_UPSTREAM` |
| Job | `opennote-migrate` | `migrate` | `alembic upgrade head` with only `OPENNOTE_DATABASE_URL`. In the chart it is a `pre-install,pre-upgrade` hook |
| ServiceAccount | `opennote` | (the namespace's `default`) | No API token is mounted into any pod |
| Ingress | `opennote` (off by default) | — | To web |
| Route | `opennote-web` (with `openshift.enabled=true`) | `web` (overlay) | Edge TLS to web, HTTP redirected to HTTPS |

PostgreSQL and Valkey are not part of these manifests: point OpenNote at a PostgreSQL server with the pgvector extension available and at a Valkey (or Redis-protocol) server. The migration runs `CREATE EXTENSION IF NOT EXISTS vector` and `pg_trgm`, so the database role must be allowed to create them, or an administrator creates them first.

## Before you install

1. **Kubernetes 1.30 or newer.** The chart declares `kubeVersion: ">=1.30.0-0"` and Helm refuses older clusters.
2. **A `ReadWriteMany` storage class** (for example NFS, CephFS, Azure Files or EFS), the cluster default or named with `persistence.storageClassName`. The api and the worker mount both volumes at the same time, possibly on different nodes. The images run as UID 1001 in group 0; on Kubernetes every pod sets `fsGroup: 1001`, so the volumes are group-writable for it. A storage driver that ignores `fsGroup` (some NFS drivers) needs the export writable by that UID or group instead.
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

   `<database-url>` has the form `postgresql+psycopg://<user>:<password>@<host>:5432/<database>`, and `<valkey-url>` the form `redis://<host>:6379/0`. `--from-literal` leaves the values in your shell history; `--from-file=OPENNOTE_DATABASE_URL=<file>` reads one from a file instead. Another Secret name is set with `existingSecret` (chart only).

### Images

From the repository root:

```bash
docker build -f infrastructure/containers/api/Containerfile -t <registry>/opennote-api:0.1.0 .
docker build -f infrastructure/containers/web/Containerfile -t <registry>/opennote-web:0.1.0 .
docker push <registry>/opennote-api:0.1.0
docker push <registry>/opennote-web:0.1.0
```

The defaults name `ghcr.io/theonewizard/opennote-api` and `ghcr.io/theonewizard/opennote-web` with the tag `0.1.0` (the chart's `appVersion`); those images do not exist yet. A private registry needs a pull secret: `imagePullSecrets` in the chart.

## Install with Helm

```bash
helm install opennote infrastructure/helm/opennote --namespace opennote \
  --set image.apiRepository=<registry>/opennote-api \
  --set image.webRepository=<registry>/opennote-web
```

Helm runs the migration Job first and creates the other objects only after it succeeds; `helm upgrade` does the same. The last Job is kept until the next upgrade, so its logs stay readable (`kubectl -n opennote logs job/opennote-migrate`); `helm uninstall` leaves it, and the two volumes, in place. Without an Ingress or Route, reach the web app with `kubectl -n opennote port-forward service/opennote-web 8080:80` and http://127.0.0.1:8080.

The values (`infrastructure/helm/opennote/values.yaml` describes each one):

| Value | Default | |
|---|---|---|
| `image.apiRepository`, `image.webRepository`, `image.tag`, `image.pullPolicy` | `ghcr.io/theonewizard/opennote-api`, `…/opennote-web`, the chart's `appVersion`, `IfNotPresent` | |
| `imagePullSecrets` | `[]` | |
| `existingSecret` | `opennote` | Keys `OPENNOTE_DATABASE_URL`, `OPENNOTE_VALKEY_URL` |
| `logLevel` | `INFO` | `OPENNOTE_LOG_LEVEL`; `OPENNOTE_ENVIRONMENT` is always `production` |
| `clusterDomain` | `cluster.local` | Used for web's `OPENNOTE_API_UPSTREAM`, `<release>-api.<namespace>.svc.<clusterDomain>:80`. nginx's resolver ignores the resolv.conf search list, so the name must be fully qualified |
| `fsGroup` | `1001` | Left out when `openshift.enabled` is true |
| `openshift.enabled`, `openshift.route.host` | `false`, empty (the router generates a host) | |
| `ingress.enabled`, `ingress.className`, `ingress.annotations`, `ingress.host`, `ingress.tlsSecretName` | `false`, empty, `{}`, empty (any host), empty (no TLS) | |
| `persistence.accessMode`, `persistence.storageClassName`, `persistence.vaults.size`, `persistence.history.size` | `ReadWriteMany`, empty (the default class), `10Gi`, `10Gi` | |
| `api.replicas`, `worker.replicas`, `web.replicas` | `1` | |
| `api.resources`, `worker.resources` | requests 250m CPU and 256Mi, limits 1 CPU and 512Mi | The migration Job uses `api.resources` |
| `web.resources` | requests 50m and 64Mi, limits 250m and 128Mi | |

An Ingress, for an ingress controller you already run:

```bash
helm upgrade opennote infrastructure/helm/opennote --namespace opennote --reuse-values \
  --set ingress.enabled=true --set ingress.className=<class> --set ingress.host=<host> \
  --set ingress.tlsSecretName=<tls-secret>
```

## Apply with kustomize

```bash
kubectl apply -k infrastructure/kubernetes/base
```

The base deploys into the namespace `opennote` and uses the default image names; change them in an overlay (`images:`). Another namespace must also change `OPENNOTE_API_UPSTREAM` in the `web` ConfigMap (`api.opennote.svc.cluster.local:80` in the base), for the reason given for `clusterDomain` above. kustomize has no ordering: the migration Job runs alongside the Deployments. A Job's pod template cannot change, so delete the Job before applying a new image: `kubectl -n opennote delete job migrate --ignore-not-found`.

## OpenShift

Either install the chart with `--set openshift.enabled=true`, or apply the overlay:

```bash
oc apply -k infrastructure/openshift
```

Both differ from plain Kubernetes in two ways:

- **No `fsGroup`.** The `restricted-v2` SCC assigns each pod a UID and an `fsGroup` from the namespace's ranges and refuses a fixed `fsGroup` outside them. The images run with any UID in group 0, and the volumes get the SCC's group.
- **A Route to web** with edge TLS (the router's default certificate) and HTTP redirected to HTTPS: `oc -n opennote get route`. With the chart, `openshift.route.host` sets a host name.

The cluster must run Kubernetes 1.30 or newer (the chart's `kubeVersion`).

## Validation

The `manifests` job of `.github/workflows/containers.yml` runs whenever that workflow does (docs/development/setup.md, "Continuous integration"):

- `helm lint --strict` for the defaults, `openshift.enabled=true`, and an Ingress with a host and TLS;
- `helm template` of the same three variants, and `kubectl kustomize` of the base and the OpenShift overlay;
- a check that nothing renders a Secret, that each of the four pods sets `fsGroup: 1001` on Kubernetes and that none does on OpenShift;
- `kubeconform -strict` of all five renders against the Kubernetes 1.30.0 schemas and the newest ones, with the Route schema from the community CRD catalog (`datreeio/CRDs-catalog`, OpenShift 4.15).

The same locally, with Helm, kustomize and kubeconform installed:

```bash
helm lint --strict infrastructure/helm/opennote
helm template opennote infrastructure/helm/opennote | kubeconform -strict -summary
kustomize build infrastructure/kubernetes/base | kubeconform -strict -summary
```

None of this proves that the manifests work on a cluster: the probes, the migration hook, volume permissions, the SCC and the Route are only exercised by a real deployment.
