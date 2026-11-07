import CFileSwap
import Foundation
import OpenNoteCore

#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#elseif canImport(Musl)
import Musl
#endif

public enum VaultError: Error, Equatable {
    /// The path is not a safe vault-relative path, or breaks the rules for a new file.
    case invalidPath(String, [PathViolation])
    /// A component of the path is a symlink; vaults never follow them (contract §1.1).
    case symlink(String)
    case notFound(String)
    /// The file on disk is not the expected base: an external edit (or create, or delete)
    /// happened. Nothing was overwritten; the sync engine takes it from here (contract §4.4).
    case externalChange(String, currentHash: String?)
    case io(String, Int32)
}

/// One note or attachment found by a scan (contract §1.1, §3, §6).
public struct ScannedFile: Sendable, Equatable {
    /// Vault-relative, NFC.
    public let path: String
    /// The leaf name exactly as spelled on disk.
    public let diskName: String
    public let kind: FileKind
    public let size: Int64
    public let mtimeNs: Int64
    public let inode: UInt64
    /// nil: the file could not be read; treat it as unchanged.
    public let contentHash: String?
    public let pathWarning: Bool

    public init(path: String, diskName: String, kind: FileKind, size: Int64, mtimeNs: Int64, inode: UInt64,
                contentHash: String?, pathWarning: Bool) {
        self.path = path
        self.diskName = diskName
        self.kind = kind
        self.size = size
        self.mtimeNs = mtimeNs
        self.inode = inode
        self.contentHash = contentHash
        self.pathWarning = pathWarning
    }
}

/// The on-disk facts after OpenNote wrote a file.
public struct WrittenFile: Sendable, Equatable {
    public let path: String
    public let size: Int64
    public let mtimeNs: Int64
    public let inode: UInt64
    public let contentHash: String
}

/// A local vault directory: scanning, reading, and writes that never clobber an external edit
/// (storage contract §1, §3, §4), the client side of `backend/app/vaults`.
///
/// Writes go to a dot-prefixed temp file in the target folder, are flushed, then swapped with
/// the target in one step (`renamex_np(RENAME_SWAP)` on Apple platforms, `renameat2`
/// with `RENAME_EXCHANGE` on Linux). The displaced bytes are hashed afterwards: if they are not
/// the expected base, they go back and the caller gets `.externalChange`. On Apple platforms
/// every write and delete is coordinated with `NSFileCoordinator`, so Files, iCloud Drive
/// and Obsidian see a coordinated change. Deletes move the file to `recoveryRoot`, outside the
/// vault, never unlinking it first.
public struct Vault: Sendable {
    public static let maxNoteBytes: Int64 = 16 * 1024 * 1024  // a larger .md is an opaque attachment

    public let root: URL
    /// Where deleted and displaced files go (Application Support, never inside the vault).
    public let recoveryRoot: URL

    public init(root: URL, recoveryRoot: URL) {
        self.root = root.standardizedFileURL
        self.recoveryRoot = recoveryRoot.standardizedFileURL
    }

    // MARK: - Scan

    /// Every note and attachment, sorted by name within each folder, folders depth-first. A
    /// file whose (size, mtime, inode) match its entry in `known` keeps that entry's hash.
    public func scan(known: [String: ScannedFile] = [:]) throws(VaultError) -> [ScannedFile] {
        var out: [ScannedFile] = []
        try scanDirectory(root.path, prefix: "", known: known, into: &out)
        return out
    }

    private func scanDirectory(_ dir: String, prefix: String, known: [String: ScannedFile],
                               into out: inout [ScannedFile]) throws(VaultError) {
        let names: [String]
        do {
            names = try FileManager.default.contentsOfDirectory(atPath: dir)
        } catch {
            throw .io(dir, EIO)
        }
        let entries = names.map { (disk: $0, name: VaultPath.normalize($0)) }
            .sorted { $0.name.unicodeScalars.lexicographicallyPrecedes($1.name.unicodeScalars) }
        let keys = entries.map { VaultPath.casefoldKey($0.name) }
        var keyCounts: [String: Int] = [:]
        for key in keys { keyCounts[key, default: 0] += 1 }
        for (entry, key) in zip(entries, keys) {
            let path = prefix + entry.name
            var kind = VaultPath.classify(path)
            guard kind == .note || kind == .attachment else { continue }  // never read
            let full = dir + "/" + entry.disk
            guard let st = try FileStat.of(full) else { continue }  // removed during the scan
            switch st.kind {
            case .directory:
                try scanDirectory(full, prefix: path + "/", known: known, into: &out)
            case .file:
                if kind == .note && st.size > Self.maxNoteBytes { kind = .attachment }
                let warning = !VaultPath.validate(path, note: kind == .note).isEmpty || keyCounts[key, default: 0] > 1
                var hash: String?
                if let old = known[path], old.size == st.size, old.mtimeNs == st.mtimeNs, old.inode == st.inode {
                    hash = old.contentHash
                }
                if hash == nil {
                    do {
                        hash = try Self.hash(full)
                    } catch .notFound {
                        continue  // removed during the scan: the next one reports the delete
                    } catch {
                        hash = nil  // unreadable (permissions, a swapped-in symlink): kept as is
                    }
                }
                out.append(ScannedFile(path: path, diskName: entry.disk, kind: kind, size: st.size,
                                       mtimeNs: st.mtimeNs, inode: st.inode, contentHash: hash,
                                       pathWarning: warning))
            case .other:
                continue  // symlinks and special files are unsupported entries
            }
        }
    }

    // MARK: - Read

    public func read(_ path: String) throws(VaultError) -> Data {
        let full = try resolve(path)
        let handle = try openNoFollow(full)
        do {
            return try handle.readToEnd() ?? Data()
        } catch {
            throw .io(full, EIO)
        }
    }

    /// The content hash of the file at `path`, or nil when there is none.
    public func currentHash(_ path: String) throws(VaultError) -> String? {
        let full = try resolve(path)
        do {
            return try Self.hash(full)
        } catch .notFound {
            return nil
        }
    }

    // MARK: - Write

    /// Writes `data` to `path`. `expectedBase` is the hash of the bytes the caller last saw:
    /// nil means the file must not exist yet. Throws `.externalChange` instead of overwriting
    /// anything else.
    @discardableResult
    public func write(_ path: String, _ data: Data, expectedBase: String?) throws(VaultError) -> WrittenFile {
        let creating = expectedBase == nil
        let full = try resolve(path, forNewFile: creating)
        let dir = (full as NSString).deletingLastPathComponent
        if creating { try makeParents(of: path) }
        try coordinate(full, deleting: false) { () throws(VaultError) in
            let current = try Self.hashIfPresent(full)
            guard current == expectedBase else { throw .externalChange(path, currentHash: current) }
            let tmp = try writeTemp(data, nextTo: full)
            if creating {
                if opennote_rename_noreplace(tmp, full) != 0 {
                    let error = errno
                    if error == ENOTSUP || error == EINVAL, case .some(.none) = try? FileStat.of(full) {
                        // No RENAME_NOREPLACE here (some network volumes): check, then rename.
                        guard rename(tmp, full) == 0 else { throw cleanup(tmp, .io(full, errno)) }
                    } else if error == EEXIST {
                        throw cleanup(tmp, .externalChange(path, currentHash: try Self.hashIfPresent(full)))
                    } else {
                        throw cleanup(tmp, .io(full, error))
                    }
                }
            } else if opennote_exchange(tmp, full) == 0 {
                // `tmp` now holds the displaced bytes: they must be the base we expected.
                let displaced = try Self.hashIfPresent(tmp)
                if displaced != expectedBase {
                    try putBack(displaced: tmp, target: full, ours: ContentHash.sha256(data))
                    throw .externalChange(path, currentHash: displaced)
                }
                unlink(tmp)
            } else {
                let error = errno
                if error == ENOENT {
                    throw cleanup(tmp, .externalChange(path, currentHash: nil))  // deleted meanwhile
                }
                guard error == ENOTSUP || error == EINVAL else { throw cleanup(tmp, .io(full, error)) }
                // No atomic swap on this filesystem: check, then rename. An external save in
                // between would be lost; the window is documented in the storage contract §4.2.
                let again = try Self.hashIfPresent(full)
                guard again == expectedBase else {
                    throw cleanup(tmp, .externalChange(path, currentHash: again))
                }
                guard rename(tmp, full) == 0 else { throw cleanup(tmp, .io(full, errno)) }
            }
            fsyncDirectory(dir)
        }
        guard let st = try FileStat.of(full) else { throw .externalChange(path, currentHash: nil) }
        return WrittenFile(path: path, size: st.size, mtimeNs: st.mtimeNs, inode: st.inode,
                           contentHash: ContentHash.sha256(data))
    }

    /// Moves the file at `path` to the recovery area if it still has `expectedBase`; returns
    /// where it went.
    @discardableResult
    public func delete(_ path: String, expectedBase: String) throws(VaultError) -> URL {
        let full = try resolve(path)
        var moved: URL?
        try coordinate(full, deleting: true) { () throws(VaultError) in
            // Take the file out of the way first, then check what was taken: an external save
            // can never land between the check and the delete.
            let name = (full as NSString).lastPathComponent
            let tmp = (full as NSString).deletingLastPathComponent + "/.\(name).\(Self.token()).opennote-tmp"
            guard rename(full, tmp) == 0 else {
                if errno == ENOENT { throw .externalChange(path, currentHash: nil) }
                throw .io(full, errno)
            }
            let hash = try Self.hashIfPresent(tmp)
            guard hash == expectedBase else {
                if opennote_rename_noreplace(tmp, full) != 0 { moved = try toRecovery(tmp, path) }
                throw .externalChange(path, currentHash: hash)
            }
            moved = try toRecovery(tmp, path)
            fsyncDirectory((full as NSString).deletingLastPathComponent)
        }
        return moved!
    }

    /// Removes this vault's in-flight temp files older than `age` (crashed writes).
    public func removeStaleTemps(olderThan age: TimeInterval = 3600) {
        let cutoff = Date().addingTimeInterval(-age)
        let keys: [URLResourceKey] = [.contentModificationDateKey, .isRegularFileKey, .isDirectoryKey]
        guard let walker = FileManager.default.enumerator(at: root, includingPropertiesForKeys: keys) else { return }
        for case let url as URL in walker {
            let values = try? url.resourceValues(forKeys: Set(keys))
            let name = url.lastPathComponent
            if values?.isDirectory == true {
                if name.hasPrefix(".") { walker.skipDescendants() }  // .git, .obsidian, .trash
            } else if name.hasSuffix(VaultPath.tempSuffix), values?.isRegularFile == true,
                      let modified = values?.contentModificationDate, modified < cutoff {
                try? FileManager.default.removeItem(at: url)
            }
        }
    }

    // MARK: - Helpers

    /// The absolute path for `path`, refusing anything that could leave the vault: absolute
    /// paths, empty, `.` and `..` segments, NUL, and symlinked folders. A new file must also
    /// pass every path rule, including the case-fold collision check (contract §3.2).
    func resolve(_ path: String, forNewFile: Bool = false) throws(VaultError) -> String {
        var structural = VaultPath.validate(path, note: false).filter {
            ["empty_segment", "dot_segment", "absolute", "backslash"].contains($0.code)
        }
        if path.unicodeScalars.contains("\0") { structural.append(PathViolation("control_char")) }
        guard structural.isEmpty else { throw .invalidPath(path, structural) }
        let normalized = VaultPath.normalize(path)
        if forNewFile {
            let kind = VaultPath.classify(normalized)
            guard kind == .note || kind == .attachment else {
                throw .invalidPath(path, [PathViolation("not_vault_content")])
            }
            let violations = VaultPath.validate(normalized, note: kind == .note)
            guard violations.isEmpty else { throw .invalidPath(path, violations) }
        }
        var current = root.path
        let segments = segmentsOf(normalized)
        for (index, segment) in segments.enumerated() {
            let last = index == segments.count - 1
            let onDisk = try diskName(of: segment, in: current, forNewFile: forNewFile && last)
            current += "/" + onDisk
            if !last, let st = try FileStat.of(current), st.kind != .directory {
                throw st.kind == .other ? .symlink(current) : .invalidPath(path, [PathViolation("not_a_folder")])
            }
        }
        return current
    }

    /// The on-disk spelling of `segment` in `dir`: macOS may hold a name in NFD, so names
    /// are matched in NFC. A new file must not collide case-insensitively with another name.
    private func diskName(of segment: String, in dir: String, forNewFile: Bool) throws(VaultError) -> String {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: dir) else { return segment }
        if let exact = names.first(where: { VaultPath.normalize($0).unicodeScalars.elementsEqual(segment.unicodeScalars) }) {
            return exact  // for a new file the write then finds it and reports an external change
        }
        if forNewFile {
            let key = VaultPath.casefoldKey(segment)
            if names.contains(where: { VaultPath.casefoldKey($0) == key }) {
                throw .invalidPath(segment, [PathViolation("casefold_collision", segment: segment)])
            }
        }
        return segment
    }

    private func makeParents(of path: String) throws(VaultError) {
        var current = root.path
        let segments = segmentsOf(VaultPath.normalize(path)).dropLast()
        for segment in segments {
            current += "/" + (try diskName(of: segment, in: current, forNewFile: true))
            switch try FileStat.of(current)?.kind {
            case nil:
                guard mkdir(current, 0o755) == 0 || errno == EEXIST else { throw .io(current, errno) }
            case .directory?: continue
            case .other?: throw .symlink(current)
            case .file?: throw .invalidPath(path, [PathViolation("not_a_folder")])
            }
        }
    }

    private func writeTemp(_ data: Data, nextTo full: String) throws(VaultError) -> String {
        let name = (full as NSString).lastPathComponent
        let tmp = (full as NSString).deletingLastPathComponent + "/.\(name).\(Self.token()).opennote-tmp"
        let fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644)
        guard fd >= 0 else { throw .io(tmp, errno) }
        defer { close(fd) }
        let ok = data.withUnsafeBytes { buffer -> Bool in
            var offset = 0
            while offset < buffer.count {
                let n = posixWrite(fd, buffer.baseAddress! + offset, buffer.count - offset)
                if n < 0 { if errno == EINTR { continue }; return false }
                offset += n
            }
            return true
        }
        guard ok, opennote_full_fsync(fd) == 0 else { throw cleanup(tmp, .io(tmp, errno)) }
        return tmp
    }

    /// After a swap displaced bytes that were not the base: put them back if the target still
    /// holds what we wrote, otherwise keep them in the recovery area. Never unlinks them.
    private func putBack(displaced tmp: String, target: String, ours: String) throws(VaultError) {
        if try Self.hashIfPresent(target) == ours, opennote_exchange(tmp, target) == 0 {
            unlink(tmp)  // `tmp` holds our bytes again
            return
        }
        let relative = String(target.dropFirst(root.path.count + 1))
        _ = try toRecovery(tmp, relative)
    }

    private func toRecovery(_ file: String, _ path: String) throws(VaultError) -> URL {
        let dest = recoveryRoot
            .appendingPathComponent("\(Int(Date().timeIntervalSince1970))-\(Self.token())")
            .appendingPathComponent(path)
        do {
            try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            if rename(file, dest.path) != 0 {
                guard errno == EXDEV else { throw VaultError.io(dest.path, errno) }
                // The recovery area is on another volume (a vault on an external disk).
                try FileManager.default.copyItem(atPath: file, toPath: dest.path)
                unlink(file)
            }
        } catch let error as VaultError {
            throw error
        } catch {
            throw .io(dest.path, EIO)
        }
        return dest
    }

    private func cleanup(_ tmp: String, _ error: VaultError) -> VaultError {
        unlink(tmp)
        return error
    }

    private func coordinate(_ full: String, deleting: Bool, _ body: () throws(VaultError) -> Void) throws(VaultError) {
        #if os(macOS) || os(iOS) || os(visionOS)
        var result: Result<Void, VaultError> = .success(())
        var coordinationError: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(
            writingItemAt: URL(fileURLWithPath: full), options: deleting ? .forDeleting : .forReplacing,
            error: &coordinationError
        ) { _ in
            do throws(VaultError) { try body() } catch { result = .failure(error) }
        }
        if let coordinationError { throw .io(full, Int32(coordinationError.code)) }
        try result.get()
        #else
        try body()
        #endif
    }

    static func hash(_ full: String) throws(VaultError) -> String {
        let handle = try openNoFollow(full)
        do {
            return try ContentHash.sha256(reading: handle)
        } catch {
            throw .io(full, EIO)
        }
    }

    static func hashIfPresent(_ full: String) throws(VaultError) -> String? {
        do {
            return try hash(full)
        } catch .notFound {
            return nil
        }
    }

    private func segmentsOf(_ path: String) -> [String] {
        path.unicodeScalars.split(separator: "/", omittingEmptySubsequences: false)
            .map { String(String.UnicodeScalarView($0)) }
    }

    private static func token() -> String {
        String(UUID().uuidString.prefix(8)).lowercased()
    }
}
