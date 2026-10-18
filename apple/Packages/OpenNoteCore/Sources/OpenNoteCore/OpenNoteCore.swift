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
        let hex = SHA256.hash(data: data).map { byte in
            let digits = String(byte, radix: 16)
            return byte < 0x10 ? "0" + digits : digits
        }
        return "sha256:" + hex.joined()
    }
}
