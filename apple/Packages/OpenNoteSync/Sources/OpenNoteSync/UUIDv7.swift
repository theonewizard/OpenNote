import Foundation

/// A UUIDv7 (RFC 9562 §5.7): 48-bit Unix milliseconds, then random bits. The protocol asks
/// for them as `file_id` and `client_op_id`; time order keeps the server's indexes compact.
enum UUIDv7 {
    static func make(at date: Date = Date()) -> String {
        var bytes = (0..<16).map { _ in UInt8.random(in: 0...255) }
        let ms = UInt64(max(0, date.timeIntervalSince1970 * 1000))
        for i in 0..<6 { bytes[i] = UInt8(truncatingIfNeeded: ms >> (8 * (5 - i))) }
        bytes[6] = (bytes[6] & 0x0F) | 0x70  // version 7
        bytes[8] = (bytes[8] & 0x3F) | 0x80  // variant 10
        let hex = bytes.map { $0 < 0x10 ? "0" + String($0, radix: 16) : String($0, radix: 16) }
        return [hex[0..<4], hex[4..<6], hex[6..<8], hex[8..<10], hex[10..<16]].map { $0.joined() }.joined(separator: "-")
    }
}
