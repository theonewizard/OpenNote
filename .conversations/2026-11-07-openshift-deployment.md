# 2026-11-07 — P8-06 OpenShift production deployment

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Workstream 3 of the parallel plan (P8-06, P8-04, P8-08). Several threads now record rulings at the same time, so this workstream numbers its own, R-P8-001 onwards (R-P8-001 to R-P8-009 here; the release and backup records continue at R-P8-010 and R-P8-020).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |

The coordinator turned it into this workstream: P8-06 (needs only P0-11), P8-04 and P8-08; UBI images, no privileged containers, arbitrary UIDs; nothing that incurs charges or touches external production accounts without Flemming's approval; notarization and TestFlight not touched.

## Rulings

- R-P8-001: "Deploys on OpenShift 4.16+" cannot be shown without an OpenShift cluster, and none is available to the project (CRC and OpenShift Local do not fit GitHub's runners). The nearest repeatable evidence is a real deployment on kind in CI at the chart's floor (Kubernetes 1.29, the base of OpenShift 4.16) and at the newest node image, with the two things OpenShift does differently made explicit: Pod Security `restricted` enforced on the namespace, and `restricted-v2`'s arbitrary `runAsUser` and `fsGroup` patched into the overlay's pods. P8-06 is therefore TESTING, not COMPLETED, until it runs on a real cluster. Cost if wrong: a gap between the simulated and the real SCC that only a cluster shows.
- R-P8-002: kind is installed with `go install sigs.k8s.io/kind@v0.33.0` rather than a marketplace action: the Go checksum database pins what is built, and no new third-party action enters the workflows. The 1.29.14 node image predates kind 0.33.0; it starts under it in CI, and the job would show if it stopped doing so.
- R-P8-003: the Pod Security check is the API server's own: a server-side dry run of every template in a namespace labelled `enforce` and `warn` `restricted`, failing on any PodSecurity warning, plus a canary pod without a security context that must be refused. This closes the Phase 0 open item (a throwaway Go program run by hand) with a check that runs on every containers run.
- R-P8-004: the chart gains `networkPolicy.enabled` (default `false`, so existing installs do not change): the API accepts only the release's web pods, the worker accepts nothing, web stays open for the router or ingress controller, egress is left alone because the database and Valkey are external. The deployment test turns it on and checks both directions, with a positive control so a broken probe cannot pass as "blocked". The production guide says to turn it on.
- R-P8-005: the chart gains `openshift.route.annotations` for HSTS and router timeouts, and nothing else on the Route: a custom certificate stays a router-level or operator-made Route decision, because putting certificate material into Helm values would put a private key into the release's stored values.
- R-P8-006: the deploy job's checks are named `deploy (Kubernetes 1.29)` and `deploy (Kubernetes 1.37)`, short enough to list as required checks; workflow.md lists them for branch protection.

## Output

Branch `feature/openshift-deployment` in `.worktrees/openshift/`: `scripts/kind-deploy-test.sh`, the `deploy` job in `.github/workflows/containers.yml`, the chart's NetworkPolicy template and Route annotations, `docs/deployment/kubernetes.md` (status, values, network policy, production on OpenShift, deployment test), the CI and branch-protection lists in setup.md and workflow.md, the P8-06 rows in ROADMAP.md and IMPLEMENTATION_STATUS.md, and this record.
