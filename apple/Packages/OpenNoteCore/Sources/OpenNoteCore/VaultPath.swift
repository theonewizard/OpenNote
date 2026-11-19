import Foundation

/// How a vault path is treated (storage contract §1.1).
public enum FileKind: String, Sendable, Codable {
    case note, attachment, config
    case obsidianConfig = "obsidian_config"
    case ignored, temp
}

/// One broken path rule; `segment` is nil for whole-path rules.
public struct PathViolation: Sendable, Equatable, Codable {
    public let code: String
    public let segment: String?

    public init(_ code: String, segment: String? = nil) {
        self.code = code
        self.segment = segment
    }
}

/// Vault path rules shared by every client (storage contract §1.1 and §3), the Swift twin of
/// `backend/app/vaults/paths.py`. Paths are vault-relative, `/`-separated and compared in
/// Unicode NFC. The rules here are pure string checks.
public enum VaultPath {
    public static let maxSegmentBytes = 255
    public static let maxPathBytes = 1024
    public static let forbiddenChars: Set<Unicode.Scalar> = ["*", "\"", "\\", "/", "<", ">", ":", "|", "?"]
    public static let linkChars: Set<Unicode.Scalar> = ["#", "^", "[", "]", "|"]
    public static let reservedNames: Set<String> = Set(["CON", "PRN", "AUX", "NUL"]
        + (1...9).map { "COM\($0)" } + (1...9).map { "LPT\($0)" })
    public static let osCruft: Set<String> = ["thumbs.db", "desktop.ini", "icon\r"]
    public static let tempSuffix = ".opennote-tmp"

    /// The NFC form of `path`; nothing else changes.
    public static func normalize(_ path: String) -> String {
        path.precomposedStringWithCanonicalMapping
    }

    /// The key two paths collide on: NFC, then case-folded (Python `str.casefold`).
    public static func casefoldKey(_ path: String) -> String {
        normalize(path).folding(options: .caseInsensitive, locale: nil)
    }

    /// Storage contract §1.1, first match wins.
    public static func classify(_ path: String) -> FileKind {
        let segments = path.scalarSplit("/")
        let name = segments.last ?? ""
        if name.scalarsEnd(with: tempSuffix) { return .temp }
        if path == ".opennote/config.json" { return .config }
        if segments.first == ".obsidian" { return .obsidianConfig }
        if segments.contains(where: { $0.scalarsStart(with: ".") }) || osCruft.contains(casefoldKey(name)) {
            return .ignored
        }
        if casefoldKey(name).scalarsEnd(with: ".md") { return .note }
        return .attachment
    }

    /// The rule violations of `path` (empty when valid). Case-fold collisions need the folder
    /// listing, so callers check those with `casefoldKey`.
    public static func validate(_ path: String, note: Bool) -> [PathViolation] {
        if path.isEmpty { return [PathViolation("empty_segment")] }
        if path.scalarsStart(with: "/") { return [PathViolation("absolute")] }
        var found: [PathViolation] = []
        if path.unicodeScalars.contains("\\") { found.append(PathViolation("backslash")) }
        if path.utf8.count > maxPathBytes { found.append(PathViolation("path_too_long")) }
        let segments = path.scalarSplit("/")
        for (index, segment) in segments.enumerated() {
            found += segmentViolations(segment, note: note && index == segments.count - 1)
        }
        return found
    }

    private static func segmentViolations(_ segment: String, note: Bool) -> [PathViolation] {
        func bad(_ code: String) -> PathViolation { PathViolation(code, segment: segment) }
        if segment.isEmpty { return [bad("empty_segment")] }
        if segment == "." || segment == ".." { return [bad("dot_segment")] }
        var found: [PathViolation] = []
        if segment.unicodeScalars.contains(where: { $0.value < 0x20 || $0.value == 0x7F }) {
            found.append(bad("control_char"))
        }
        if segment.unicodeScalars.contains(where: { $0 != "\\" && forbiddenChars.contains($0) }) {
            found.append(bad("forbidden_char"))
        }
        if note && segment.unicodeScalars.contains(where: { linkChars.contains($0) }) { found.append(bad("link_char")) }
        if segment.scalarsStart(with: ".") { found.append(bad("leading_dot")) }
        if segment.scalarsEnd(with: " ") || segment.scalarsEnd(with: ".") { found.append(bad("trailing_space_or_dot")) }
        if segment.utf8.count > maxSegmentBytes { found.append(bad("segment_too_long")) }
        let base = String(String.UnicodeScalarView(segment.unicodeScalars.prefix { $0 != "." }))
        if reservedNames.contains(base.uppercased()) { found.append(bad("reserved_name")) }
        return found
    }
}

extension String {
    /// `hasPrefix` by Unicode scalars, as Python's `startswith` compares code points
    /// (`String.hasPrefix` compares grapheme clusters).
    func scalarsStart(with prefix: String) -> Bool {
        unicodeScalars.starts(with: prefix.unicodeScalars)
    }

    /// `split` by Unicode scalars, keeping empty pieces, as Python's `str.split(sep)`.
    func scalarSplit(_ separator: Unicode.Scalar) -> [String] {
        unicodeScalars.split(separator: separator, omittingEmptySubsequences: false)
            .map { String(String.UnicodeScalarView($0)) }
    }

    /// `hasSuffix` by Unicode scalars, as Python's `endswith`.
    func scalarsEnd(with suffix: String) -> Bool {
        unicodeScalars.reversed().starts(with: suffix.unicodeScalars.reversed())
    }
}
