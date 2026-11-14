import Foundation

#if canImport(CryptoKit)
import CryptoKit
#else
import Crypto
#endif

/// Domain rules shared by the OpenNote apps.
public enum OpenNoteCore {
    /// The OpenNote release; the same string as `backend/app/__init__.py`.
    public static let version = "0.1.0"
}

/// Content hashes as defined by the storage contract (§6).
public enum ContentHash {
    /// `"sha256:"` followed by the lowercase hex SHA-256 of exactly these bytes.
    public static func sha256(_ data: Data) -> String {
        format(SHA256.hash(data: data))
    }

    /// The same hash of everything left to read from `handle`, in 1 MiB chunks so large
    /// attachments are never held in memory whole. The caller opens and closes the handle.
    public static func sha256(reading handle: FileHandle) throws -> String {
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        return format(hasher.finalize())
    }

    private static func format(_ digest: SHA256.Digest) -> String {
        "sha256:" + digest.map { byte in
            let digits = String(byte, radix: 16)
            return byte < 0x10 ? "0" + digits : digits
        }.joined()
    }
}
