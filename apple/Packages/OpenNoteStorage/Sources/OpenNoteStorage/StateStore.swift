import CSQLite
import Foundation
import OpenNoteCore

public struct StateError: Error, Equatable, CustomStringConvertible {
    public let code: Int32
    public let message: String
    public var description: String { "SQLite \(code): \(message)" }
}

/// What the last reconciliation changed.
public struct Changes: Sendable, Equatable {
    public var added: [ScannedFile] = []
    public var modified: [ScannedFile] = []
    public var removed: [String] = []
    public var isEmpty: Bool { added.isEmpty && modified.isEmpty && removed.isEmpty }
}

/// The device's local state for one vault, in SQLite outside the vault (storage contract
/// §1.3): what each file looked like at the last scan or OpenNote write. It is a cache: losing
/// it costs one full re-hash of the vault, never data. Sync state (bases, outbox, cursor)
/// joins it with the Swift sync engine (P5-03), as a new `user_version`.
public final class StateStore {
    public static let schemaVersion: Int32 = 1
    private var db: OpaquePointer?

    public init(url: URL) throws(StateError) {
        let flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(url.path, &db, flags, nil) == SQLITE_OK else {
            let error = StateError(code: sqlite3_errcode(db), message: String(cString: sqlite3_errmsg(db)))
            sqlite3_close(db)
            throw error
        }
        try exec("PRAGMA journal_mode = WAL")
        try exec("PRAGMA synchronous = NORMAL")
        let version = try queryInt("PRAGMA user_version")
        guard version <= Self.schemaVersion else {
            throw StateError(code: SQLITE_MISMATCH, message: "state schema \(version) is newer than this app")
        }
        if version < 1 {
            try exec("""
                CREATE TABLE files (
                    path TEXT PRIMARY KEY,
                    path_key TEXT NOT NULL,
                    disk_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    inode INTEGER NOT NULL,
                    content_hash TEXT,
                    path_warning INTEGER NOT NULL
                );
                CREATE INDEX files_path_key ON files (path_key);
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version = 1;
                """)
        }
    }

    deinit { sqlite3_close(db) }

    // MARK: - Files

    private static let columns = "path, disk_name, kind, size, mtime_ns, inode, content_hash, path_warning"

    public func files() throws(StateError) -> [String: ScannedFile] {
        var out: [String: ScannedFile] = [:]
        try query("SELECT \(Self.columns) FROM files") { row in
            let file = row.scannedFile
            out[file.path] = file
        }
        return out
    }

    public func file(_ path: String) throws(StateError) -> ScannedFile? {
        var file: ScannedFile?
        try query("SELECT \(Self.columns) FROM files WHERE path = ?", [.text(path)]) { file = $0.scannedFile }
        return file
    }

    /// Replaces the file table with a scan's result, in one transaction, and says what changed
    /// by content hash. A file whose hash could not be read keeps its old row.
    public func apply(scan: [ScannedFile]) throws(StateError) -> Changes {
        let old = try files()
        var changes = Changes()
        var seen = Set<String>()
        try transaction { () throws(StateError) in
            for file in scan {
                seen.insert(file.path)
                guard let previous = old[file.path] else {
                    changes.added.append(file)
                    try upsert(file)
                    continue
                }
                guard file.contentHash != nil else { continue }
                if previous.contentHash != file.contentHash { changes.modified.append(file) }
                if previous != file { try upsert(file) }
            }
            for path in old.keys.sorted() where !seen.contains(path) {
                changes.removed.append(path)
                try run("DELETE FROM files WHERE path = ?", [.text(path)])
            }
        }
        return changes
    }

    /// Records what OpenNote just wrote, so the next scan does not report it as a change.
    public func record(_ written: WrittenFile, kind: FileKind, diskName: String) throws(StateError) {
        try upsert(ScannedFile(
            path: written.path, diskName: diskName, kind: kind, size: written.size, mtimeNs: written.mtimeNs,
            inode: written.inode, contentHash: written.contentHash,
            pathWarning: !VaultPath.validate(written.path, note: kind == .note).isEmpty))
    }

    public func remove(_ path: String) throws(StateError) {
        try run("DELETE FROM files WHERE path = ?", [.text(path)])
    }

    // MARK: - Meta

    public func meta(_ key: String) throws(StateError) -> String? {
        var value: String?
        try query("SELECT value FROM meta WHERE key = ?", [.text(key)]) { value = $0.text(0) }
        return value
    }

    public func setMeta(_ key: String, _ value: String) throws(StateError) {
        try run("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                [.text(key), .text(value)])
    }

    // MARK: - SQLite

    enum Value {
        case text(String?)
        case int(Int64)
    }

    struct Row {
        let statement: OpaquePointer

        func text(_ i: Int32) -> String? {
            sqlite3_column_type(statement, i) == SQLITE_NULL ? nil : String(cString: sqlite3_column_text(statement, i)!)
        }

        func int(_ i: Int32) -> Int64 { sqlite3_column_int64(statement, i) }

        var scannedFile: ScannedFile {
            ScannedFile(
                path: text(0)!, diskName: text(1)!, kind: FileKind(rawValue: text(2)!) ?? .attachment,
                size: int(3), mtimeNs: int(4), inode: UInt64(bitPattern: int(5)),
                contentHash: text(6), pathWarning: int(7) != 0)
        }
    }

    private func upsert(_ f: ScannedFile) throws(StateError) {
        try run("""
            INSERT INTO files (path, path_key, disk_name, kind, size, mtime_ns, inode, content_hash, path_warning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (path) DO UPDATE SET path_key = excluded.path_key, disk_name = excluded.disk_name,
                kind = excluded.kind, size = excluded.size, mtime_ns = excluded.mtime_ns, inode = excluded.inode,
                content_hash = excluded.content_hash, path_warning = excluded.path_warning
            """, [.text(f.path), .text(VaultPath.casefoldKey(f.path)), .text(f.diskName), .text(f.kind.rawValue),
                  .int(f.size), .int(f.mtimeNs), .int(Int64(bitPattern: f.inode)), .text(f.contentHash),
                  .int(f.pathWarning ? 1 : 0)])
    }

    private func transaction(_ body: () throws(StateError) -> Void) throws(StateError) {
        try exec("BEGIN IMMEDIATE")
        do {
            try body()
            try exec("COMMIT")
        } catch {
            try? exec("ROLLBACK")
            throw error
        }
    }

    private func error() -> StateError {
        StateError(code: sqlite3_errcode(db), message: String(cString: sqlite3_errmsg(db)))
    }

    private func exec(_ sql: String) throws(StateError) {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else { throw error() }
    }

    private func queryInt(_ sql: String) throws(StateError) -> Int32 {
        var value: Int32 = 0
        try query(sql) { value = Int32($0.int(0)) }
        return value
    }

    private func run(_ sql: String, _ values: [Value]) throws(StateError) {
        try query(sql, values) { _ in }
    }

    private func query(_ sql: String, _ values: [Value] = [], _ row: (Row) -> Void) throws(StateError) {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let statement else { throw error() }
        defer { sqlite3_finalize(statement) }
        // SQLITE_TRANSIENT: SQLite copies the bytes before the Swift string goes away.
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        for (index, value) in values.enumerated() {
            let i = Int32(index + 1)
            switch value {
            case let .text(s?): sqlite3_bind_text(statement, i, s, -1, transient)
            case .text(nil): sqlite3_bind_null(statement, i)
            case let .int(n): sqlite3_bind_int64(statement, i, n)
            }
        }
        while true {
            switch sqlite3_step(statement) {
            case SQLITE_ROW: row(Row(statement: statement))
            case SQLITE_DONE: return
            default: throw error()
            }
        }
    }
}
