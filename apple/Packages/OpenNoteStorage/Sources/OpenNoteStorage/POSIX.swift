import Foundation

#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#elseif canImport(Musl)
import Musl
#endif

/// What `lstat` says about one directory entry; symlinks are never followed.
struct FileStat {
    enum Kind { case file, directory, other }

    let kind: Kind
    let size: Int64
    let mtimeNs: Int64
    let inode: UInt64

    /// nil when nothing exists at `path`.
    static func of(_ path: String) throws(VaultError) -> FileStat? {
        var st = stat()
        guard lstat(path, &st) == 0 else {
            if errno == ENOENT || errno == ENOTDIR { return nil }
            throw .io(path, errno)
        }
        let type = st.st_mode & S_IFMT
        #if canImport(Darwin)
        let mtime = st.st_mtimespec
        #else
        let mtime = st.st_mtim
        #endif
        return FileStat(
            kind: type == S_IFREG ? .file : type == S_IFDIR ? .directory : .other,
            size: Int64(st.st_size),
            mtimeNs: Int64(mtime.tv_sec) * 1_000_000_000 + Int64(mtime.tv_nsec),
            inode: UInt64(st.st_ino))
    }
}

/// Opens a regular file for reading without following a symlink in the last component.
func openNoFollow(_ path: String) throws(VaultError) -> FileHandle {
    let fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    guard fd >= 0 else {
        if errno == ENOENT { throw .notFound(path) }
        if errno == ELOOP { throw .symlink(path) }
        throw .io(path, errno)
    }
    return FileHandle(fileDescriptor: fd, closeOnDealloc: true)
}

/// fsync a directory so a rename in it is durable.
func fsyncDirectory(_ path: String) {
    let fd = open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC)
    guard fd >= 0 else { return }
    _ = fsync(fd)
    close(fd)
}

/// `write(2)`, named apart from `Vault.write`.
func posixWrite(_ fd: Int32, _ buffer: UnsafeRawPointer, _ count: Int) -> Int {
    write(fd, buffer, count)
}
