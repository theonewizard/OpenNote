import Foundation
import OpenNoteCore

/// One file as the sync engine knows it (sync protocol §2.2), keyed by the server's file id.
///
/// The base is the server revision this device's copy derives from; the remote is the newest
/// revision pulled, which the engine writes to disk once the local copy is clean. A nil hash
/// is a tombstone (or, with revision 0, nothing yet).
public struct SyncFile: Sendable, Equatable {
    public var fileID: String
    public var kind: FileKind
    /// Where the file is in the local vault; nil when it is not on disk.
    public var localPath: String?
    public var baseRevision: Int64 = 0
    public var baseHash: String?
    public var basePath: String?
    public var remoteRevision: Int64 = 0
    public var remoteHash: String?
    public var remotePath: String?
    /// `rejected`: the server refused the last operation (`note` says why); never pushed or
    /// overwritten again until the user clears it. `restored`: edited here after the server
    /// forgot a delete, so pushed as a new file (informational).
    public var flag: String?
    public var note: String?

    public init(fileID: String, kind: FileKind, localPath: String?) {
        self.fileID = fileID
        self.kind = kind
        self.localPath = localPath
    }
}

/// One pending operation of the outbox (sync protocol §3), pushed in `id` order.
public struct OutboxOp: Sendable, Equatable {
    public enum Kind: String, Sendable { case create, update, move, delete }

    public var id: Int64 = 0
    public var clientOpID: String
    public var fileID: String
    public var op: Kind
    /// The path of a `create`, the new path of a `move`.
    public var path: String?
    public var kind: FileKind
    public var baseRevision: Int64
    public var contentHash: String?
    /// Unix seconds; an operation older than the tombstone window minus 7 days is dropped.
    public var createdAt: Int64
    /// Sent at least once: its content hash is then fixed, a retry must repeat it exactly.
    public var sent = false

    public init(clientOpID: String, fileID: String, op: Kind, path: String? = nil, kind: FileKind,
                baseRevision: Int64 = 0, contentHash: String? = nil, createdAt: Int64) {
        self.clientOpID = clientOpID
        self.fileID = fileID
        self.op = op
        self.path = path
        self.kind = kind
        self.baseRevision = baseRevision
        self.contentHash = contentHash
        self.createdAt = createdAt
    }
}

extension StateStore {
    static let syncSchema = """
        CREATE TABLE sync_files (
            file_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            local_path TEXT,
            base_revision INTEGER NOT NULL,
            base_hash TEXT,
            base_path TEXT,
            remote_revision INTEGER NOT NULL,
            remote_hash TEXT,
            remote_path TEXT,
            flag TEXT,
            note TEXT
        );
        CREATE INDEX sync_files_local_path ON sync_files (local_path);
        CREATE TABLE outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_op_id TEXT NOT NULL UNIQUE,
            file_id TEXT NOT NULL,
            op TEXT NOT NULL,
            path TEXT,
            kind TEXT NOT NULL,
            base_revision INTEGER NOT NULL,
            content_hash TEXT,
            created_at INTEGER NOT NULL,
            sent INTEGER NOT NULL
        );
        PRAGMA user_version = 2;
        """

    private static let syncColumns = """
        file_id, kind, local_path, base_revision, base_hash, base_path, remote_revision, remote_hash,
        remote_path, flag, note
        """

    public func syncFiles() throws(StateError) -> [SyncFile] {
        var out: [SyncFile] = []
        try query("SELECT \(Self.syncColumns) FROM sync_files ORDER BY file_id") { out.append($0.syncFile) }
        return out
    }

    public func syncFile(_ fileID: String) throws(StateError) -> SyncFile? {
        var file: SyncFile?
        try query("SELECT \(Self.syncColumns) FROM sync_files WHERE file_id = ?", [.text(fileID)]) { file = $0.syncFile }
        return file
    }

    public func save(_ f: SyncFile) throws(StateError) {
        try run("""
            INSERT OR REPLACE INTO sync_files (\(Self.syncColumns)) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [.text(f.fileID), .text(f.kind.rawValue), .text(f.localPath), .int(f.baseRevision),
                  .text(f.baseHash), .text(f.basePath), .int(f.remoteRevision), .text(f.remoteHash),
                  .text(f.remotePath), .text(f.flag), .text(f.note)])
    }

    public func removeSyncFile(_ fileID: String) throws(StateError) {
        try run("DELETE FROM sync_files WHERE file_id = ?", [.text(fileID)])
    }

    // MARK: - Outbox

    private static let outboxColumns =
        "id, client_op_id, file_id, op, path, kind, base_revision, content_hash, created_at, sent"

    public func outbox() throws(StateError) -> [OutboxOp] {
        var out: [OutboxOp] = []
        try query("SELECT \(Self.outboxColumns) FROM outbox ORDER BY id") { out.append($0.outboxOp) }
        return out
    }

    /// Appends `op`; its `id` is assigned here.
    public func enqueue(_ op: OutboxOp) throws(StateError) {
        try run("""
            INSERT INTO outbox (client_op_id, file_id, op, path, kind, base_revision, content_hash, created_at, sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [.text(op.clientOpID), .text(op.fileID), .text(op.op.rawValue), .text(op.path),
                  .text(op.kind.rawValue), .int(op.baseRevision), .text(op.contentHash), .int(op.createdAt),
                  .int(op.sent ? 1 : 0)])
    }

    /// Stores a refreshed content hash and the sent mark.
    public func update(_ op: OutboxOp) throws(StateError) {
        try run("UPDATE outbox SET content_hash = ?, sent = ? WHERE id = ?",
                [.text(op.contentHash), .int(op.sent ? 1 : 0), .int(op.id)])
    }

    public func removeOutbox(_ id: Int64) throws(StateError) {
        try run("DELETE FROM outbox WHERE id = ?", [.int(id)])
    }
}

extension StateStore.Row {
    var syncFile: SyncFile {
        var f = SyncFile(fileID: text(0)!, kind: FileKind(rawValue: text(1)!) ?? .attachment, localPath: text(2))
        f.baseRevision = int(3)
        f.baseHash = text(4)
        f.basePath = text(5)
        f.remoteRevision = int(6)
        f.remoteHash = text(7)
        f.remotePath = text(8)
        f.flag = text(9)
        f.note = text(10)
        return f
    }

    var outboxOp: OutboxOp {
        var op = OutboxOp(clientOpID: text(1)!, fileID: text(2)!, op: OutboxOp.Kind(rawValue: text(3)!) ?? .update,
                          path: text(4), kind: FileKind(rawValue: text(5)!) ?? .attachment, baseRevision: int(6),
                          contentHash: text(7), createdAt: int(8))
        op.id = int(0)
        op.sent = int(9) != 0
        return op
    }
}
