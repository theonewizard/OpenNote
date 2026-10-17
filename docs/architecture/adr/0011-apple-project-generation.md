# ADR-0011: Generate the Xcode project with XcodeGen

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §6.2 shows `apple/OpenNote.xcodeproj` in the tree. Hand-edited `.pbxproj` files cause merge conflicts and cannot be reviewed meaningfully, and AI agents editing them without Xcode is error-prone.

## Decision
Describe targets in `apple/project.yml` and generate `OpenNote.xcodeproj` with **XcodeGen** (`make apple-project`). The generated project is git-ignored. Swift packages are plain SPM packages buildable with `swift build` independent of Xcode.

## Consequences
Reviewable project configuration and reproducible builds on CI (macOS runners) and on Flemming's Mac. One extra tool (`brew install xcodegen`). Tuist was the alternative; XcodeGen is smaller and sufficient.
