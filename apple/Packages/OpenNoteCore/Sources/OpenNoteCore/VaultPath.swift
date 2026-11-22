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

    /// A valid file name made from any text (a dropped file's name, a note's first line):
    /// characters the rules forbid become `-`, leading dots and trailing spaces and dots go,
    /// the stem is cut to fit 255 bytes, and an empty name becomes `Untitled`.
    public static func sanitizedName(_ name: String, note: Bool = false) -> String {
        var scalars = Array(normalize(name).unicodeScalars).map { scalar -> Unicode.Scalar in
            let bad = scalar.value < 0x20 || scalar.value == 0x7F || forbiddenChars.contains(scalar)
                || (note && linkChars.contains(scalar))
            return bad ? "-" : scalar
        }
        scalars = Array(scalars.drop { $0 == "." })
        let dot = scalars.lastIndex(of: ".") ?? scalars.count
        var stem = Array(scalars[..<dot])
        let ext = Array(scalars[dot...])
        func bytes(_ s: [Unicode.Scalar]) -> Int { String(String.UnicodeScalarView(s)).utf8.count }
        while bytes(stem) + bytes(ext) > maxSegmentBytes, !stem.isEmpty { stem.removeLast() }
        var out = stem + ext
        while let last = out.last, last == " " || last == "." { out.removeLast() }
        var result = String(String.UnicodeScalarView(out))
        if result.isEmpty { return "Untitled" }
        let base = String(String.UnicodeScalarView(result.unicodeScalars.prefix { $0 != "." }))
        if reservedNames.contains(base.uppercased()) { result = "_" + result }
        return result
    }

    /// The file name for a note holding `text` (a quick capture, a shared page): its first
    /// non-empty line without heading marks, at most 60 characters, or `fallback`.
    public static func noteName(forText text: String, fallback: String) -> String {
        let line = text.split(whereSeparator: \.isNewline).lazy
            .map { $0.drop { $0 == "#" || $0 == " " || $0 == "\t" } }.first { !$0.isEmpty } ?? ""
        let title = line.prefix(60).trimmingCharacters(in: .whitespaces)
        return sanitizedName((title.isEmpty ? fallback : title) + ".md", note: true)
    }

    /// `path` if no entry of `taken` collides with it (case-folded, contract §3), else the
    /// first of `name 1.ext`, `name 2.ext`… that is free.
    public static func freePath(_ path: String, taken: some Sequence<String>) -> String {
        let keys = Set(taken.map(casefoldKey))
        guard keys.contains(casefoldKey(path)) else { return path }
        let slash = path.lastIndex(of: "/").map { path.index(after: $0) } ?? path.startIndex
        let dot = path[slash...].lastIndex(of: ".") ?? path.endIndex
        var n = 1
        while keys.contains(casefoldKey("\(path[..<dot]) \(n)\(path[dot...])")) { n += 1 }
        return "\(path[..<dot]) \(n)\(path[dot...])"
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
