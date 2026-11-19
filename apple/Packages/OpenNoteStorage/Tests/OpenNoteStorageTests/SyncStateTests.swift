import CSQLite
import Foundation
import OpenNoteCore
import OpenNoteStorage
import Testing

@Suite struct SyncStateTests {
    @Test func syncFilesRoundTrip() throws {
        let box = try Sandbox()
        let state = try box.local().state
        var file = SyncFile(fileID: "f1", kind: .note, localPath: "a.md")
        file.baseRevision = 3
        file.baseHash = "sha256:aa"
        file.basePath = "a.md"
        file.remoteRevision = 4
        file.remotePath = "b.md"
        file.flag = "rejected"
        file.note = "quota"
        try state.save(file)
        #expect(try state.syncFile("f1") == file)
        file.localPath = nil
        try state.save(file)
        #expect(try state.syncFiles() == [file])
        try state.removeSyncFile("f1")
        #expect(try state.syncFiles().isEmpty)
    }

    @Test func outboxKeepsOrderAndUpdates() throws {
        let box = try Sandbox()
        let state = try box.local().state
        try state.enqueue(OutboxOp(clientOpID: "c1", fileID: "f1", op: .create, path: "a.md", kind: .note,
                                   contentHash: "sha256:01", createdAt: 100))
        try state.enqueue(OutboxOp(clientOpID: "c2", fileID: "f1", op: .move, path: "b.md", kind: .note,
                                   baseRevision: 1, createdAt: 101))
        var ops = try state.outbox()
        #expect(ops.map(\.clientOpID) == ["c1", "c2"])
        #expect(ops[1].op == .move && ops[1].path == "b.md" && ops[1].baseRevision == 1 && !ops[1].sent)
        ops[0].contentHash = "sha256:02"
        ops[0].sent = true
        try state.update(ops[0])
        #expect(try state.outbox()[0] == ops[0])
        try state.removeOutbox(ops[0].id)
        #expect(try state.outbox().map(\.clientOpID) == ["c2"])
    }

    @Test func aFailedTransactionWritesNothing() throws {
        let box = try Sandbox()
        let state = try box.local().state
        #expect(throws: StateError.self) {
            try state.transaction { () throws(StateError) in
                try state.save(SyncFile(fileID: "f1", kind: .note, localPath: "a.md"))
                try state.enqueue(OutboxOp(clientOpID: "dup", fileID: "f1", op: .delete, kind: .note, createdAt: 1))
                try state.enqueue(OutboxOp(clientOpID: "dup", fileID: "f1", op: .delete, kind: .note, createdAt: 1))
            }
        }
        #expect(try state.syncFiles().isEmpty)
        #expect(try state.outbox().isEmpty)
    }

    @Test func versionOneDatabasesGainTheSyncTables() throws {
        let box = try Sandbox()
        try FileManager.default.createDirectory(at: box.support, withIntermediateDirectories: true)
        let url = box.support.appendingPathComponent("state.sqlite")
        var db: OpaquePointer?
        #expect(sqlite3_open(url.path, &db) == SQLITE_OK)
        #expect(sqlite3_exec(db, """
            CREATE TABLE files (path TEXT PRIMARY KEY, path_key TEXT NOT NULL, disk_name TEXT NOT NULL,
                kind TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, inode INTEGER NOT NULL,
                content_hash TEXT, path_warning INTEGER NOT NULL);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('cursor', 'kept');
            PRAGMA user_version = 1;
            """, nil, nil, nil) == SQLITE_OK)
        sqlite3_close(db)
        let state = try StateStore(url: url)
        #expect(try state.meta("cursor") == "kept")
        try state.save(SyncFile(fileID: "f1", kind: .attachment, localPath: nil))
        #expect(try state.syncFile("f1")?.kind == .attachment)
    }

    @Test func chunkReadsReturnTheRequestedRange() throws {
        let box = try Sandbox()
        try box.put("big.bin", "0123456789")
        let vault = Vault(root: box.root, recoveryRoot: box.support)
        #expect(try vault.read("big.bin", offset: 3, count: 4) == Data("3456".utf8))
        #expect(try vault.read("big.bin", offset: 8, count: 4) == Data("89".utf8))
    }
}
