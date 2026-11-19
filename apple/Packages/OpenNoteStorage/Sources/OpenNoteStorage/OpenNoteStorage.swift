import Foundation
import OpenNoteCore

/// The module's name, which OpenNoteSync's placeholder lists among its dependencies.
public enum OpenNoteStorage {
    public static let moduleName = "OpenNoteStorage"
}

/// One vault on this device: the folder plus its state database and recovery area, which live
/// in `supportDirectory` (Application Support on macOS, the app container's Library on iOS),
/// never inside the vault (storage contract §1.3).
public final class LocalVault {
    public let vault: Vault
    public let state: StateStore

    public init(root: URL, supportDirectory: URL) throws {
        try FileManager.default.createDirectory(at: supportDirectory, withIntermediateDirectories: true)
        vault = Vault(root: root, recoveryRoot: supportDirectory.appendingPathComponent("recovery"))
        state = try StateStore(url: supportDirectory.appendingPathComponent("state.sqlite"))
    }

    /// Scans the vault (re-hashing only files whose size, mtime or inode moved) and updates
    /// the state; the result is what changed outside OpenNote since the last call.
    @discardableResult
    public func reconcile() throws -> Changes {
        try state.apply(scan: vault.scan(known: state.files()))
    }

    public func read(_ path: String) throws -> NoteDocument {
        NoteDocument(try vault.read(path))
    }

    /// Saves over the version the state last saw; `.externalChange` if the file moved on.
    @discardableResult
    public func save(_ path: String, _ data: Data) throws -> WrittenFile {
        let known = try state.file(VaultPath.normalize(path))
        guard let base = known?.contentHash else { throw VaultError.notFound(path) }
        return try record(vault.write(path, data, expectedBase: base))
    }

    /// Creates a new file; `.invalidPath` for a name that breaks the path rules.
    @discardableResult
    public func create(_ path: String, _ data: Data) throws -> WrittenFile {
        try record(vault.write(path, data, expectedBase: nil))
    }

    /// Moves the file to the recovery area if it is still the version the state last saw.
    public func delete(_ path: String) throws {
        let normalized = VaultPath.normalize(path)
        guard let base = try state.file(normalized)?.contentHash else { throw VaultError.notFound(path) }
        try vault.delete(normalized, expectedBase: base)
        try state.remove(normalized)
    }

    private func record(_ written: WrittenFile) throws -> WrittenFile {
        let normalized = VaultPath.normalize(written.path)
        let name = try vault.resolve(normalized).split(separator: "/").last.map(String.init) ?? normalized
        let file = WrittenFile(path: normalized, size: written.size, mtimeNs: written.mtimeNs,
                               inode: written.inode, contentHash: written.contentHash)
        try state.record(file, kind: VaultPath.classify(normalized), diskName: name)
        return file
    }
}
