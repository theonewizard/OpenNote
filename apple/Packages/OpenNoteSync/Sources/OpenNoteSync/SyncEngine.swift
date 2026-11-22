import Foundation
import OpenNoteCore
import OpenNoteStorage

public enum SyncEngineError: Error, Equatable {
    /// The file changed while it was read for upload; the next round sends the new bytes.
    case fileChanged(String)
    /// A downloaded blob did not hash to what the server named.
    case hashMismatch(String)
}

/// The Apple client's sync engine for one vault (sync protocol §§2.2, 4, 5, 9).
///
/// Each round scans the vault for changes made outside the engine (the editor, Obsidian,
/// Finder) and turns them into outbox operations, pushes the outbox (blobs first), then pulls
/// changes and writes every pulled revision whose local copy is clean. A dirty file is never
/// touched: its pending operation reaches the server, which merges (clients carry no merge
/// engine). Every step is resumable from the state database and every server call is
/// idempotent, so a crash or a lost response at any point is safe.
///
/// `run()` repeats rounds on start, on each change hint from `GET /events`, 2 s after
/// `notifyLocalChange()`, and every 60 s; local editing never waits for any of it.
public actor SyncEngine {
    static let chunkBytes = 8 * 1024 * 1024  // sync protocol §3
    static let batchSize = 100  // sync protocol §5
    static let rejected = "rejected"
    static let restored = "restored"
    static let cursorKey = "sync.cursor"
    static let reconcileKey = "sync.reconcile"

    let local: LocalVault
    let api: any SyncAPI
    let vaultID: String
    let downloads: URL
    /// The tombstone window minus a 7-day margin: older operations are dropped (§5).
    let opLifetime: TimeInterval
    let now: @Sendable () -> Date

    /// The last round's failure; nil after a round that completed.
    public private(set) var lastError: (any Error)?
    private var waiter: CheckedContinuation<Void, Never>?
    private var signalled = false
    private var debounce: Task<Void, Never>?
    private var onRound: (@Sendable ((any Error)?) -> Void)?

    /// `supportDirectory` is the vault's folder outside the vault (Application Support): the
    /// state database, the recovery area and download temp files live there.
    /// `tombstoneRetentionDays` is the server's `OPENNOTE_TOMBSTONE_RETENTION_DAYS`.
    public init(root: URL, supportDirectory: URL, vaultID: String, api: any SyncAPI,
                tombstoneRetentionDays: Int = 90, now: @escaping @Sendable () -> Date = { Date() }) throws {
        self.local = try LocalVault(root: root, supportDirectory: supportDirectory)
        self.api = api
        self.vaultID = vaultID.lowercased()
        self.downloads = supportDirectory.appendingPathComponent("downloads")
        self.opLifetime = TimeInterval(max(tombstoneRetentionDays - 7, 1) * 86_400)
        self.now = now
    }

    var state: StateStore { local.state }

    // MARK: - Loop

    /// Called after every round of `run()` with what stopped it, nil when it completed: the
    /// vault folder may have changed, and the status to show is known.
    public func setOnRound(_ handler: (@Sendable ((any Error)?) -> Void)?) { onRound = handler }

    /// Runs rounds until the task is cancelled. Call it once per engine.
    public func run() async {
        let hints = Task { [api, vaultID] in
            await Self.listen(api: api, vaultID: vaultID) { await self.wake() }
        }
        defer { hints.cancel() }
        var failures = 0
        while !Task.isCancelled {
            do {
                try await sync()
                failures = 0
            } catch {
                if Task.isCancelled { break }
                failures += 1
                lastError = error
            }
            onRound?(lastError)
            // Bounded backoff after failures: 5 s, 10 s, ... up to 5 minutes.
            await wait(seconds: failures == 0 ? 60 : min(300, 5 * pow(2, Double(failures - 1))))
        }
    }

    /// The vault changed locally (an editor save, a file event): sync 2 s after the last call.
    public func notifyLocalChange() {
        debounce?.cancel()
        debounce = Task {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            await self.wake()
        }
    }

    /// One round: scan, push, pull.
    public func sync() async throws {
        try dropExpiredOps()
        try scan()
        try await push()
        try await pull()
        lastError = nil
    }

    func wake() {
        if let waiter {
            self.waiter = nil
            waiter.resume()
        } else {
            signalled = true
        }
    }

    private func wait(seconds: Double) async {
        if signalled || Task.isCancelled {
            signalled = false
            return
        }
        let timer = Task {
            do {
                try await Task.sleep(for: .seconds(seconds))
                await self.wake()
            } catch {}
        }
        await withTaskCancellationHandler {
            await withCheckedContinuation { waiter = $0 }
        } onCancel: {
            Task { await self.wake() }
        }
        timer.cancel()
    }

    /// Wakes the loop on `ready` and on every change hint for this vault (§4, R-P5-004),
    /// reconnecting with a bounded backoff when the stream ends or fails.
    static func listen(api: any SyncAPI, vaultID: String, wake: @escaping @Sendable () async -> Void) async {
        var delay = 1.0
        while !Task.isCancelled {
            do {
                for try await hint in try await api.events() {
                    delay = 1
                    switch hint {
                    case let .ready(vaults) where vaults.contains(where: { $0.lowercased() == vaultID }):
                        await wake()
                    case let .change(id, _) where id.lowercased() == vaultID:
                        await wake()
                    default:
                        break
                    }
                }
            } catch {}
            try? await Task.sleep(for: .seconds(delay))
            delay = min(delay * 2, 60)
        }
    }

    // MARK: - Flags

    /// Files the user should see: `rejected` (with the server's reason in `note`) and `restored`.
    public func flaggedFiles() throws -> [SyncFile] {
        try state.syncFiles().filter { $0.flag != nil }
    }

    /// Clears a file's flag; a rejected file is pushed again on the next round.
    public func clearFlag(_ fileID: String) throws {
        guard var row = try state.syncFile(fileID) else { return }
        row.flag = nil
        row.note = nil
        try state.save(row)
    }

    // MARK: - Outbox expiry (§5)

    func dropExpiredOps() throws {
        let cutoff = Int64(now().timeIntervalSince1970 - opLifetime)
        let expired = try state.outbox().filter { $0.createdAt < cutoff }
        guard !expired.isEmpty else { return }
        try state.transaction { () throws(StateError) in
            for op in expired { try state.removeOutbox(op.id) }
            try state.setMeta(Self.reconcileKey, "1")
        }
    }

    // MARK: - Scan (§9: local changes without an outbox operation)

    func scan() throws {
        try local.reconcile()
        let disk = try state.files()
        let rows = try state.syncFiles()
        let pending = Set(try state.outbox().map(\.fileID))
        let owned = Set(rows.compactMap(\.localPath))
        let unowned = disk.values.filter { !owned.contains($0.path) && $0.contentHash != nil }
            .sorted { $0.path.unicodeScalars.lexicographicallyPrecedes($1.path.unicodeScalars) }
        var claimed = Set<String>()

        try state.transaction { () throws(StateError) in
            for var row in rows where !pending.contains(row.fileID) && row.flag != Self.rejected {
                guard let path = row.localPath else {
                    // Deleted here and not acknowledged (its operation was dropped): again.
                    if row.baseRevision > 0 && row.baseHash != nil { try enqueue(.delete, row) }
                    continue
                }
                guard let file = disk[path] else {
                    if row.baseRevision > 0, let base = row.baseHash {
                        // Gone from its path: moved if the same bytes appeared elsewhere.
                        if let target = unowned.first(where: {
                            $0.contentHash == base && $0.kind == row.kind && !claimed.contains($0.path)
                        }) {
                            claimed.insert(target.path)
                            row.localPath = target.path
                            try state.save(row)
                            try enqueue(.move, row, path: target.path)
                        } else {
                            row.localPath = nil
                            try state.save(row)
                            try enqueue(.delete, row)
                        }
                    } else if row.baseRevision == 0 && row.remoteRevision > 0 {
                        row.localPath = nil  // a server file waiting to be written
                        try state.save(row)
                    } else if row.baseRevision == 0 {
                        try state.removeSyncFile(row.fileID)  // never reached the server
                    }
                    continue
                }
                guard let hash = file.contentHash else { continue }
                if row.baseRevision > 0 {
                    if let basePath = row.basePath, basePath != path { try enqueue(.move, row, path: path) }
                    if let base = row.baseHash, base != hash { try enqueue(.update, row, hash: hash) }
                } else if row.remoteRevision == 0 && row.baseHash == nil {
                    try enqueue(.create, row, path: path, hash: hash)
                } else if row.remoteRevision > 0 && row.baseHash != hash {
                    // Edited before the server's file could be written here: a new file.
                    var copy = SyncFile(fileID: UUIDv7.make(at: now()), kind: row.kind, localPath: path)
                    copy.flag = row.flag
                    row.localPath = nil
                    row.baseHash = nil
                    try state.save(row)
                    try state.save(copy)
                    try enqueue(.create, copy, path: path, hash: hash)
                }
            }
            for file in unowned where !claimed.contains(file.path) {
                if var match = rows.first(where: {
                    $0.localPath == nil && $0.remoteHash != nil && $0.remoteHash == file.contentHash
                        && $0.remotePath == file.path && !pending.contains($0.fileID)
                }) {
                    // The server's file is already here (written by a reconcile or by hand).
                    match.localPath = file.path
                    match.baseRevision = match.remoteRevision
                    match.baseHash = match.remoteHash
                    match.basePath = match.remotePath
                    try state.save(match)
                    continue
                }
                let row = SyncFile(fileID: UUIDv7.make(at: now()), kind: file.kind, localPath: file.path)
                try state.save(row)
                try enqueue(.create, row, path: file.path, hash: file.contentHash)
            }
        }
    }

    private func enqueue(_ kind: OutboxOp.Kind, _ row: SyncFile, path: String? = nil,
                         hash: String? = nil) throws(StateError) {
        let date = now()
        try state.enqueue(OutboxOp(clientOpID: UUIDv7.make(at: date), fileID: row.fileID, op: kind, path: path,
                                   kind: row.kind, baseRevision: row.baseRevision, contentHash: hash,
                                   createdAt: Int64(date.timeIntervalSince1970)))
    }

    // MARK: - Push (§5)

    func push() async throws {
        while true {
            let batch = Array(try state.outbox().prefix(Self.batchSize))
            guard !batch.isEmpty else { return }
            var send: [OutboxOp] = []
            var skipped = false
            for var op in batch {
                if op.op == .create || op.op == .update {
                    guard try await prepareContent(&op) else {
                        skipped = true
                        continue
                    }
                }
                if !op.sent {
                    op.sent = true
                    try state.update(op)
                }
                send.append(op)
            }
            if !send.isEmpty {
                let results = try await api.push(send, idempotencyKey: UUIDv7.make(at: now()))
                guard results.count == send.count else {
                    throw SyncAPIError.status(200, "\(results.count) results for \(send.count) operations")
                }
                for (op, result) in zip(send, results) { try await apply(result, to: op) }
            }
            // A skipped operation waits for the next round, which rescans first.
            if skipped || send.isEmpty { return }
        }
    }

    /// Makes sure the server holds the operation's blob. False: not sent this round (the
    /// operation may have been dropped because its file is gone).
    private func prepareContent(_ op: inout OutboxOp) async throws -> Bool {
        let path = try state.syncFile(op.fileID)?.localPath
        guard let path, let file = try state.file(path), let hash = file.contentHash else {
            if op.sent { return true }  // repeat it exactly: the server knows it or rejects it
            try state.removeOutbox(op.id)  // the file is gone; the next scan decides
            return false
        }
        if !op.sent { op.contentHash = hash }
        guard op.contentHash == hash, let sent = op.contentHash else {
            // Sent with bytes that are no longer on disk: fine if the server has them.
            if let sent = op.contentHash, try await api.headBlob(Self.hex(sent)) == .present { return true }
            try state.removeOutbox(op.id)  // never committed (a commit needs its blob)
            return false
        }
        do {
            try await upload(path, hash: sent, size: file.size)
        } catch is VaultError {
            return false
        } catch SyncEngineError.fileChanged {
            return false
        } catch SyncAPIError.status(422, _) {
            return false  // the bytes did not match the hash: changed while uploading
        }
        return true
    }

    /// HEAD, then the missing bytes: whole up to 8 MiB, else in chunks from `Upload-Offset`.
    private func upload(_ path: String, hash: String, size: Int64) async throws {
        let hex = Self.hex(hash)
        guard case var .missing(offset) = try await api.headBlob(hex) else { return }
        if size <= Int64(Self.chunkBytes) {
            let data = try local.vault.read(path)
            guard ContentHash.sha256(data) == hash else { throw SyncEngineError.fileChanged(path) }
            _ = try await api.putBlob(hex, data, range: nil)
            return
        }
        for _ in 0..<(size / Int64(Self.chunkBytes) + 3) {
            let data = try local.vault.read(path, offset: UInt64(offset), count: Self.chunkBytes)
            guard !data.isEmpty else { break }
            let range = BlobRange(first: offset, last: offset + Int64(data.count) - 1, total: size)
            switch try await api.putBlob(hex, data, range: range) {
            case .stored: return
            case let .continueAt(next): offset = next
            }
        }
        throw SyncEngineError.fileChanged(path)
    }

    func apply(_ result: PushOutcome, to op: OutboxOp) async throws {
        let status = result.status == .duplicate ? Self.original(of: result, for: op) : result.status
        switch status {
        case .applied, .duplicate:
            try state.transaction { () throws(StateError) in
                try state.removeOutbox(op.id)
                guard var row = try state.syncFile(op.fileID), let revision = result.revision else { return }
                row.baseRevision = revision
                row.baseHash = op.op == .delete ? nil : result.contentHash
                row.basePath = result.path ?? row.basePath
                try state.save(row)
            }
        case .merged:
            try state.removeOutbox(op.id)
            guard var row = try state.syncFile(op.fileID), let revision = result.revision else { return }
            let pushed = op.op == .create || op.op == .update ? op.contentHash : row.baseHash
            let current = try row.localPath.flatMap { try state.file($0)?.contentHash }
            if current == pushed {
                // Still what was pushed: write the merged result.
                row.baseHash = pushed
                try await materialize(row, revision: revision, hash: result.contentHash,
                                      path: result.path ?? row.localPath)
            } else {
                // Edited again meanwhile: stays dirty and is pushed on top of the merge.
                row.baseRevision = revision
                row.baseHash = result.contentHash
                row.basePath = result.path ?? row.basePath
                try state.save(row)
            }
        case .conflict:
            try conflict(result, op)
        case .rejected:
            try state.transaction { () throws(StateError) in
                try state.removeOutbox(op.id)
                guard var row = try state.syncFile(op.fileID) else { return }
                let type = result.problemType ?? ""
                if op.op == .delete && type.hasSuffix("delete-superseded") {
                    row.baseHash = nil  // edit wins (§6): the pull writes the edited file back
                } else if type.hasSuffix("file-not-found") {
                    // The server forgot the file (its tombstone passed the window).
                    try state.removeSyncFile(row.fileID)
                    if op.op != .delete, let path = row.localPath {
                        try restore(path, kind: row.kind)  // the edit wins, as a new file
                    }
                    return
                } else {
                    row.flag = Self.rejected
                    row.note = result.problemDetail ?? result.problemType
                }
                try state.save(row)
            }
        }
    }

    /// The edit is safe in the conflict copy, which the next pull writes. The original file
    /// takes the server's version: its local copy now counts as clean at the pushed bytes.
    private func conflict(_ result: PushOutcome, _ op: OutboxOp) throws {
        try state.transaction { () throws(StateError) in
            try state.removeOutbox(op.id)
            guard op.op == .create else {
                guard var row = try state.syncFile(op.fileID) else { return }
                row.baseHash = op.contentHash
                try state.save(row)
                return
            }
            // A create on a taken path: the path belongs to the server's original file.
            try state.removeSyncFile(op.fileID)
            guard let original = result.originalFileID, let path = op.path else { return }
            var row = try state.syncFile(original) ?? SyncFile(fileID: original, kind: op.kind, localPath: nil)
            if row.localPath == nil {
                row.localPath = path
                row.baseHash = op.contentHash
                try state.save(row)
            }
        }
    }

    /// What a `duplicate` first was; the server stores the original fields (§5).
    static func original(of result: PushOutcome, for op: OutboxOp) -> PushOutcome.Status {
        if result.originalFileID != nil { return .conflict }
        if result.revision == nil { return .rejected }
        switch op.op {
        case .create, .update: return result.contentHash == op.contentHash ? .applied : .merged
        case .move: return result.path == op.path ? .applied : .merged
        case .delete: return .applied
        }
    }

    // MARK: - Pull (§4)

    func pull() async throws {
        if try state.meta(Self.reconcileKey) == "1" { try await reconcile() }
        while true {
            let page: ChangesPage
            do {
                page = try await api.changes(after: try state.meta(Self.cursorKey))
            } catch SyncAPIError.cursorExpired {
                try await reconcile()
                continue
            }
            try state.transaction { () throws(StateError) in
                for entry in page.entries { try record(entry) }
                try state.setMeta(Self.cursorKey, page.nextCursor)
            }
            if !page.hasMore { break }
        }
        try await settleAll()
    }

    /// Notes the server's newest state of a file; `settleAll` writes it once the copy is clean.
    private func record(_ entry: RemoteEntry) throws(StateError) {
        guard let kind = FileKind(rawValue: entry.kind), kind == .note || kind == .attachment else { return }
        var row = try state.syncFile(entry.fileID) ?? SyncFile(fileID: entry.fileID, kind: kind, localPath: nil)
        guard entry.revision > row.remoteRevision else { return }
        row.remoteRevision = entry.revision
        row.remoteHash = entry.deleted ? nil : entry.contentHash
        row.remotePath = entry.path
        try state.save(row)
    }

    func settleAll() async throws {
        let pending = Set(try state.outbox().map(\.fileID))
        for row in try state.syncFiles() where row.remoteRevision > row.baseRevision {
            guard !pending.contains(row.fileID), row.flag != Self.rejected else { continue }
            let current = try row.localPath.flatMap { try state.file($0)?.contentHash }
            if let path = row.localPath, path == row.remotePath, current != nil, current == row.remoteHash {
                var same = row  // already the server's bytes
                same.baseRevision = row.remoteRevision
                same.baseHash = row.remoteHash
                same.basePath = path
                try state.save(same)
                continue
            }
            let clean = row.localPath == nil ? row.baseHash == nil || row.baseRevision == 0 : current == row.baseHash
            guard clean else { continue }  // dirty: the pending operation is merged on push
            try await materialize(row, revision: row.remoteRevision, hash: row.remoteHash,
                                  path: row.remotePath ?? row.localPath)
        }
    }

    /// Writes a server revision to disk (moves, renames and tombstones included) and makes it
    /// the base. A file that changed on disk meanwhile, or a path that is taken, is left as it
    /// is for a later round: nothing is ever overwritten that was not seen (storage contract §4).
    private func materialize(_ row: SyncFile, revision: Int64, hash: String?, path: String?) async throws {
        var row = row
        do {
            if let hash, let path {
                if row.localPath == path {
                    if try state.file(path)?.contentHash != hash {
                        let data = try await fetch(hash)
                        try local.save(path, data)
                    }
                } else {
                    let data = try await fetch(hash)
                    try local.create(path, data)
                    let old = row.localPath
                    row.localPath = path
                    try base(&row, revision, hash, path)
                    if let old { try? local.delete(old) }  // edited meanwhile: it stays, and is pushed as new
                    return
                }
            } else if let old = row.localPath {
                try local.delete(old)  // into the recovery area, never unlinked
                row.localPath = nil
            }
        } catch is VaultError {
            return
        }
        try base(&row, revision, hash, path)
    }

    private func base(_ row: inout SyncFile, _ revision: Int64, _ hash: String?, _ path: String?) throws {
        row.baseRevision = revision
        row.baseHash = hash
        row.basePath = path
        try state.save(row)
    }

    /// Downloads a blob to a temp file outside the vault, checks its hash and maps it.
    private func fetch(_ hash: String) async throws -> Data {
        try FileManager.default.createDirectory(at: downloads, withIntermediateDirectories: true)
        let file = downloads.appendingPathComponent(UUIDv7.make(at: now()))
        defer { try? FileManager.default.removeItem(at: file) }
        try await api.downloadBlob(Self.hex(hash), to: file)
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        guard try ContentHash.sha256(reading: handle) == hash else { throw SyncEngineError.hashMismatch(hash) }
        return try Data(contentsOf: file, options: .alwaysMapped)
    }

    // MARK: - Full reconcile (§4, on 410 or after dropped operations)

    func reconcile() async throws {
        var entries: [RemoteEntry] = []
        var page: String?
        var cursor = ""
        repeat {
            let snapshot = try await api.snapshot(page: page)
            entries += snapshot.entries
            cursor = snapshot.cursor
            page = snapshot.nextPage
        } while page != nil
        try local.reconcile()
        let disk = try state.files()
        let live = Set(entries.map(\.fileID))
        let pending = Set(try state.outbox().map(\.fileID))
        try state.transaction { () throws(StateError) in
            for entry in entries { try record(entry) }
            for var row in try state.syncFiles() where !live.contains(row.fileID) && row.baseRevision > 0 {
                guard !pending.contains(row.fileID), row.flag != Self.rejected else { continue }
                // The server forgot the file: its tombstone passed the retention window.
                guard let path = row.localPath, row.baseHash != nil else {
                    try state.removeSyncFile(row.fileID)
                    continue
                }
                if disk[path]?.contentHash == row.baseHash {
                    row.remoteRevision = row.baseRevision + 1  // a tombstone for settleAll
                    row.remoteHash = nil
                    row.remotePath = path
                    try state.save(row)
                } else {
                    try state.removeSyncFile(row.fileID)
                    try restore(path, kind: row.kind)  // edited here: the edit wins (§4)
                }
            }
            try state.setMeta(Self.cursorKey, cursor)
            try state.setMeta(Self.reconcileKey, "0")
        }
    }

    /// A local file whose server file is gone becomes a new file, flagged `restored`; the
    /// next scan pushes it as a `create`.
    private func restore(_ path: String, kind: FileKind) throws(StateError) {
        var restored = SyncFile(fileID: UUIDv7.make(at: now()), kind: kind, localPath: path)
        restored.flag = Self.restored
        try state.save(restored)
    }

    static func hex(_ hash: String) -> String {
        hash.hasPrefix("sha256:") ? String(hash.dropFirst(7)) : hash
    }
}
