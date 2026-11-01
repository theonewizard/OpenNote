# ADR-0007: Native SwiftUI clients with shared Swift packages

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §5 and §6.2 choose SwiftUI for Apple platforms for Spotlight, Share Sheet, Shortcuts, widgets, VisionKit and background tasks.

## Decision
SwiftUI apps for macOS and iOS/iPadOS over five local Swift packages (`OpenNoteCore`, `OpenNoteStorage`, `OpenNoteAPI`, `OpenNoteSync`, `OpenNoteEditor`). `OpenNoteCore` and `OpenNoteStorage` depend only on Foundation and SQLite so they build and test on Linux as well as macOS. Swift 6 language mode with strict concurrency. Minimum OS per decision D3 (macOS 15, iOS 18). The API client is generated with Apple's `swift-openapi-generator` from the committed OpenAPI document.

## Consequences
Two client codebases (Swift and TypeScript) instead of one; mitigated by keeping business rules (merge, validation) on the server and generating API clients.
