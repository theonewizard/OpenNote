import Foundation
import OpenNoteCore
import OpenNoteStorage
@testable import OpenNoteSync
import Synchronization
import Testing

/// A vault folder and its support folder under the temp directory.
final class Box {
    let base = FileManager.default.temporaryDirectory.appendingPathComponent("opennote-sync-\(UUID().uuidString)")
    var root: URL { base.appendingPathComponent("vault") }
    var support: URL { base.appendingPathComponent("support") }

    init() throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    deinit { try? FileManager.default.removeItem(at: base) }

    func put(_ path: String, _ text: String) throws { try put(path, Data(text.utf8)) }

    func put(_ path: String, _ data: Data) throws {
        let url = root.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }

    func text(_ path: String) -> String? {
        (try? Data(contentsOf: root.appendingPathComponent(path))).map { String(decoding: $0, as: UTF8.self) }
    }

    func remove(_ path: String) throws { try FileManager.default.removeItem(at: root.appendingPathComponent(path)) }

    func move(_ from: String, _ to: String) throws {
        let target = root.appendingPathComponent(to)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.moveItem(at: root.appendingPathComponent(from), to: target)
    }

    /// The contents of every file in the recovery area.
    func recovered() -> [String] {
        let recovery = support.appendingPathComponent("recovery")
        guard let walker = FileManager.default.enumerator(at: recovery, includingPropertiesForKeys: nil) else { return [] }
        return walker.compactMap { item in
            guard let url = item as? URL, let data = try? Data(contentsOf: url) else { return nil }
            return String(decoding: data, as: UTF8.self)
        }
    }

    func engine(_ server: FakeServer, clock: Clock = Clock()) throws -> SyncEngine {
        try SyncEngine(root: root, supportDirectory: support, vaultID: "vault", api: server, now: { clock.now })
    }
}

final class Clock: Sendable {
    private let date = Mutex(Date())
    var now: Date { date.withLock { $0 } }
    func advance(days: Double) { date.withLock { $0 += days * 86_400 } }
}

final class Counter: Sendable {
    private let value = Mutex(0)
    var count: Int { value.withLock { $0 } }
    func bump() { value.withLock { $0 += 1 } }
}

@Suite struct SyncEngineTests {
    @Test func firstSyncPushesLocalFilesAndPullsServerFiles() async throws {
        let box = try Box(), server = FakeServer()
        try box.put("a.md", "local")
        _ = await server.seed("b.md", "remote")
        let engine = try box.engine(server)
        try await engine.sync()
        #expect(await server.live() == ["a.md": "local", "b.md": "remote"])
        #expect(box.text("b.md") == "remote")
        let pushes = await server.pushed.count
        try await engine.sync()
        #expect(await server.pushed.count == pushes)  // pulled writes are never pushed back (I5)
    }

    @Test func localEditsArePushedAndServerEditsArePulled() async throws {
        let box = try Box(), server = FakeServer()
        let id = await server.seed("b.md", "remote")
        let engine = try box.engine(server)
        try await engine.sync()
        try box.put("b.md", "mine, longer")
        try await engine.sync()
        #expect(await server.text(id) == "mine, longer")
        await server.edit(id, "theirs")
        try await engine.sync()
        #expect(box.text("b.md") == "theirs")
    }

    @Test func concurrentEditsAreMergedOnTheServerAndWrittenBack() async throws {
        let box = try Box(), server = FakeServer()
        let id = await server.seed("n.md", "base")
        let engine = try box.engine(server)
        try await engine.sync()
        await server.set(merge: { theirs, ours in theirs + Data("\n".utf8) + ours })
        await server.edit(id, "theirs!")
        try box.put("n.md", "ours-local")
        try await engine.sync()
        #expect(await server.text(id) == "theirs!\nours-local")
        #expect(box.text("n.md") == "theirs!\nours-local")
    }

    @Test func conflictingEditsKeepBothVersions() async throws {
        let box = try Box(), server = FakeServer()
        let id = await server.seed("n.md", "base")
        let engine = try box.engine(server)
        try await engine.sync()
        await server.edit(id, "theirs!")
        try box.put("n.md", "ours-local")
        try await engine.sync()
        #expect(box.text("n.md") == "theirs!")
        #expect(box.text("n (conflict test 2026-11-19).md") == "ours-local")
        let pushes = await server.pushed.count
        try await engine.sync()
        #expect(await server.pushed.count == pushes)
    }

    @Test func aCreateOnATakenPathKeepsBothFiles() async throws {
        let box = try Box(), server = FakeServer()
        _ = await server.seed("a.md", "server-version")
        try box.put("a.md", "local-version-x")
        let engine = try box.engine(server)
        try await engine.sync()
        #expect(box.text("a.md") == "server-version")
        #expect(box.text("a (conflict test 2026-11-19).md") == "local-version-x")
    }

    @Test func deletesTravelBothWaysAndPulledOnesGoToRecovery() async throws {
        let box = try Box(), server = FakeServer()
        let a = await server.seed("a.md", "aaa")
        let b = await server.seed("b.md", "bbb")
        let engine = try box.engine(server)
        try await engine.sync()
        try box.remove("a.md")
        await server.remove(b)
        try await engine.sync()
        #expect(await server.files[a]?.hash == nil)
        #expect(box.text("b.md") == nil)
        #expect(box.recovered().contains("bbb"))
    }

    @Test func aRemoteDeleteOfAnEditedFileLosesNothing() async throws {
        let box = try Box(), server = FakeServer()
        let id = await server.seed("a.md", "aaa")
        let engine = try box.engine(server)
        try await engine.sync()
        await server.remove(id)
        try box.put("a.md", "edited here")
        try await engine.sync()
        // Edit wins (§6): the update revives the file, and nothing is moved to recovery.
        #expect(await server.text(id) == "edited here")
        #expect(box.text("a.md") == "edited here")
    }

    @Test func renamesArePushedAsMoves() async throws {
        let box = try Box(), server = FakeServer()
        let id = await server.seed("old.md", "x-content")
        let engine = try box.engine(server)
        try await engine.sync()
        try box.move("old.md", "folder/new.md")
        try await engine.sync()
        #expect(await server.files[id]?.path == "folder/new.md")
        #expect(await server.pushed.last?.map(\.op) == [.move])
        #expect(await server.live().count == 1)
    }

    @Test func rejectedOperationsAreFlaggedAndWaitForTheUser() async throws {
        let box = try Box(), server = FakeServer()
        await server.set(rejectPathsContaining: "bad")
        try box.put("bad.md", "x")
        let engine = try box.engine(server)
        try await engine.sync()
        let flagged = try await engine.flaggedFiles()
        #expect(flagged.map(\.flag) == ["rejected"])
        #expect(flagged.first?.note == "invalid-path")
        let pushes = await server.pushed.count
        try await engine.sync()
        #expect(await server.pushed.count == pushes)
        await server.set(rejectPathsContaining: "\u{0}")
        try await engine.clearFlag(flagged[0].fileID)
        try await engine.sync()
        #expect(await server.live() == ["bad.md": "x"])
    }

    @Test func largeFilesGoInChunksAndResumeWhereTheyStopped() async throws {
        let box = try Box(), server = FakeServer()
        let size = SyncEngine.chunkBytes + 10
        let data = Data((0..<size).map { UInt8(truncatingIfNeeded: $0 * 31) })
        try box.put("big.bin", data)
        await server.set(dropAfterNextChunk: true)
        let engine = try box.engine(server)
        await #expect(throws: URLError.self) { try await engine.sync() }
        try await engine.sync()
        let chunk = Int64(SyncEngine.chunkBytes), total = Int64(size)
        #expect(await server.puts == [BlobRange(first: 0, last: chunk - 1, total: total),
                                      BlobRange(first: chunk, last: total - 1, total: total)])
        #expect(await server.files.values.first?.hash == ContentHash.sha256(data))
    }

    @Test func anExpiredCursorReconcilesFromTheSnapshot() async throws {
        let box = try Box(), server = FakeServer()
        let gone = await server.seed("gone.md", "g1")
        let keep = await server.seed("keep.md", "k1")
        let engine = try box.engine(server)
        try await engine.sync()
        await server.remove(gone)
        await server.forget(gone)
        await server.edit(keep, "k2-newer")
        try await engine.sync()
        #expect(box.text("gone.md") == nil)
        #expect(box.recovered().contains("g1"))
        #expect(box.text("keep.md") == "k2-newer")
    }

    @Test func anEditOfAFileTheServerForgotIsRestoredAsANewFile() async throws {
        let box = try Box(), server = FakeServer()
        let id = await server.seed("note.md", "n1")
        let engine = try box.engine(server)
        try await engine.sync()
        await server.remove(id)
        await server.forget(id)
        try box.put("note.md", "edited offline")
        try await engine.sync()
        try await engine.sync()
        #expect(await server.live() == ["note.md": "edited offline"])
        #expect(try await engine.flaggedFiles().map(\.flag) == ["restored"])
    }

    @Test func operationsPastTheWindowAreDroppedAndSentFresh() async throws {
        let box = try Box(), server = FakeServer(), clock = Clock()
        try box.put("a.md", "one")
        await server.set(failPushes: true)
        let engine = try box.engine(server, clock: clock)
        await #expect(throws: URLError.self) { try await engine.sync() }
        let first = await server.attempted.first?.first?.clientOpID
        clock.advance(days: 84)
        await server.set(failPushes: false)
        try await engine.sync()
        #expect(await server.live() == ["a.md": "one"])
        #expect(await server.pushed.last?.first?.clientOpID != first)
    }

    @Test func pagesArePulledUntilTheLast() async throws {
        let box = try Box(), server = FakeServer()
        for i in 0..<5 { _ = await server.seed("n\(i).md", "text \(i)") }
        await server.set(pageSize: 2)
        let engine = try box.engine(server)
        try await engine.sync()
        #expect((0..<5).allSatisfy { box.text("n\($0).md") == "text \($0)" })
    }

    @Test func duplicatesAreReadAsTheirFirstResult() {
        let update = OutboxOp(clientOpID: "c", fileID: "f", op: .update, kind: .note, baseRevision: 1,
                              contentHash: "sha256:01", createdAt: 0)
        func dup(_ hash: String?, revision: Int64? = 2, original: String? = nil) -> PushOutcome {
            PushOutcome(status: .duplicate, fileID: "f", revision: revision, contentHash: hash, originalFileID: original)
        }
        #expect(SyncEngine.original(of: dup("sha256:01"), for: update) == .applied)
        #expect(SyncEngine.original(of: dup("sha256:02"), for: update) == .merged)
        #expect(SyncEngine.original(of: dup(nil, revision: nil), for: update) == .rejected)
        #expect(SyncEngine.original(of: dup("sha256:01", original: "g"), for: update) == .conflict)
    }

    @Test func hintsForThisVaultWakeTheEngine() async throws {
        let server = FakeServer()
        let wakes = Counter()
        let listener = Task { await SyncEngine.listen(api: server, vaultID: "vault") { wakes.bump() } }
        defer { listener.cancel() }
        try await until { await server.hints != nil }
        await server.hint(.ready(vaults: ["vault"]))
        await server.hint(.change(vaultID: "other", seq: 1))
        await server.hint(.change(vaultID: "VAULT", seq: 2))
        try await until { wakes.count == 2 }
        #expect(wakes.count == 2)
    }

    @Test func uuidsAreVersion7() {
        let id = UUIDv7.make(at: Date(timeIntervalSince1970: 1_700_000_000))
        #expect(id.count == 36)
        #expect(id.hasPrefix("018bcfe5-6800-7"))
        #expect(UUID(uuidString: id) != nil)
    }
}

/// Polls `condition` for up to 2 s.
func until(_ condition: @Sendable () async -> Bool) async throws {
    for _ in 0..<200 {
        if await condition() { return }
        try await Task.sleep(for: .milliseconds(10))
    }
    Issue.record("condition not met in time")
}
