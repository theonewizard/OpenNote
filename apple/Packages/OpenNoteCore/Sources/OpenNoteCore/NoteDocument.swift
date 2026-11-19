import Foundation

/// A line ending OpenNote writes: the note's dominant one, or LF for new files.
public enum LineEnding: String, Sendable {
    case lf = "\n"
    case crlf = "\r\n"
}

/// The note is not valid UTF-8: it is readable and synced as bytes, never edited.
public struct ReadOnlyNote: Error, Equatable {
    public init() {}
}

/// The byte-preserving note model (storage contract §2.1, §2.2), the Swift twin of
/// `backend/app/notes/document.py`.
///
/// A note is its bytes. Parsing finds the BOM, the dominant line ending and the frontmatter
/// span; every edit is a replacement of one span of the original text (`replacing`), never a
/// re-render, so bytes outside the edit cannot change. Spans are UTF-8 byte offsets into the
/// text after the BOM; they always fall on line boundaries.
public struct NoteDocument: Sendable, Equatable {
    public static let bom: [UInt8] = [0xEF, 0xBB, 0xBF]

    public let raw: Data
    /// The text after the BOM, or nil when the note is not valid UTF-8 (read-only, opaque).
    public let text: String?
    public let hasBOM: Bool
    public let newline: LineEnding
    /// The YAML between the delimiters.
    public let frontmatter: Range<Int>?
    public let body: Range<Int>

    private let utf8: [UInt8]

    public var isReadOnly: Bool { text == nil }

    public init(_ raw: Data) {
        let bytes = [UInt8](raw)
        let hasBOM = bytes.starts(with: Self.bom)
        let utf8 = Array(bytes[(hasBOM ? 3 : 0)...])
        self.raw = raw
        self.hasBOM = hasBOM
        guard let text = String(validating: utf8, as: UTF8.self) else {
            self.text = nil
            self.utf8 = []
            self.newline = .lf
            self.frontmatter = nil
            self.body = 0..<0
            return
        }
        self.text = text
        self.utf8 = utf8
        self.newline = Self.dominantNewline(utf8)
        (self.frontmatter, self.body) = Self.frontmatterSpan(utf8)
    }

    /// The text of `span` (nil for a read-only note).
    public func text(of span: Range<Int>) -> String? {
        text == nil ? nil : String(decoding: utf8[span], as: UTF8.self)
    }

    public var frontmatterText: String? { frontmatter.flatMap { text(of: $0) } }
    public var bodyText: String? { text(of: body) }

    /// The note's bytes with `span` replaced by `new`, verbatim; everything else is kept byte
    /// for byte. Text OpenNote generates goes through `withNewlines` first, so it follows the
    /// note's dominant line ending; text from an editor keeps its own endings.
    public func replacing(_ span: Range<Int>, with new: String) throws(ReadOnlyNote) -> Data {
        guard text != nil else { throw ReadOnlyNote() }
        var out = Data(hasBOM ? Self.bom : [])
        out.append(contentsOf: utf8[..<span.lowerBound])
        out.append(contentsOf: Array(new.utf8))
        out.append(contentsOf: utf8[span.upperBound...])
        return out
    }

    private static func dominantNewline(_ b: [UInt8]) -> LineEnding {
        var lf = 0
        var crlf = 0
        for i in b.indices where b[i] == 0x0A {
            lf += 1
            if i > 0 && b[i - 1] == 0x0D { crlf += 1 }
        }
        return crlf > lf - crlf ? .crlf : .lf
    }

    /// End of the line starting at `start` (without its ending) and start of the next.
    private static func lineEnd(_ b: [UInt8], _ start: Int) -> (Int, Int) {
        guard let end = b[start...].firstIndex(of: 0x0A) else { return (b.count, b.count) }
        let contentEnd = end > start && b[end - 1] == 0x0D ? end - 1 : end
        return (contentEnd, end + 1)
    }

    private static func frontmatterSpan(_ b: [UInt8]) -> (Range<Int>?, Range<Int>) {
        let whole = 0..<b.count
        let (firstEnd, next) = lineEnd(b, 0)
        guard b[0..<firstEnd].elementsEqual("---".utf8), next != firstEnd else { return (nil, whole) }
        var pos = next
        while pos < b.count {
            let (end, following) = lineEnd(b, pos)
            let line = b[pos..<end]
            if line.elementsEqual("---".utf8) || line.elementsEqual("...".utf8) {
                return (next..<pos, following..<b.count)
            }
            pos = following
        }
        return (nil, whole)
    }
}

/// `text` with every line ending made `newline`: for new lines OpenNote inserts.
public func withNewlines(_ text: String, _ newline: LineEnding) -> String {
    text.replacingOccurrences(of: "\r\n", with: "\n")
        .replacingOccurrences(of: "\n", with: newline.rawValue)
}
