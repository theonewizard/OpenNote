# Consulting OpenNotes — Powered by Obsidian

> Source design document as posted by Flemming in the OpenNote project on 2026-10-17. Transcribed verbatim; only formatting was changed (tab-separated tables turned into Markdown tables, diagrams and code put in fenced blocks, headings marked). The interpretation, contradictions and decisions are in `docs/superpowers/specs/2026-10-17-opennote-architecture-design.md`.

Project: Consulting OpenNotes — Powered by Obsidian
Product Design, Architecture, AI Coding Prompt & Implementation Roadmap
Target platforms: macOS, iOS, iPadOS, and Web Backend: Obsidian-compatible Markdown vaults Deployment: Self-hosted Linux containers, based Red Hat UBI Architecture: Local-first, client offline-capable, API-driven Development approach: AI-assisted development with Claude Code and reviewing using  Project status: Proposed architecture and implementation plan

---

## 1. Executive Summary

I investigated Evernote's current capabilities, including the major features introduced in Evernote v11 in January 2026.

Evernote has evolved beyond a note-taking application into a productivity platform combining:

* Notes and rich-text editing
* Notebooks, tags, and spaces
* Document management
* Web clipping
* Tasks and reminders
* Calendar integration
* Document scanning and OCR
* AI-assisted search and knowledge management
* AI meeting notes and transcription
* Cross-device synchronization
* Collaboration and sharing

Introduced AI Assistant, semantic search, and AI Meeting Notes.

The proposed application should reproduce these core capabilities while addressing several limitations of traditional cloud-based note-taking systems. The AI integration last

### Primary design objectives

1. Data ownership
   All notes must be stored as standard Markdown files compatible with Obsidian.
   Users should be able to open their vault directly in Obsidian without conversion.
2. Local-first operation
   The macOS and iOS applications must function without an internet connection.
   Synchronization happens automatically when connectivity returns.
3. Self-hosted backend
   The backend should run in Linux containers and support:
   * Docker Compose
   * Podman
   * Kubernetes
   * OpenShift

   Require Red Hat Universal Base Images.
4. Modern applications
   Deliver a consistent experience across macOS, iPhone, iPad, and web browsers based on a Reversed engineering of Evernote v11 using reverse engineer everything
5. AI-powered productivity
   Use local AI for:
   * Semantic search
   * Automatic tagging
   * Document classification
   * Summarization
   * Meeting transcription
   * Knowledge extraction
   * Natural-language interaction with notes

   AI should be optional, privacy-preserving, and configurable.
6. Open architecture
   Avoid proprietary storage formats and unnecessary vendor dependencies.
   The system should remain usable even if its backend services are unavailable.

---

## 2. Evernote Feature Investigation

The following feature inventory is based on Evernote's published product information and documentation.

Sources:

* Evernote official website
* Evernote feature comparison
* Evernote v11 announcement
* Evernote AI documentation

### 2.1 Feature Comparison

The proposed application will be called OpenNote throughout this design. This is a working name.

| Feature | Evernote | OpenNote target | Priority |
|---|---|---|---|
| Rich-text editor | Yes | Yes | P0 |
| Markdown editing | Limited/native format differs | Native Markdown | P0 |
| Notebooks | Yes | Yes | P0 |
| Nested notebooks | Organization-dependent | Native folders | P0 |
| Tags | Yes | Yes | P0 |
| Spaces | Yes | Yes | P1 |
| Attachments | Yes | Yes | P0 |
| PDF preview | Yes | Yes | P0 |
| Image preview | Yes | Yes | P0 |
| Full-text search | Yes | Yes | P0 |
| Offline notes | Yes | Yes | P0 |
| Cross-device sync | Yes | Self-hosted | P0 |
| Web application | Yes | Yes | P0 |
| macOS application | Yes | Yes | P0 |
| iOS application | Yes | Yes | P0 |
| iPadOS application | Yes | Yes | P0 |
| Web clipping | Yes | Yes | P1 |
| Email-to-note | Yes | Yes | P2 |
| Document scanning | Yes | Yes | P1 |
| OCR | Yes | Yes | P1 |
| Tasks | Yes | Yes | P1 |
| Recurring tasks | Yes | Yes | P1 |
| Reminders | Yes | Yes | P1 |
| Calendar integration | Yes | Yes | P1 |
| Templates | Yes | Yes | P1 |
| Note history | Yes | Yes | P1 |
| Note sharing | Yes | Yes | P2 |
| Collaboration | Yes | Yes | P2 |
| AI Assistant | Yes | Local AI | P2 |
| Semantic search | Yes | Local AI | P2 |
| AI transcription | Yes | Local AI | P2 |
| AI Meeting Notes | Yes | Local AI | P2 |
| Backlinks | Not a core Evernote strength | Native | P1 |
| Knowledge graph | Not a core Evernote feature | Yes | P2 |
| Obsidian compatibility | No | Yes | P0 |
| Self-hosting | No | Yes | P0 |
| User-owned Markdown | No | Yes | P0 |

Priority definitions:

* P0: Required for the initial usable product.
* P1: Required for a feature-complete productivity application.
* P2: Advanced functionality and differentiation.

The biggest architectural difference is that OpenNote will treat Markdown files as its authoritative data source rather than storing notes in a proprietary database.

---

## 3. Obsidian as the Storage Backend

An important distinction:

Obsidian is an application, not a database server.

Obsidian stores notes as Markdown files in a directory called a vault. Images, PDFs, and other attachments are stored as ordinary files.

Its documentation confirms that vaults can be accessed by other editors and file-management tools.

Therefore, I recommend building an Obsidian-compatible storage engine, rather than attempting to use Obsidian itself as a backend service.

This distinction allows us to maintain full compatibility without depending on Obsidian's application runtime.

### 3.1 Storage Principles

The following rules should be mandatory.

1. Markdown files are the authoritative source for note content.
2. YAML frontmatter stores portable note metadata.
3. Attachments remain ordinary files.
4. Standard Obsidian wiki-links are supported.
5. Existing Obsidian vaults can be opened without conversion.
6. OpenNote-specific metadata must not interfere with Obsidian.
7. The application must detect modifications made directly through Obsidian.
8. Database indexes must be rebuildable from the vault.
9. Users must be able to export their entire vault without proprietary conversion.
10. The system must never silently rewrite or discard unsupported Markdown syntax.

### 3.2 Proposed Vault Structure

```
OpenNoteVault/
│
├── Inbox/
│   ├── Quick Note.md
│   └── Captured Article.md
│
├── Personal/
│   ├── Journal/
│   │   ├── 2026-10-17.md
│   │   └── 2026-10-18.md
│   │
│   ├── Projects/
│   └── Ideas/
│
├── Work/
│   ├── Meetings/
│   ├── Projects/
│   └── Documentation/
│
├── Templates/
│   ├── Meeting.md
│   ├── Project.md
│   └── Daily Note.md
│
├── Attachments/
│   ├── Images/
│   ├── Documents/
│   └── Audio/
│
├── .obsidian/
│   └── ...
│
└── .opennote/
    ├── config.json
    └── metadata/
```

The .opennote directory should contain only portable configuration and carefully scoped application metadata.

Search indexes, embeddings, temporary files, and device-specific caches should live outside the vault.

This prevents application-generated data from unnecessarily appearing in Obsidian.

---

## 4. Note Data Model

Each note should use Markdown with YAML frontmatter.

Example:

```markdown
---
id: 018f5a40-2d14-7b9c-8e3a-123456789abc
title: Project Architecture
created: 2026-10-17T10:30:00Z
modified: 2026-10-17T11:45:00Z

tags:
  - architecture
  - development
  - project

aliases:
  - Architecture Design

opennote:
  favorite: true
  archived: false
  status: active
---

# Project Architecture

This document describes the system architecture.

## Requirements

- Support macOS
- Support iOS
- Support Web
- Store notes in Markdown

## Related Documents

[[Backend Architecture]]

[[Development Roadmap]]

## Tasks

- [ ] Create architecture
- [ ] Implement backend
- [ ] Implement frontend
```

### Metadata rules

Use standard Obsidian-compatible properties wherever possible.

Application-specific properties should be namespaced.

The id provides stable identity even when the user renames or moves the file.

Because existing Obsidian notes may not have an ID, the application must also support notes without frontmatter.

It should not automatically insert metadata into existing notes merely because they were opened.

A migration or normalization operation must be explicit.

---

## 5. Recommended System Architecture

I recommend a hybrid architecture:

* SwiftUI for macOS and iOS
* React/TypeScript for web
* Python/FastAPI for backend services
* PostgreSQL for operational metadata
* SQLite for local caches
* Markdown vaults for authoritative note storage
* Local AI services for optional intelligence

Although a single cross-platform framework could reduce initial development effort, native SwiftUI provides stronger integration with Apple-specific features.

Examples include:

* Spotlight
* Share Sheet
* Shortcuts
* Widgets
* Apple Pencil
* Document scanning
* Background synchronization
* Native notifications

The shared API and data model will ensure consistent behavior.

### 5.1 Architecture Diagram

```
                    CLIENT APPLICATIONS
  ┌───────────────────────────────────────────────┐
  │                                               │
  │   macOS App        iOS / iPadOS App            │
  │    SwiftUI             SwiftUI                 │
  │                                               │
  │                 Web Application               │
  │                  React / TS                   │
  │                                               │
  └──────────────────────┬────────────────────────┘
                         │
                  HTTPS / WebSocket
                         │
  ┌──────────────────────▼────────────────────────┐
  │                                               │
  │                 API GATEWAY                   │
  │                                               │
  │          Authentication / Authorization       │
  │             REST / WebSocket API              │
  │                                               │
  └──────────────────────┬────────────────────────┘
                         │
  ┌──────────────────────▼────────────────────────┐
  │                                               │
  │              APPLICATION BACKEND              │
  │                                               │
  │  ┌─────────────┐  ┌──────────────────────┐    │
  │  │ Note        │  │ Sync                 │    │
  │  │ Service     │  │ Service              │    │
  │  └─────────────┘  └──────────────────────┘    │
  │                                               │
  │  ┌─────────────┐  ┌──────────────────────┐    │
  │  │ Search      │  │ Task                 │    │
  │  │ Service     │  │ Service              │    │
  │  └─────────────┘  └──────────────────────┘    │
  │                                               │
  │  ┌─────────────┐  ┌──────────────────────┐    │
  │  │ Attachment  │  │ Calendar             │    │
  │  │ Service     │  │ Service              │    │
  │  └─────────────┘  └──────────────────────┘    │
  │                                               │
  │  ┌──────────────────────────────────────┐     │
  │  │ AI / OCR / Transcription Service     │     │
  │  └──────────────────────────────────────┘     │
  │                                               │
  └──────────────┬──────────────┬─────────────────┘
                 │              │
       ┌─────────▼──────┐  ┌────▼───────────────┐
       │                │  │                    │
       │ OBSIDIAN VAULT │  │ DATABASE / INDEX   │
       │                │  │                    │
       │ Markdown       │  │ PostgreSQL         │
       │ YAML           │  │ Full-text index    │
       │ Attachments    │  │ Vector index       │
       │                │  │ Sync state         │
       │                │  │                    │
       └────────────────┘  └────────────────────┘
```

### Important architectural boundary

The backend database must never become the only place where a note's essential content exists.

PostgreSQL can hold:

* User accounts
* Access permissions
* Sync cursors
* Device registrations
* Task scheduling state
* Search indexes
* Embeddings
* Background job state

But Markdown files remain the source of truth for note content.

---

## 6. Technology Stack

### 6.1 Backend  Use the Latest version of the below tools and these are minimums

| Component | Recommended technology |
|---|---|
| Programming language | Python 3.13+ |
| API framework | FastAPI |
| Validation | Pydantic |
| ORM | SQLAlchemy |
| Database migrations | Alembic |
| Operational database | PostgreSQL |
| Search | PostgreSQL full-text search |
| Vector search | pgvector |
| Background jobs | Redis-backed worker |
| File monitoring | watchdog |
| Markdown parsing | markdown-it-py |
| Authentication | OIDC / OAuth 2.0 |
| WebSocket support | FastAPI |
| API documentation | OpenAPI |
| Container images | Red Hat UBI |
| Testing | pytest |
| Observability | OpenTelemetry |

I would initially deploy a collection of independent microservices.

This reduces complexity while preserving clear boundaries between services.

Background workers and AI inference can run as separate processes.

The architecture should permit future service extraction without requiring it from day one.

### 6.2 Apple Applications

| Component | Technology |
|---|---|
| Language | Swift |
| UI | SwiftUI |
| Local database | SQLite |
| Networking | URLSession |
| Background operations | BackgroundTasks |
| Authentication | AuthenticationServices |
| Secure credentials | Keychain |
| Document scanning | VisionKit |
| OCR | Vision |
| Notifications | UserNotifications |
| File integration | FileProvider where appropriate |
| Share extension | Share Extension |
| Widgets | WidgetKit |

Shared business logic should be implemented in a Swift Package.

Suggested structure:

```
apple/
├── OpenNote.xcodeproj
│
├── Apps/
│   ├── macOS/
│   └── iOS/
│
├── Packages/
│   ├── OpenNoteCore/
│   ├── OpenNoteAPI/
│   ├── OpenNoteStorage/
│   ├── OpenNoteSync/
│   └── OpenNoteEditor/
│
└── Tests/
```

### 6.3 Web Application

| Component | Technology |
|---|---|
| Framework | React |
| Language | TypeScript |
| Build system | Vite |
| UI components | shadcn/ui |
| Styling | Tailwind CSS |
| Editor | TipTap / ProseMirror |
| Markdown parsing | remark / unified |
| State management | Zustand |
| API caching | TanStack Query |
| Offline storage | IndexedDB |
| PWA | Service Worker |
| Testing | Vitest / Playwright |

#### Editor architecture

The editor deserves special attention.

Rich-text editors and Markdown do not have identical document models.

A naive Markdown-to-HTML-to-Markdown conversion can destroy:

* Wiki-links
* Embedded files
* Callouts
* Frontmatter
* Custom Markdown extensions
* Unsupported syntax

Therefore, the editor must preserve unsupported syntax rather than silently discard it.

For the first release, I recommend a Markdown-first editor with live preview.

A full WYSIWYG editor can be added after round-trip compatibility tests are established.

---

## 7. Synchronization Architecture

Synchronization is one of the highest-risk components.

Obsidian supports multiple synchronization methods, including Obsidian Sync and file-based solutions. Its documentation also warns against mixing synchronization services for the same vault because of potential conflicts.

OpenNote should implement its own synchronization protocol.

It must not attempt to use Obsidian Sync's proprietary protocol.

### 7.1 Sync Requirements

The system must support:

* Offline editing
* Incremental synchronization
* Attachment synchronization
* File renaming
* Folder movement
* Deleted-file propagation
* Conflict detection
* Conflict recovery
* Version history
* Interrupted synchronization
* Multiple devices
* Direct Obsidian modifications

### 7.2 Recommended Sync Strategy

Use a revision-based synchronization protocol.

Each note has:

```json
{
  "note_id": "018f5a40-2d14-7b9c-8e3a-123456789abc",
  "revision": 42,
  "content_hash": "sha256:...",
  "modified_at": "2026-10-17T12:00:00Z",
  "device_id": "macbook-01"
}
```

Every write should include the revision the client originally read.

The server must reject stale writes instead of silently overwriting newer content.

#### Conflict example

```
MacBook:
    Note revision 10
    Edited offline
    Creates revision 11A

iPhone:
    Note revision 10
    Edited offline
    Creates revision 11B

Both reconnect.

Server:
    Detects divergent changes.

Resolution:
    Attempt safe three-way merge.

If merge is unsafe:
    Preserve both versions.
    Present conflict resolution UI.
```

Never silently overwrite conflicting note content.

#### Advanced option

A CRDT-based editor could eventually support simultaneous collaborative editing.

However, I would not use CRDTs as the initial synchronization foundation.

The first implementation should prioritize correctness, predictable conflict handling, and preservation of Markdown files.

Real-time collaboration can be added later as a separate capability.

---

## 8. Search Architecture

Evernote supports advanced search and semantic retrieval, including information extracted from attachments.

OpenNote should provide two search modes.

### 8.1 Traditional Search

Features:

* Full-text search
* Title search
* Tag search
* Notebook filtering
* Date filtering
* Attachment search
* Boolean operators
* Saved searches
* Search suggestions

Example:

```
tag:project notebook:Work "architecture"
```

Advanced examples:

```
created:2026-01-01
has:attachment type:pdf
tag:meeting after:2026-09-01
```

The search parser should have a documented grammar.

### 8.2 Semantic Search

Semantic search allows queries such as:

> Find the notes where I discussed replacing the backup infrastructure.

The system should find relevant notes even when they do not contain those exact words.

Recommended architecture:

```
Markdown Notes
      │
      ▼
Document Parser
      │
      ▼
Text Chunking
      │
      ▼
Embedding Model
      │
      ▼
pgvector
      │
      ▼
Hybrid Search
      │
      ▼
Ranked Results
```

Use a combination of:

* Keyword search
* Vector similarity
* Metadata filtering
* Optional reranking

AI-generated results must include references to the original notes.

---

## 9. Local AI Architecture

I recommend making AI a separate optional subsystem.

The application should remain fully functional without AI services.

### 9.1 AI Features

#### AI Assistant

Example:

> Summarize everything I have written about the IBM Power infrastructure project.

The assistant should retrieve relevant notes, summarize their content, and provide links back to the sources.

#### Automatic Tagging

Example:

A new note contains:

> Meeting about Red Hat OpenShift virtualization, storage migration and backup strategy.

Suggested tags:

```
openshift
virtualization
storage
backup
meeting
```

#### Document Classification

Automatically suggest:

* Notebook
* Tags
* Document type
* Related notes
* Follow-up tasks

#### Meeting Notes

Support:

1. Audio recording
2. Speech transcription
3. Speaker identification where available
4. Summary generation
5. Action-item extraction
6. Creation of linked notes
7. Optional task creation

#### AI Search

Example:

> What decisions did we make about the storage architecture last month?

The system should answer using only authorized notes and clearly identify supporting sources.

### 9.2 Recommended AI Components

| Component | Recommendation |
|---|---|
| Local LLM runtime | Ollama |
| Alternative inference runtime | llama.cpp |
| Speech recognition | faster-whisper |
| Embeddings | Local embedding model |
| Vector storage | pgvector |
| OCR | Tesseract / Apple Vision |
| AI orchestration | Python |
| Model management | Configurable |
| External AI | Optional, disabled by default |

Do not hard-code one language model.

Instead, introduce a provider abstraction:

```python
class AIProvider:
    async def generate(self, prompt: str):
        ...

    async def embed(self, text: str):
        ...

    async def transcribe(self, audio: bytes):
        ...
```

The actual interfaces should use typed request and response objects.

The application should support different providers without requiring changes to business logic.

---

## 10. Additional Features Beyond Evernote

I recommend including several capabilities that make OpenNote particularly valuable.

### 10.1 Obsidian Backlinks

Support:

```
[[Project Architecture]]
```

When opening the note, display:

* Outgoing links
* Incoming links
* Unresolved links
* Related notes

### 10.2 Knowledge Graph

Visualize relationships between notes.

Filtering should support:

* Notebook
* Tags
* Date
* Link depth

### 10.3 Multiple Vaults

Users should be able to maintain independent vaults.

Example:

```
Personal Vault
Work Vault
Research Vault
Archive Vault
```

Each vault can have different:

* Synchronization settings
* Permissions
* AI configuration
* Backup policies

### 10.4 Version History

Maintain historical revisions.

Features:

* Compare revisions
* Restore older versions
* Recover deleted notes
* Track modifications
* Export revision history

Version history must not depend solely on database backups.

### 10.5 Automation

Expose an API for external integrations.

Potential integrations:

* Home Assistant
* Apple Shortcuts
* Email
* Calendar
* GitHub
* Webhooks
* MCP-compatible AI tools

---

## 11. Deployment Architecture

The backend should support self-hosted deployment.

### 11.1 Container Structure

```
OpenNote Deployment
│
├── opennote-api
│   └── FastAPI
│
├── opennote-worker
│   └── Background processing
│
├── opennote-web
│   └── React application
│
├── opennote-ai
│   └── Optional AI inference
│
├── postgresql
│   ├── Application metadata
│   ├── Search
│   └── Vector indexes
│
├── redis
│   └── Background job coordination
│
└── volumes
    ├── vaults/
    ├── database/
    └── backups/
```

### 11.2 Deployment Requirements

Support:

Development

```
docker compose up -d
```

Podman

```
podman compose up -d
```

Production

* Kubernetes manifests
* Helm charts
* OpenShift-compatible deployment
* Persistent volumes
* Secrets management
* Health checks
* Resource limits
* Backup and restore

Container images should use Red Hat UBI where practical.

The deployment must not require privileged containers.

OpenShift deployments should support arbitrary runtime UIDs and restricted security contexts.

---

## 12. Security Architecture

Security should be included from the beginning rather than added near release.

### Authentication

Support:

* Local authentication
* OpenID Connect
* OAuth 2.0
* Multi-factor authentication through the identity provider
* Session management
* Device registration

### Authorization

Use vault-level access controls.

Future collaboration should support:

* Owner
* Editor
* Viewer

### Encryption

* TLS for network traffic
* Encryption at rest where configured
* Secure credential storage
* Encrypted backups
* Optional client-side encryption in a later phase

Full end-to-end encryption requires additional design because server-side search, OCR, and AI processing may need access to plaintext.

Do not advertise end-to-end encryption unless the architecture actually guarantees it.

### Operational Security

Include:

* Audit logging
* Rate limiting
* Input validation
* Dependency scanning
* Container image scanning
* Secrets management
* Secure file uploads
* Path traversal protection
* Attachment malware scanning where available

---

## 13. Development Roadmap

The following is a proposed implementation schedule, not a record of completed development.

The timeline assumes approximately three full-time engineers with AI-assisted development, plus part-time QA and design support.

A single developer should expect a longer schedule.

### Phase 0 — Foundation and Architecture

Duration: 2 weeks

Deliverables

* Repository initialization
* Architecture documentation
* Coding standards
* Development environment
* CI/CD
* Container configuration
* API conventions
* Data model specification
* Initial UI design system
* Security threat model

Acceptance Criteria

* Repository builds successfully.
* Backend starts in containers.
* Apple applications compile.
* Web application compiles.
* CI runs automated tests.
* Architecture decisions are documented.

Milestone M0: Development environment ready

### Phase 1 — Vault Storage Engine

Duration: 3 weeks

Deliverables

* Vault management
* Markdown parser
* YAML frontmatter support
* Note creation
* Note modification
* Note deletion
* Folder management
* Attachment management
* File-system watcher
* Metadata indexing

Critical Tests

* Existing Obsidian vault opens successfully.
* Notes retain their Markdown syntax.
* Unsupported Markdown remains intact.
* External file modifications are detected.
* Renaming notes does not lose their identity.
* Attachments remain accessible.

Milestone M1: Obsidian-compatible storage engine

### Phase 2 — Backend API

Duration: 3 weeks

Deliverables

* REST API
* Authentication
* Vault API
* Notes API
* Tags API
* Attachments API
* Search API
* Database migrations
* OpenAPI specification
* API integration tests

Initial API

```
GET    /api/v1/vaults
POST   /api/v1/vaults

GET    /api/v1/notes
POST   /api/v1/notes

GET    /api/v1/notes/{id}
PUT    /api/v1/notes/{id}
DELETE /api/v1/notes/{id}

GET    /api/v1/search

POST   /api/v1/attachments

GET    /api/v1/tags
```

Mutating operations should use revision preconditions.

Milestone M2: Functional backend API

### Phase 3 — Web Application

Duration: 4 weeks

Deliverables

* Authentication UI
* Notebook navigation
* Note listing
* Markdown editor
* Live preview
* Tags
* Search
* Attachments
* Favorites
* Settings
* Responsive design

UI Layout

```
┌──────────────────────────────────────────────────────┐
│ OpenNote                            Search    User   │
├────────────┬─────────────────┬───────────────────────┤
│            │                 │                       │
│ Navigation │ Note List       │ Note Editor           │
│            │                 │                       │
│ Inbox      │ Project A       │ # Project A           │
│ Notes      │ Project B       │                       │
│ Favorites  │ Meeting Notes   │ Markdown content      │
│ Tags       │ Research        │                       │
│            │                 │                       │
│ Notebooks  │                 │                       │
│            │                 │                       │
├────────────┴─────────────────┴───────────────────────┤
│ Status: Synced                                       │
└──────────────────────────────────────────────────────┘
```

Milestone M3: Usable web application

### Phase 4 — macOS and iOS Applications

Duration: 5 weeks

Deliverables

* Shared Swift package
* macOS application
* iPhone application
* iPadOS layout
* Note editing
* Notebook navigation
* Local SQLite cache
* Attachment handling
* Offline editing
* Authentication
* Native search interface

Platform-specific features

macOS

* Keyboard shortcuts
* Menu bar integration
* Drag and drop
* Finder integration
* Multiple windows

iOS

* Share Sheet
* Quick capture
* Camera attachments
* Native notifications

iPadOS

* Split view
* Keyboard support
* Apple Pencil-compatible interactions

Milestone M4: Native applications functional

### Phase 5 — Synchronization

Duration: 4 weeks

Deliverables

* Sync protocol
* Incremental updates
* Offline change queue
* Conflict detection
* Conflict resolution
* Attachment synchronization
* Deleted-file propagation
* Device registration
* Version history
* Sync status interface

Acceptance Criteria

A note edited offline on an iPhone must synchronize correctly when the device reconnects.

A simultaneous conflicting edit on macOS must not be silently overwritten.

Direct changes through Obsidian must propagate to OpenNote clients.

Milestone M5: Reliable multi-device synchronization

At this point, the application should be suitable for controlled daily use.

### Phase 6 — Productivity Features

Duration: 4 weeks

Deliverables

* Tasks
* Reminders
* Recurring tasks
* Calendar integration
* Web clipping
* Templates
* Document scanning
* OCR
* Saved searches
* Backlinks

Acceptance Criteria

Tasks embedded in Markdown must appear in the centralized task view.

Task updates must remain consistent between the task view and the original note.

Milestone M6: Evernote-style productivity features

### Phase 7 — AI Integration

Duration: 4 weeks

Deliverables

* Local AI provider integration
* Embedding pipeline
* Semantic search
* AI Assistant
* Automatic tagging
* Note summarization
* Meeting transcription
* AI-generated action items
* Source citations

Acceptance Criteria

* AI services can be disabled.
* Notes remain accessible without AI.
* Search answers reference source notes.
* AI indexing updates after note changes.
* Unauthorized vault content is excluded.
* AI operations do not modify notes without user approval.

Milestone M7: AI-enabled knowledge platform

### Phase 8 — Production Hardening

Duration: 3 weeks

Deliverables

* Performance optimization
* Security testing
* Accessibility review
* Backup and restore
* Disaster recovery testing
* OpenShift deployment
* Documentation
* Installation packages
* Release automation
* Beta testing

Acceptance Criteria

* Successful restore from backup.
* No known critical security vulnerabilities.
* Sync conflict tests pass.
* Offline functionality passes.
* Installation documentation is complete.
* Existing vault compatibility tests pass.

Milestone M8: Production-oriented v1 release

---

## 14. Roadmap Summary

| Phase | Duration | Cumulative | Deliverable |
|---|---|---|---|
| 0. Foundation | 2 weeks | 2 | Development environment |
| 1. Storage | 3 weeks | 5 | Obsidian-compatible vault |
| 2. Backend | 3 weeks | 8 | API |
| 3. Web | 4 weeks | 12 | Web application |
| 4. Apple apps | 5 weeks | 17 | macOS/iOS applications |
| 5. Sync | 4 weeks | 21 | Multi-device sync |
| 6. Productivity | 4 weeks | 25 | Evernote-style features |
| 7. AI | 4 weeks | 29 | AI features |
| 8. Hardening | 3 weeks | 32 | Production release |

Estimated total: 32 weeks sequentially.

Some activities can overlap, potentially reducing elapsed time to approximately 24–28 weeks with a sufficiently staffed team.

The estimates are planning assumptions and should be refined after the initial architecture and synchronization prototypes.

---

## 15. Master AI Coding Prompt

The following prompt is designed for Claude Code or another autonomous development agent.

It defines the architecture, implementation requirements, development rules, and expected deliverables.

### OpenNote — Master Development Instructions

#### ROLE

You are a principal software architect, senior full-stack engineer, Apple platform engineer, DevOps engineer, security engineer, and QA architect.

Your assignment is to design and implement OpenNote, a production-quality, open, self-hosted note-taking and productivity platform inspired by Evernote and using Obsidian-compatible Markdown vaults as its authoritative storage format.

You are responsible for architecture, implementation, testing, documentation, security, deployment, and release readiness.

Do not treat this project as a prototype.

All code must follow professional software engineering standards.

#### 1. PRODUCT OBJECTIVE

Build a modern note-taking and personal knowledge management platform supporting:

* macOS
* iOS
* iPadOS
* Modern web browsers

The application must combine Evernote-style productivity features with Obsidian-compatible storage.

The product must support offline operation, multi-device synchronization, self-hosted deployment, and optional local AI.

Users must retain ownership and portability of their data.

#### 2. MANDATORY ARCHITECTURAL PRINCIPLES

##### 2.1 Local-first

Native applications must operate without network connectivity.

Local modifications must be persisted immediately and synchronized when connectivity returns.

Network failures must never cause loss of note content.

##### 2.2 Obsidian compatibility

Markdown files are authoritative.

Support:

* Standard Markdown
* YAML frontmatter
* Obsidian wiki-links
* Obsidian embeds
* Tags
* Callouts
* Attachments
* Relative links
* Existing folder structures

Preserve unsupported Markdown syntax.

Do not automatically modify existing notes simply because they are opened.

##### 2.3 Storage independence

Do not store authoritative note content exclusively in PostgreSQL or another database.

Indexes and derived metadata must be rebuildable from vault contents.

Use stable identifiers for notes and attachments.

Handle existing files that lack identifiers.

##### 2.4 Self-hosted architecture

The backend must run in Linux containers.

Prefer Red Hat Universal Base Images.

Support:

* Docker Compose
* Podman
* Kubernetes
* OpenShift

Do not require privileged containers.

##### 2.5 Security by design

Implement authentication, authorization, secure session management, input validation, and safe file operations.

Use least-privilege access.

Never commit secrets.

##### 2.6 API-first

All clients must use a documented and versioned backend API.

Generate OpenAPI specifications.

Generate typed API clients where practical.

Avoid duplicating business rules between applications.

##### 2.7 Modular architecture

Start with a modular monolith.

Use explicit module boundaries.

Avoid premature microservices.

AI inference and asynchronous workers may run separately.

#### 3. REQUIRED TECHNOLOGY STACK

Backend

* Python 3.13 or newer supported version
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic
* PostgreSQL
* pgvector
* Redis-backed background jobs
* pytest
* OpenTelemetry

Web

* React
* TypeScript
* Vite
* Tailwind CSS
* shadcn/ui
* TipTap or another suitable editor framework
* TanStack Query
* IndexedDB
* Playwright
* Vitest

Apple

* Swift
* SwiftUI
* Swift Package Manager
* SQLite
* URLSession
* Keychain
* BackgroundTasks
* VisionKit
* WidgetKit

AI

* Ollama or llama.cpp
* Local embedding models
* pgvector
* faster-whisper
* Configurable AI provider abstraction

Infrastructure

* Red Hat UBI
* Docker Compose
* Podman
* Kubernetes
* OpenShift
* Helm
* GitHub Actions or equivalent CI/CD

Alternative technologies require a documented architectural decision explaining the benefits and trade-offs.

#### 4. REPOSITORY STRUCTURE

Create a monorepo:

```
opennote/ CLAUDE.md README.md LICENSE

backend/
    app/
        api/
        auth/
        vaults/
        notes/
        attachments/
        search/
        sync/
        tasks/
        calendar/
        ai/
        workers/
    migrations/
    tests/
    requirements.txt
    pyproject.toml

web/
    src/
    public/
    tests/
    package.json

apple/
    Apps/
        macOS/
        iOS/
    Packages/
        OpenNoteCore/
        OpenNoteAPI/
        OpenNoteStorage/
        OpenNoteSync/
        OpenNoteEditor/
    Tests/

infrastructure/
    compose/
    containers/
    kubernetes/
    helm/
    openshift/

docs/
    architecture/
    api/
    development/
    operations/
    security/
    superpowers/
        specs/
        plans/

scripts/
tests/
    integration/
    e2e/
    compatibility/
    performance/
```

#### 5. DEVELOPMENT ENVIRONMENT

All Python development must use a repository-local virtual environment.

Use:

```
.venv/bin/python .venv/bin/pip .venv/bin/pytest
```

Never install project Python dependencies globally.

Maintain pinned dependencies and lock files where supported.

Provide reproducible development environments.

Use formatting, linting, type checking, and security scanning.

#### 6. DEVELOPMENT WORKFLOW

Use feature branches and isolated worktrees.

Feature worktrees must be created under:

```
.worktrees///
```

All significant features require:

1. Requirements analysis
2. Design specification
3. Implementation plan
4. Test plan
5. Implementation
6. Automated testing
7. Documentation
8. Review
9. Squash merge into main

Store design specifications in:

```
docs/superpowers/specs/YYYY-MM-DD--design.md
```

Store implementation plans in:

```
docs/superpowers/plans/YYYY-MM-DD--plan.md
```

Never bypass failing tests.

Never disable security controls merely to make development easier.

#### 7. IMPLEMENTATION PHASES

Implement the following phases in order.

Phase 0 — Foundation

Create:

* Repository structure
* Development environment
* CI/CD
* Architecture documentation
* Container definitions
* Database configuration
* Initial Apple projects
* Initial web project
* Security baseline

Phase 1 — Storage

Implement:

* Vault discovery
* Vault creation
* Markdown parsing
* Frontmatter parsing
* Note identity
* File operations
* Folder operations
* Attachment handling
* File-system monitoring
* External modification detection

Preserve Obsidian compatibility.

Phase 2 — Backend API

Implement:

* Authentication
* Vault endpoints
* Note endpoints
* Search endpoints
* Attachment endpoints
* Tag endpoints
* API documentation
* Integration tests

All modifying endpoints must support concurrency protection.

Phase 3 — Web Application

Implement:

* Authentication
* Three-pane layout
* Notebook navigation
* Note listing
* Markdown editor
* Search
* Tags
* Attachments
* Settings
* Responsive layouts

Phase 4 — Native Apple Applications

Implement:

* Shared Swift packages
* macOS application
* iOS application
* iPadOS interface
* Local persistence
* Offline editing
* Attachment support
* Native platform integration

Phase 5 — Synchronization

Implement:

* Device registration
* Revision tracking
* Incremental synchronization
* Offline operation queue
* Conflict detection
* Three-way merge where safe
* Conflict preservation
* Attachment synchronization
* Tombstones
* Version history
* Recovery procedures

Never silently overwrite conflicting edits.

Phase 6 — Productivity

Implement:

* Tasks
* Recurring tasks
* Reminders
* Calendar integration
* Web clipping
* Templates
* OCR
* Document scanning
* Backlinks
* Saved searches

Phase 7 — AI

Implement:

* AI provider abstraction
* Local inference integration
* Embedding generation
* Semantic search
* AI Assistant
* Summarization
* Automatic tagging
* Transcription
* Meeting notes
* Action-item extraction

AI must remain optional.

AI must not modify user content without authorization.

Phase 8 — Production

Implement:

* Performance testing
* Security validation
* Backup and restore
* Disaster recovery
* Container hardening
* OpenShift deployment
* Documentation
* Release packaging
* Automated release pipelines

#### 8. DATA MODEL REQUIREMENTS

Notes must use Markdown.

Metadata should use YAML frontmatter.

Application-specific metadata must be namespaced.

Support stable note identity independently of file paths.

Support direct modifications from Obsidian.

Do not require proprietary conversion.

Do not store device-specific state inside Markdown files.

#### 9. SYNCHRONIZATION REQUIREMENTS

Implement revision-based synchronization.

Every mutation must be conditional on the expected revision.

Use content hashes to detect changes.

Preserve conflicting versions.

Support interrupted and resumed synchronization.

Use durable queues for offline changes.

Support safe file moves and deletions.

Prevent synchronization loops.

Test simultaneous editing from multiple devices.

Do not rely on timestamps alone to determine authoritative content.

#### 10. EDITOR REQUIREMENTS

Support:

* Markdown editing
* Live preview
* Headings
* Lists
* Checkboxes
* Tables
* Links
* Images
* Attachments
* Code blocks
* Syntax highlighting
* Wiki-links
* Callouts
* Frontmatter

Preserve unsupported syntax during round-trip conversion.

Maintain compatibility tests against representative Obsidian vaults.

#### 11. SEARCH REQUIREMENTS

Implement:

* Full-text search
* Title search
* Tag filtering
* Notebook filtering
* Date filtering
* Attachment search
* Saved searches
* Semantic search

Search must respect vault permissions.

Search indexes must be rebuildable.

#### 12. AI REQUIREMENTS

AI functionality must be optional and disabled by default until configured.

Support local inference.

External AI providers must be opt-in.

Do not transmit private note content to external services without explicit configuration and authorization.

AI-generated answers must reference their source notes.

Treat retrieved note content as untrusted input.

Prevent note content from overriding system instructions.

Provide configurable model selection.

#### 13. QUALITY REQUIREMENTS

Every module must include automated tests.

Require:

* Unit tests
* Integration tests
* API contract tests
* UI tests
* Synchronization tests
* Obsidian compatibility tests
* Security tests
* Performance tests

Use coverage targets appropriate to each subsystem.

Critical storage and synchronization paths require especially comprehensive testing.

Do not optimize for coverage percentages at the expense of meaningful assertions.

#### 14. PERFORMANCE TARGETS

Use these initial performance objectives:

* Application startup: under 3 seconds on reference hardware
* Note opening: under 200 ms for cached notes
* Search response: under 500 ms for common queries
* Local save: under 100 ms for ordinary notes
* Initial support for vaults containing 100,000 notes
* Background indexing without blocking editing
* Incremental synchronization rather than full vault transfers

Benchmark against documented reference hardware.

Treat these as targets to validate, not guaranteed performance.

#### 15. SECURITY REQUIREMENTS

Implement:

* Authentication
* Authorization
* Secure token storage
* TLS
* Audit logging
* Rate limiting
* Input validation
* Secure attachment handling
* Path traversal prevention
* Dependency scanning
* Container scanning
* Backup encryption

Document the security model.

Do not claim end-to-end encryption unless it is actually implemented and verified.

#### 16. DOCUMENTATION REQUIREMENTS

Maintain:

* Architecture overview
* Architecture decision records
* API documentation
* Developer setup
* Deployment instructions
* Backup procedures
* Restore procedures
* Security documentation
* User documentation
* Release notes

Documentation must evolve with implementation.

#### 17. ACCEPTANCE CRITERIA

The application is ready for release only when:

1. Existing Obsidian vaults can be opened safely.
2. Markdown remains compatible with Obsidian.
3. macOS, iOS, iPadOS, and web clients function.
4. Offline editing works.
5. Synchronization preserves user data.
6. Conflicts are detected and recoverable.
7. Attachments synchronize correctly.
8. Search operates reliably.
9. Authentication and authorization are enforced.
10. AI can be disabled without affecting core functionality.
11. Backup and restore are verified.
12. Container deployment works.
13. Automated tests pass.
14. Documentation is complete.
15. No known critical security vulnerabilities remain.

#### 18. AUTONOMY AND EXECUTION RULES

Work autonomously within the development environment.

You may:

* Create development branches
* Create worktrees
* Implement features
* Refactor code
* Run tests
* Install dependencies inside approved project environments
* Build development containers
* Update documentation
* Commit development changes

Do not request approval for routine development activities.

However, require explicit approval before:

* Deleting production data
* Changing production infrastructure
* Accessing external production accounts
* Publishing applications
* Incurring paid service charges
* Making irreversible migrations
* Removing security controls

Do not claim work is complete without verification.

Do not invent successful test results.

#### 19. IMPLEMENTATION TRACKING

Maintain:

```
docs/IMPLEMENTATION_STATUS.md
```

The file must include:

* Current phase
* Completed features
* Features in progress
* Blocked tasks
* Open architectural decisions
* Test status
* Known defects
* Next planned work

Also maintain:

```
docs/ROADMAP.md
```

Each roadmap item must have:

* Identifier
* Description
* Dependencies
* Priority
* Acceptance criteria
* Status

Use the following statuses:

* NOT_STARTED
* IN_PROGRESS
* BLOCKED
* TESTING
* COMPLETED

#### 20. INITIAL EXECUTION INSTRUCTIONS

Begin by performing the following actions:

1. Analyze all requirements in this document.
2. Identify architectural risks and unresolved decisions.
3. Produce a complete architecture specification.
4. Produce an implementation roadmap.
5. Define the repository structure.
6. Create architecture decision records.
7. Define the API and storage contracts.
8. Design the synchronization protocol.
9. Define the testing strategy.
10. Create the initial development environment.
11. Implement Phase 0.
12. Run all applicable tests.
13. Update implementation tracking.
14. Proceed to Phase 1 when Phase 0 acceptance criteria are met.

Do not implement advanced features before their foundational dependencies are ready.

Prioritize data integrity, reliability, security, and maintainability over rapid feature accumulation.

The final product must be a maintainable, production-quality application rather than a demonstration.

---

## 16. Important Architecture Decisions

Before coding begins, I would explicitly record five architecture decisions.

| Decision | Recommendation | Reason |
|---|---|---|
| Native vs cross-platform Apple UI | SwiftUI | Best Apple integration |
| Storage | Obsidian-compatible vault | Data portability |
| Backend architecture | Modular monolith | Lower complexity |
| Synchronization | Revision-based | Predictable conflict handling |
| AI | Optional local services | Privacy and independence |

There are also three technical issues I would address before committing to the full roadmap.

### A. Markdown compatibility

The most important risk is that rich-text editing may corrupt existing Obsidian Markdown.

I recommend developing an automated compatibility test suite using real-world Markdown examples before implementing the full editor.

### B. Concurrent access to vault files

The backend and Obsidian may modify the same vault simultaneously.

File-system events, atomic writes, revision checking, and conflict handling must be designed together.

For the initial release, the server should be the authoritative synchronization endpoint. Avoid simultaneously synchronizing the same vault through iCloud, Obsidian Sync, and OpenNote.

### C. Web offline support

A web browser cannot access an arbitrary local Obsidian vault in the same way as a native application.

The web client should therefore use IndexedDB for offline storage and synchronize through the backend.

The native macOS and iOS applications can maintain local file-backed vaults where platform permissions allow.

This difference must be reflected in the implementation rather than hidden behind an unrealistic abstraction.

---

## 17. Recommended MVP

Although the full roadmap covers Evernote-style functionality, I recommend establishing a smaller first milestone.

MVP target: A reliable Obsidian-compatible note application on macOS, iOS, and web.

The MVP should contain:

| Feature | MVP |
|---|---|
| Markdown notes | Yes |
| Notebooks/folders | Yes |
| Tags | Yes |
| Attachments | Yes |
| Full-text search | Yes |
| macOS | Yes |
| iOS/iPadOS | Yes |
| Web | Yes |
| Offline editing | Yes |
| Synchronization | Yes |
| Obsidian compatibility | Yes |
| Version history | Basic |
| Tasks | Later |
| Calendar | Later |
| Web clipping | Later |
| AI | Later |
| Collaboration | Later |

The critical achievement is not having the largest number of features.

It is proving that the system can safely store, edit, and synchronize an existing Obsidian vault across multiple platforms.

Once that works reliably, the remaining features can be added incrementally.

---

## 18. Final Recommendation

I recommend developing OpenNote as a local-first, Obsidian-compatible productivity platform with Evernote-style functionality, rather than building an Evernote clone.

The distinction is important.

Evernote provides a strong model for capture, organization, search, tasks, and productivity. Obsidian provides a strong model for user-owned files, Markdown, links, and knowledge management.

Combining these approaches creates a more flexible system.

### Suggested release strategy

Release 0.1 — Foundation
Backend, Markdown storage, web application, and basic note editing.

Release 0.2 — Native Clients
macOS, iOS, and iPadOS applications with local storage.

Release 0.3 — Synchronization
Reliable offline synchronization and version history.

Release 0.5 — Productivity
Tasks, reminders, calendar, web clipping, OCR, and templates.

Release 0.8 — Intelligence
Local AI, semantic search, meeting transcription, and knowledge management.

Release 1.0 — Production
Security hardening, performance validation, backup and restore, deployment automation, and documentation.

My preferred implementation order is storage engine → synchronization prototype → API → clients → productivity → AI. Although the roadmap groups backend and client development before the complete sync phase, synchronization should be prototyped early because it carries the greatest data-integrity risk.

The master prompt above can be used as the initial development specification for Claude Code. It establishes the architecture, coding standards, implementation phases, acceptance criteria, and development autonomy needed to turn the design into a working application.
