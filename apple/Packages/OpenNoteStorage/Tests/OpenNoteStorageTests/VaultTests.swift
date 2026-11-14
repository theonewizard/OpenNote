import Foundation
import OpenNoteCore
import OpenNoteStorage
import Testing

/// A fresh vault folder and support folder under the system temp directory.
final class Sandbox {
    let base = FileManager.default.temporaryDirectory.appendingPathComponent("opennote-\(UUID().uuidString)")
    var root: URL { base.appendingPathComponent("vault") }
    var support: URL { base.appendingPathComponent("support") }

    init() throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    deinit { try? FileManager.default.removeItem(at: base) }

    func put(_ path: String, _ text: String) throws {
        let url = root.appendingPathComponent(path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(text.utf8).write(to: url)
    }

    func bytes(_ path: String) throws -> Data { try Data(contentsOf: root.appendingPathComponent(path)) }

    func local() throws -> LocalVault { try LocalVault(root: root, supportDirectory: support) }
}

let compatibility = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("tests/compatibility/vaults")

func corpusNotes() -> [String] {
    let names = (try? FileManager.default.contentsOfDirectory(atPath: compatibility.path)) ?? []
    return names.filter {
        FileManager.default.fileExists(atPath: compatibility.appendingPathComponent("\($0)/note.md").path)
    }.sorted()
}

@Suite struct ScanTests {
    @Test func corpusVaultTreeMatchesExpected() throws {
        let vault = Vault(root: compatibility.appendingPathComponent("obsidian-basic/vault"),
                          recoveryRoot: FileManager.default.temporaryDirectory)
        let expected = try JSONSerialization.jsonObject(
            with: Data(contentsOf: compatibility.appendingPathComponent("obsidian-basic/expected.json"))) as! [String: Any]
        let files = (expected["files"] as! [[String: Any]]).map {
            "\($0["path"] as! String) \($0["kind"] as! String) \($0["path_warning"] as! Bool)"
        }
        let got = try vault.scan().map { "\($0.path) \($0.kind.rawValue) \($0.pathWarning)" }
        #expect(got == files)
    }

    @Test func knownFilesKeepTheirHashAndChangedOnesAreRehashed() throws {
        let box = try Sandbox()
        try box.put("a.md", "one")
        let vault = Vault(root: box.root, recoveryRoot: box.support)
        var first = Dictionary(uniqueKeysWithValues: try vault.scan().map { ($0.path, $0) })
        #expect(first["a.md"]?.contentHash == ContentHash.sha256(Data("one".utf8)))
        // A stale hash survives a scan when (size, mtime, inode) still match: mtime is the hint.
        let old = first["a.md"]!
        first["a.md"] = ScannedFileProbe.with(old, hash: "sha256:stale")
        #expect(try vault.scan(known: first).first?.contentHash == "sha256:stale")
        try box.put("a.md", "changed")
        #expect(try vault.scan(known: first).first?.contentHash == ContentHash.sha256(Data("changed".utf8)))
    }

    @Test func symlinksAndDotFoldersAreSkipped() throws {
        let box = try Sandbox()
        try box.put("real.md", "x")
        try box.put(".obsidian/app.json", "{}")
        try box.put("folder/.hidden.md", "x")
        try FileManager.default.createSymbolicLink(atPath: box.root.appendingPathComponent("link.md").path,
                                                   withDestinationPath: "real.md")
        let paths = try Vault(root: box.root, recoveryRoot: box.support).scan().map(\.path)
        #expect(paths == ["real.md"])
    }

    @Test func caseFoldTwinsAndBadNamesGetAPathWarning() throws {
        let box = try Sandbox()
        try box.put("Note.md", "x")
        try box.put("ok.md", "x")
        try box.put("a#b.md", "x")
        try box.put("note.md", "y")  // a second file only on case-sensitive filesystems (Linux)
        let files = try Vault(root: box.root, recoveryRoot: box.support).scan()
        let warned = files.filter(\.pathWarning).map(\.path).sorted()
        #expect(warned == (files.count == 4 ? ["Note.md", "a#b.md", "note.md"] : ["a#b.md"]))
    }
}

/// The same ScannedFile with another hash.
enum ScannedFileProbe {
    static func with(_ f: ScannedFile, hash: String) -> ScannedFile {
        ScannedFile(path: f.path, diskName: f.diskName, kind: f.kind, size: f.size, mtimeNs: f.mtimeNs,
                    inode: f.inode, contentHash: hash, pathWarning: f.pathWarning)
    }
}

@Suite struct WriteTests {
    @Test(arguments: corpusNotes())
    func corpusNotesWriteAndReadBackByteForByte(_ name: String) throws {
        let box = try Sandbox()
        let raw = try Data(contentsOf: compatibility.appendingPathComponent("\(name)/note.md"))
        let local = try box.local()
        try local.create("\(name).md", raw)
        #expect(try box.bytes("\(name).md") == raw)
        let doc = try local.read("\(name).md")
        #expect(doc.raw == raw)
        if let body = doc.bodyText {
            try local.save("\(name).md", try doc.replacing(doc.body, with: body))
            #expect(try box.bytes("\(name).md") == raw)
        }
    }

    @Test func saveRefusesToClobberAnExternalEdit() throws {
        let box = try Sandbox()
        let local = try box.local()
        try local.create("n.md", Data("ours\n".utf8))
        try box.put("n.md", "theirs\n")  // Obsidian saves meanwhile
        #expect(throws: VaultError.externalChange("n.md", currentHash: ContentHash.sha256(Data("theirs\n".utf8)))) {
            try local.save("n.md", Data("ours, edited\n".utf8))
        }
        #expect(try box.bytes("n.md") == Data("theirs\n".utf8))
        #expect(try FileManager.default.contentsOfDirectory(atPath: box.root.path) == ["n.md"])  // no temp left
    }

    @Test func createRefusesAnExistingFileAndCaseFoldTwins() throws {
        let box = try Sandbox()
        try box.put("Plan.md", "x")
        let vault = Vault(root: box.root, recoveryRoot: box.support)
        #expect(throws: VaultError.externalChange("Plan.md", currentHash: ContentHash.sha256(Data("x".utf8)))) {
            try vault.write("Plan.md", Data("y".utf8), expectedBase: nil)
        }
        #expect(throws: VaultError.self) { try vault.write("PLAN.md", Data("y".utf8), expectedBase: nil) }
        #expect(try box.bytes("Plan.md") == Data("x".utf8))
    }

    @Test func unsafeAndRuleBreakingPathsAreRefused() throws {
        let box = try Sandbox()
        try FileManager.default.createDirectory(at: box.base.appendingPathComponent("outside"), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(atPath: box.root.appendingPathComponent("escape").path,
                                                   withDestinationPath: "../outside")
        let vault = Vault(root: box.root, recoveryRoot: box.support)
        for path in ["../x.md", "/etc/x.md", "a//b.md", "./x.md", "escape/x.md", "bad:name.md", "a#b.md", ".hidden.md", "CON.md"] {
            #expect(throws: VaultError.self, "\(path)") { try vault.write(path, Data("x".utf8), expectedBase: nil) }
        }
        #expect(try FileManager.default.contentsOfDirectory(atPath: box.base.appendingPathComponent("outside").path).isEmpty)
    }

    @Test func newFilesCreateTheirFoldersAndUseNFC() throws {
        let box = try Sandbox()
        let vault = Vault(root: box.root, recoveryRoot: box.support)
        try vault.write("Re\u{301}sume\u{301}/Cafe\u{301}.md", Data("x".utf8), expectedBase: nil)
        #expect(try vault.scan().map(\.path) == ["Résumé/Café.md"])
        #expect(try vault.read("Re\u{301}sume\u{301}/Cafe\u{301}.md") == Data("x".utf8))
    }

    @Test func localSaveIsUnder100Milliseconds() throws {
        let box = try Sandbox()
        let local = try box.local()
        let note = Data(String(repeating: "A line of a typical note with [[a link]] and #tag.\n", count: 2_000).utf8)  // ~100 KB
        try local.create("big.md", note)
        var timings: [Duration] = []
        for i in 0..<5 {
            var edited = note
            edited.append(Data("edit \(i)\n".utf8))
            let clock = ContinuousClock()
            timings.append(try clock.measure { try local.save("big.md", edited) })
        }
        let median = timings.sorted()[2]
        #expect(median < .milliseconds(100), "median save \(median)")
    }

    @Test func staleTempFilesAreRemovedAndFreshOnesKept() throws {
        let box = try Sandbox()
        try box.put(".a.md.1234.opennote-tmp", "old")
        try box.put("sub/.b.md.5678.opennote-tmp", "new")
        let old = box.root.appendingPathComponent(".a.md.1234.opennote-tmp")
        try FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(-7200)], ofItemAtPath: old.path)
        Vault(root: box.root, recoveryRoot: box.support).removeStaleTemps()
        #expect(!FileManager.default.fileExists(atPath: old.path))
        #expect(FileManager.default.fileExists(atPath: box.root.appendingPathComponent("sub/.b.md.5678.opennote-tmp").path))
    }
}

@Suite struct DeleteTests {
    @Test func deleteMovesTheFileToRecovery() throws {
        let box = try Sandbox()
        let local = try box.local()
        try local.create("gone.md", Data("keep me\n".utf8))
        try local.delete("gone.md")
        #expect(!FileManager.default.fileExists(atPath: box.root.appendingPathComponent("gone.md").path))
        let recovered = FileManager.default.enumerator(atPath: box.support.appendingPathComponent("recovery").path)?
            .compactMap { $0 as? String }.filter { $0.hasSuffix("gone.md") } ?? []
        #expect(recovered.count == 1)
        #expect(try local.reconcile().isEmpty)
    }

    @Test func deleteRefusesAnExternallyChangedFileAndLeavesIt() throws {
        let box = try Sandbox()
        let local = try box.local()
        try local.create("n.md", Data("ours".utf8))
        try box.put("n.md", "theirs")
        #expect(throws: VaultError.self) { try local.delete("n.md") }
        #expect(try box.bytes("n.md") == Data("theirs".utf8))
    }
}

@Suite struct StateTests {
    @Test func reconcileReportsOutsideChangesButNotOurOwnWrites() throws {
        let box = try Sandbox()
        try box.put("a.md", "a")
        try box.put("b.md", "b")
        let local = try box.local()
        let first = try local.reconcile()
        #expect(first.added.map(\.path) == ["a.md", "b.md"])
        try local.save("a.md", Data("a2".utf8))
        try local.create("c.md", Data("c".utf8))
        #expect(try local.reconcile().isEmpty)
        try box.put("b.md", "b changed elsewhere")
        try FileManager.default.removeItem(at: box.root.appendingPathComponent("c.md"))
        let changes = try local.reconcile()
        #expect(changes.modified.map(\.path) == ["b.md"])
        #expect(changes.removed == ["c.md"])
        #expect(changes.added.isEmpty)
    }

    @Test func stateSurvivesReopening() throws {
        let box = try Sandbox()
        try box.put("a.md", "a")
        do {
            let local = try box.local()
            try local.reconcile()
            try local.state.setMeta("cursor", "42")
        }
        let reopened = try box.local()
        #expect(try reopened.reconcile().isEmpty)
        #expect(try reopened.state.meta("cursor") == "42")
        #expect(try reopened.state.file("a.md")?.contentHash == ContentHash.sha256(Data("a".utf8)))
    }
}
