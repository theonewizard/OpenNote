#!/usr/bin/env bash
# Deploy OpenNote to the Kubernetes cluster of the current kubectl context (a throwaway kind
# cluster in CI) and check that it works (docs/deployment/kubernetes.md, "Deployment test"):
#
#   1. Helm chart, Kubernetes variant, with the network policy on, in a namespace that
#      enforces Pod Security "restricted": no template may draw a PodSecurity warning; the
#      migration hook runs, every pod becomes ready, the smoke test passes through web, the
#      API is unreachable from any other pod, an upgrade re-runs the migration, and
#      `helm uninstall` keeps both volumes.
#   2. The OpenShift kustomize overlay with what the restricted-v2 SCC does to a pod
#      simulated: an arbitrary UID and fsGroup from a namespace range, no Route (kind has no
#      router). Every pod becomes ready and the smoke test passes.
#
#   scripts/kind-deploy-test.sh
#
# Needs kubectl, helm, curl and a cluster whose nodes already hold the images
# opennote-api:dev, opennote-web:dev, opennote-postgres:dev and opennote-valkey:dev
# (`kind load docker-image`), and a default StorageClass. PostgreSQL and Valkey run as test
# fixtures with throwaway passwords and emptyDir storage. Creates and deletes the namespaces
# opennote-test and opennote; refuses to run against a cluster that already has either.
# Exits 0 when every check passes, otherwise non-zero after printing the failing check and
# the namespace's state.
set -euo pipefail

cd "$(dirname "$0")/.."
chart=infrastructure/helm/opennote
helm_ns=opennote-test
oc_ns=opennote # the overlay's namespace (infrastructure/openshift/kustomization.yaml)
work=$(mktemp -d)
port_forward=

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

dump() {
  local ns
  for ns in "$helm_ns" "$oc_ns"; do
    kubectl get namespace "$ns" >/dev/null 2>&1 || continue
    echo "::group::state of namespace $ns"
    kubectl -n "$ns" get all,pvc,networkpolicy -o wide || true
    kubectl -n "$ns" get events --sort-by=.lastTimestamp || true
    kubectl -n "$ns" logs --all-containers --prefix --tail=50 -l app.kubernetes.io/name=opennote || true
    echo "::endgroup::"
  done
}

cleanup() {
  local status=$?
  [[ -n $port_forward ]] && kill "$port_forward" 2>/dev/null
  ((status == 0)) || dump
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

for ns in "$helm_ns" "$oc_ns"; do
  ! kubectl get namespace "$ns" >/dev/null 2>&1 || fail "namespace $ns exists; use a throwaway cluster"
done

# A namespace that enforces Pod Security "restricted", and warns about it too: enforcement
# applies to pods, the warning also to the Deployments and Jobs that would create them.
make_namespace() {
  kubectl create namespace "$1"
  kubectl label namespace "$1" pod-security.kubernetes.io/enforce=restricted \
    pod-security.kubernetes.io/warn=restricted
}

# PostgreSQL and Valkey from the repository's images, and the Secret opennote with their URLs.
# Throwaway credentials for a throwaway cluster.
fixtures() {
  local ns=$1
  kubectl -n "$ns" apply -f - <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: {name: postgres}
spec:
  selector: {matchLabels: {app: postgres}}
  template:
    metadata: {labels: {app: postgres}}
    spec:
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: postgres
          image: opennote-postgres:dev
          imagePullPolicy: Never
          env:
            - {name: POSTGRES_USER, value: opennote}
            - {name: POSTGRES_PASSWORD, value: opennote}
            - {name: POSTGRES_DB, value: opennote}
          ports: [{containerPort: 5432}]
          readinessProbe:
            exec: {command: [pg_isready, --quiet, --host=127.0.0.1, --port=5432, --username=opennote]}
            periodSeconds: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: [ALL]}
          volumeMounts:
            - {name: data, mountPath: /var/lib/postgresql/data}
            - {name: tmp, mountPath: /tmp}
            - {name: shm, mountPath: /dev/shm}
      volumes:
        - {name: data, emptyDir: {}}
        - {name: tmp, emptyDir: {}}
        - {name: shm, emptyDir: {medium: Memory, sizeLimit: 256Mi}}
---
apiVersion: v1
kind: Service
metadata: {name: postgres}
spec:
  selector: {app: postgres}
  ports: [{port: 5432}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: valkey}
spec:
  selector: {matchLabels: {app: valkey}}
  template:
    metadata: {labels: {app: valkey}}
    spec:
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: valkey
          image: opennote-valkey:dev
          imagePullPolicy: Never
          ports: [{containerPort: 6379}]
          readinessProbe:
            exec: {command: [valkey-cli, -h, 127.0.0.1, ping]}
            periodSeconds: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: [ALL]}
          volumeMounts: [{name: tmp, mountPath: /tmp}]
      volumes: [{name: tmp, emptyDir: {}}]
---
apiVersion: v1
kind: Service
metadata: {name: valkey}
spec:
  selector: {app: valkey}
  ports: [{port: 6379}]
YAML
  kubectl -n "$ns" create secret generic opennote \
    --from-literal="OPENNOTE_DATABASE_URL=postgresql+psycopg://opennote:opennote@postgres.$ns.svc.cluster.local:5432/opennote" \
    --from-literal="OPENNOTE_VALKEY_URL=redis://valkey.$ns.svc.cluster.local:6379/0"
  kubectl -n "$ns" rollout status deployment/postgres deployment/valkey --timeout=300s
}

# smoke <namespace> <web service>: the repository's smoke test through a port-forward to web.
smoke() {
  kubectl -n "$1" port-forward "service/$2" 18080:80 >"$work/port-forward.log" 2>&1 &
  port_forward=$!
  scripts/smoke-test.sh http://127.0.0.1:18080
  kill "$port_forward"
  wait "$port_forward" 2>/dev/null || true
  port_forward=
}

# worker_steady <namespace> <selector>: every worker container is running and never restarted.
worker_steady() {
  local restarts
  restarts=$(kubectl -n "$1" get pods -l "$2" \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[*].restartCount}{"\n"}{end}')
  echo "worker restart counts: $restarts"
  [[ -n $restarts && -z ${restarts//[0$'\n']/} ]] || fail "a worker restarted"
}

echo "== 1. Helm chart in namespace $helm_ns"
make_namespace "$helm_ns"
fixtures "$helm_ns"
helm_args=(
  --namespace "$helm_ns"
  --set image.apiRepository=opennote-api --set image.webRepository=opennote-web
  --set image.tag=dev --set image.pullPolicy=Never
  --set persistence.accessMode=ReadWriteOnce # kind's local-path provisioner has no RWX
  --set networkPolicy.enabled=true
)

# The rendered templates, migration hook included, against the API server's admission:
# any "would violate PodSecurity" warning fails.
helm template opennote "$chart" "${helm_args[@]}" |
  kubectl -n "$helm_ns" apply --dry-run=server -f - 2>"$work/dry-run.err" >/dev/null ||
  { cat "$work/dry-run.err" >&2; fail "server-side dry run of the chart"; }
cat "$work/dry-run.err" >&2
! grep -q 'PodSecurity' "$work/dry-run.err" || fail "the chart draws PodSecurity warnings"

helm install opennote "$chart" "${helm_args[@]}" --wait --timeout 10m
kubectl -n "$helm_ns" get job opennote-migrate -o jsonpath='{.status.succeeded}' | grep -qx 1 ||
  fail "the migration Job did not succeed"
smoke "$helm_ns" opennote-web
worker_steady "$helm_ns" app.kubernetes.io/component=worker

# The network policy: a pod that is not the release's web cannot reach the API. Positive
# control first, from a pod labelled as web, so a broken probe cannot pass as "blocked".
probe() {
  local name=$1 component=$2
  kubectl -n "$helm_ns" run "$name" --image=opennote-api:dev --image-pull-policy=Never \
    --restart=Never --quiet --attach --rm \
    --labels="app.kubernetes.io/name=opennote,app.kubernetes.io/instance=opennote,app.kubernetes.io/component=$component" \
    --overrides='{"apiVersion": "v1", "spec": {"automountServiceAccountToken": false,
      "securityContext": {"runAsNonRoot": true, "seccompProfile": {"type": "RuntimeDefault"}},
      "containers": [{"name": "probe", "image": "opennote-api:dev", "imagePullPolicy": "Never",
        "command": ["python", "-c", "import urllib.request; urllib.request.urlopen(\"http://opennote-api/healthz\", timeout=5)"],
        "securityContext": {"allowPrivilegeEscalation": false, "capabilities": {"drop": ["ALL"]}}}]}}'
}
probe probe-web web || fail "a pod labelled as web cannot reach the API"
! probe probe-other other 2>/dev/null || fail "the network policy lets any pod reach the API"
echo "network policy: web reaches the API, another pod does not"

migrated_before=$(kubectl -n "$helm_ns" get job opennote-migrate -o jsonpath='{.metadata.uid}')
helm upgrade opennote "$chart" "${helm_args[@]}" --set logLevel=DEBUG --wait --timeout 10m
migrated_after=$(kubectl -n "$helm_ns" get job opennote-migrate -o jsonpath='{.metadata.uid}')
[[ $migrated_before != "$migrated_after" ]] || fail "helm upgrade did not run the migration again"
smoke "$helm_ns" opennote-web
worker_steady "$helm_ns" app.kubernetes.io/component=worker

helm uninstall opennote --namespace "$helm_ns" --wait
kubectl -n "$helm_ns" get pvc opennote-vaults opennote-history || fail "helm uninstall removed a volume"
kubectl delete namespace "$helm_ns" --wait=false

echo "== 2. OpenShift overlay in namespace $oc_ns, restricted-v2 SCC simulated"
make_namespace "$oc_ns"
fixtures "$oc_ns"
overlay=$(realpath --relative-to="$work" infrastructure/openshift)
# What restricted-v2 adds to each pod (a UID and an fsGroup from the namespace's range;
# 1000870000 is a typical one), the local images, RWO volumes, and no Route.
cat >"$work/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [$overlay]
images:
  - {name: ghcr.io/theonewizard/opennote-api, newName: opennote-api, newTag: dev}
  - {name: ghcr.io/theonewizard/opennote-web, newName: opennote-web, newTag: dev}
patches:
  - target: {kind: Deployment|Job}
    patch: |-
      - {op: add, path: /spec/template/spec/securityContext/runAsUser, value: 1000870000}
      - {op: add, path: /spec/template/spec/securityContext/fsGroup, value: 1000870000}
      - {op: add, path: /spec/template/spec/containers/0/imagePullPolicy, value: Never}
  - target: {kind: PersistentVolumeClaim}
    patch: |-
      - {op: replace, path: /spec/accessModes, value: [ReadWriteOnce]}
  - patch: |-
      \$patch: delete
      apiVersion: route.openshift.io/v1
      kind: Route
      metadata: {name: web}
YAML
kubectl kustomize "$work" >"$work/openshift.yaml"
! grep -q '^kind: Route$' "$work/openshift.yaml" || fail "the Route was not removed"
kubectl apply -f "$work/openshift.yaml" 2>"$work/apply.err" || { cat "$work/apply.err" >&2; fail "kubectl apply of the overlay"; }
cat "$work/apply.err" >&2
! grep -q 'PodSecurity' "$work/apply.err" || fail "the overlay draws PodSecurity warnings"
kubectl -n "$oc_ns" wait job/migrate --for=condition=Complete --timeout=300s
kubectl -n "$oc_ns" rollout status deployment/api deployment/worker deployment/web --timeout=300s
uid=$(kubectl -n "$oc_ns" exec deployment/api -- id -u)
[[ $uid == 1000870000 ]] || fail "api runs as UID $uid, not the assigned 1000870000"
smoke "$oc_ns" web
worker_steady "$oc_ns" app.kubernetes.io/component=worker
kubectl delete namespace "$oc_ns" --wait=false

echo "deployment test passed"
