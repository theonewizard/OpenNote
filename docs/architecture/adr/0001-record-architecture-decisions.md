# ADR-0001: Record architecture decisions

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
The design document asks for documented decisions (§15.3, §15.16, §16). Several of its sections contradict each other, so the resolution needs a durable record.

## Decision
Use lightweight ADRs (Nygard format) in `docs/architecture/adr/NNNN-title.md`. An ADR is immutable once accepted; a change of mind is a new ADR that supersedes the old one. Any technology that deviates from design §15.3 needs an ADR (design §15.3, last line).

## Consequences
Reviewers find the reason for each choice in one place. ADR status starts as *Proposed* until Flemming reviews it.
