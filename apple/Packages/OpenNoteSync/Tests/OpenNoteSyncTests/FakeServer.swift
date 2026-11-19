import Foundation
import OpenNoteCore
import OpenNoteStorage
@testable import OpenNoteSync

/// An in-memory sync server with the protocol's rules, small enough to read: revisions per
/// file, a seq log, stored operation results, content-addressed blobs with resumable uploads.
actor FakeServer: SyncAPI {
    struct File {
        var revision: Int64
        var path: String
        var kind: String
        var hash: String?
        var history: [Int64: String?] = [:]
    }

    var files: [String: File] = [:]
    var log: [RemoteEntry] = []
    var blobs: [String: Data] = [:]
    var partial: [String: Data] = [:]
    var results: [String: PushOutcome] = [:]
    /// Cursors below this seq get 410.
    var horizon: Int64 = 0
    var pageSize = 500
    /// Merges theirs and ours for an update on an old base; nil makes a conflict copy.
    var merge: (@Sendable (Data, Data) -> Data?)?
    /// Paths containing this are rejected, like a path rule.
    var rejectPathsContaining = "\u{0}"
    /// Throws after storing the next chunk, as if the connection dropped before the answer.
    var dropAfterNextChunk = false
    /// Fails every push before it reaches the server, like an outage.
    var failPushes = false
    var attempted: [[OutboxOp]] = []
    var pushed: [[OutboxOp]] = []
    var puts: [BlobRange?] = []
    var hints: AsyncThrowingStream<SyncHint, any Error>.Continuation?

    var seq: Int64 { log.last?.seq ?? 0 }

    // MARK: Test helpers

    func seed(_ path: String, _ text: String) -> String {
        let id = UUIDv7.make()
        let data = Data(text.utf8)
        blobs[Self.hex(data)] = data
        commit(id, File(revision: 1, path: path, kind: "note", hash: ContentHash.sha256(data)), op: "create")
        return id
    }

    func edit(_ id: String, _ text: String) {
        let data = Data(text.utf8)
        blobs[Self.hex(data)] = data
        var file = files[id]!
        file.revision += 1
        file.hash = ContentHash.sha256(data)
        commit(id, file, op: "update")
    }

    func remove(_ id: String) {
        var file = files[id]!
        file.revision += 1
        file.hash = nil
        commit(id, file, op: "delete")
    }

    /// Retention forgot this file's tombstone: cursors before it expire.
    func forget(_ id: String) {
        files[id] = nil
        horizon = seq
    }

    func text(_ id: String) -> String? {
        files[id]?.hash.flatMap { blobs[SyncEngine.hex($0)] }.map { String(decoding: $0, as: UTF8.self) }
    }

    func live() -> [String: String] {
        var out: [String: String] = [:]
        for (id, file) in files where file.hash != nil { out[file.path] = text(id) }
        return out
    }

    func set(merge: (@Sendable (Data, Data) -> Data?)?) { self.merge = merge }
    func set(rejectPathsContaining value: String) { rejectPathsContaining = value }
    func set(dropAfterNextChunk value: Bool) { dropAfterNextChunk = value }
    func set(pageSize value: Int) { pageSize = value }
    func set(failPushes value: Bool) { failPushes = value }
    func hint(_ hint: SyncHint) { hints?.yield(hint) }
    func endHints() { hints?.finish() }

    static func hex(_ data: Data) -> String { SyncEngine.hex(ContentHash.sha256(data)) }

    private func commit(_ id: String, _ file: File, op: String) {
        var file = file
        file.history[file.revision] = file.hash
        files[id] = file
        log.append(RemoteEntry(seq: seq + 1, fileID: id, revision: file.revision, path: file.path, kind: file.kind,
                               contentHash: file.hash, size: Int64(file.hash.flatMap { blobs[SyncEngine.hex($0)] }?.count ?? 0),
                               deleted: file.hash == nil))
    }

    // MARK: SyncAPI

    func headBlob(_ sha256: String) async throws -> BlobStatus {
        blobs[sha256] != nil ? .present : .missing(uploadOffset: Int64(partial[sha256]?.count ?? 0))
    }

    func putBlob(_ sha256: String, _ data: Data, range: BlobRange?) async throws -> ChunkResult {
        puts.append(range)
        guard let range else {
            guard Self.hex(data) == sha256 else { throw SyncAPIError.status(422, nil) }
            blobs[sha256] = data
            return .stored
        }
        let have = partial[sha256] ?? Data()
        guard range.first == Int64(have.count) else { return .continueAt(Int64(have.count)) }
        let now = have + data
        if Int64(now.count) == range.total {
            partial[sha256] = nil
            guard Self.hex(now) == sha256 else { throw SyncAPIError.status(422, nil) }
            blobs[sha256] = now
            return .stored
        }
        partial[sha256] = now
        if dropAfterNextChunk {
            dropAfterNextChunk = false
            throw URLError(.networkConnectionLost)
        }
        return .continueAt(Int64(now.count))
    }

    func downloadBlob(_ sha256: String, to file: URL) async throws {
        guard let data = blobs[sha256] else { throw SyncAPIError.status(404, nil) }
        try data.write(to: file)
    }

    func changes(after cursor: String?) async throws -> ChangesPage {
        if let cursor, let old = Int64(cursor), old < horizon { throw SyncAPIError.cursorExpired }
        let after = Int64(cursor ?? "0") ?? 0
        let entries = Array(log.filter { $0.seq > after }.prefix(pageSize))
        let next = entries.last?.seq ?? max(after, 0)
        return ChangesPage(entries: entries, nextCursor: String(next), hasMore: log.contains { $0.seq > next })
    }

    func snapshot(page: String?) async throws -> SnapshotPage {
        let live = files.filter { $0.value.hash != nil }.sorted { $0.value.path < $1.value.path }
        let start = Int(page ?? "0") ?? 0
        let slice = live.dropFirst(start).prefix(pageSize)
        let entries = slice.map { id, file in
            RemoteEntry(seq: 0, fileID: id, revision: file.revision, path: file.path, kind: file.kind,
                        contentHash: file.hash, size: 0, deleted: false)
        }
        let more = start + slice.count < live.count
        return SnapshotPage(entries: entries, cursor: String(seq), nextPage: more ? String(start + slice.count) : nil)
    }

    func push(_ ops: [OutboxOp], idempotencyKey: String) async throws -> [PushOutcome] {
        attempted.append(ops)
        if failPushes { throw URLError(.notConnectedToInternet) }
        pushed.append(ops)
        return ops.map { op in
            if var prior = results[op.clientOpID] {
                prior.status = .duplicate
                return prior
            }
            let result = apply(op)
            results[op.clientOpID] = result
            return result
        }
    }

    private func rejected(_ op: OutboxOp, _ slug: String) -> PushOutcome {
        PushOutcome(status: .rejected, fileID: op.fileID, problemType: "https://opennote.example/problems/" + slug,
                    problemDetail: slug)
    }

    private func taken(_ path: String) -> String? {
        files.first { $0.value.hash != nil && $0.value.path.lowercased() == path.lowercased() }?.key
    }

    private func copy(of op: OutboxOp, path: String, hash: String, original: String) -> PushOutcome {
        let name = (path as NSString).deletingPathExtension
        let ext = (path as NSString).pathExtension
        let copyPath = "\(name) (conflict test 2026-11-19).\(ext)"
        let id = UUIDv7.make()
        commit(id, File(revision: 1, path: copyPath, kind: op.kind.rawValue, hash: hash), op: "create")
        return PushOutcome(status: .conflict, fileID: id, revision: 1, contentHash: hash, path: copyPath,
                           problemType: "https://opennote.example/problems/conflict", originalFileID: original)
    }

    private func apply(_ op: OutboxOp) -> PushOutcome {
        if let path = op.path, path.contains(rejectPathsContaining) { return rejected(op, "invalid-path") }
        if let hash = op.contentHash, blobs[SyncEngine.hex(hash)] == nil { return rejected(op, "blob-missing") }
        switch op.op {
        case .create:
            let path = op.path!, hash = op.contentHash!
            if let other = taken(path) { return copy(of: op, path: path, hash: hash, original: other) }
            let file = File(revision: 1, path: path, kind: op.kind.rawValue, hash: hash)
            commit(op.fileID, file, op: "create")
            return PushOutcome(status: .applied, fileID: op.fileID, revision: 1, contentHash: hash, path: path)
        case .update:
            guard var file = files[op.fileID] else { return rejected(op, "file-not-found") }
            let ours = op.contentHash!
            if file.hash == ours {
                return PushOutcome(status: .applied, fileID: op.fileID, revision: file.revision, contentHash: ours,
                                   path: file.path)
            }
            var status = PushOutcome.Status.applied
            var result = ours
            if op.baseRevision < file.revision, let theirs = file.hash {
                let t = blobs[SyncEngine.hex(theirs)]!, o = blobs[SyncEngine.hex(ours)]!
                guard let merged = merge?(t, o) else {
                    return copy(of: op, path: file.path, hash: ours, original: op.fileID)
                }
                result = ContentHash.sha256(merged)
                blobs[SyncEngine.hex(result)] = merged
                status = .merged
            }
            file.revision += 1
            file.hash = result
            commit(op.fileID, file, op: "update")
            return PushOutcome(status: status, fileID: op.fileID, revision: file.revision, contentHash: result,
                               path: file.path)
        case .move:
            guard var file = files[op.fileID] else { return rejected(op, "file-not-found") }
            if let other = taken(op.path!), other != op.fileID { return rejected(op, "path-taken") }
            file.revision += 1
            file.path = op.path!
            commit(op.fileID, file, op: "move")
            return PushOutcome(status: .applied, fileID: op.fileID, revision: file.revision, contentHash: file.hash,
                               path: file.path)
        case .delete:
            guard var file = files[op.fileID] else { return rejected(op, "file-not-found") }
            if op.baseRevision < file.revision, file.history[op.baseRevision] != file.hash {
                return rejected(op, "delete-superseded")
            }
            file.revision += 1
            file.hash = nil
            commit(op.fileID, file, op: "delete")
            return PushOutcome(status: .applied, fileID: op.fileID, revision: file.revision, path: file.path)
        }
    }

    func events() async throws -> AsyncThrowingStream<SyncHint, any Error> {
        let (stream, continuation) = AsyncThrowingStream<SyncHint, any Error>.makeStream()
        hints = continuation
        return stream
    }
}
