# Security Policy

## Supported versions

OpenNote has not been released yet. Only the `main` branch is supported: fixes land there,
and there are no release branches to backport them to.

## Reporting a vulnerability

Please do not report security problems in public issues, pull requests or discussions.
Report them privately through GitHub's form instead:
https://github.com/theonewizard/OpenNote/security/advisories/new

A useful report includes:

- what is affected: the component (API, worker, web app, Apple apps, container images, CI)
  and the commit or version;
- what an attacker can do, and what they need to do it;
- steps to reproduce, or a proof of concept;
- any idea you have for a fix or a mitigation.

Do not include real user data, or credentials that are still valid, in a report.

## What happens next

- We acknowledge a report within seven days.
- We investigate, keep you informed through the advisory, and agree a fix with you.
- Disclosure is coordinated: the advisory is published once a fix is on `main`, crediting
  you unless you prefer otherwise.

There is no bug bounty.

## Threat model

The assets, trust boundaries and controls the project defends are described in
[docs/security/threat-model.md](docs/security/threat-model.md).
