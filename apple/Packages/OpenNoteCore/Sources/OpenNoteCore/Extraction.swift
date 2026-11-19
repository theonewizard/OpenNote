import Foundation
import cmark_gfm

/// One outgoing link or embed (storage contract §2.3).
public struct Link: Sendable, Equatable {
    /// Without `#heading`, `#^block` and `|alias`; "" for a link to a heading in this note.
    public let target: String
    public let heading: String?
    public let block: String?
    /// Also an embed's size, as in `![[image.png|300]]`.
    public let alias: String?
    public let embed: Bool
    /// `[text](path)` rather than `[[wiki]]`.
    public let markdown: Bool

    public init(target: String, heading: String?, block: String?, alias: String?, embed: Bool, markdown: Bool) {
        self.target = target
        self.heading = heading
        self.block = block
        self.alias = alias
        self.embed = embed
        self.markdown = markdown
    }
}

public struct Extraction: Sendable, Equatable {
    public var links: [Link] = []
    public var tags: [String] = []
    public var externalURLs: [String] = []
}

/// Read-only extraction of links, embeds and tags from a note body, the Swift twin of
/// `backend/app/notes/extract.py`.
///
/// Code (fenced, indented), HTML blocks, HTML comments, `%%comments%%` and inline code are
/// masked out first, keeping offsets, then the same regular expressions run over what is
/// left. Blocks come from cmark (CommonMark, no extensions), as markdown-it's CommonMark
/// preset finds them in Python. Offsets are Unicode scalars, Python's code points.
public enum Extractor {
    // Python's `\s` in a str pattern, spelled out (ICU's `\s` is a different set).
    private static let space = "\\t\\n\\u000b\\f\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000"
    private static let inlineCode = regex("(`+)(?!`).+?(?<!`)\\1(?!`)", dotAll: true)
    private static let htmlComment = regex("<!--.*?-->", dotAll: true)
    private static let obsidianComment = regex("%%.*?%%", dotAll: true)
    private static let wiki = regex("(!?)\\[\\[([^\\[\\]\\n]+?)\\]\\]")
    private static let markdownLink = regex("(!?)\\[([^\\]\\n]*)\\]\\((?:<([^>\\n]*)>|([^)\(space)]*))\\)")
    private static let scheme = regex("^[A-Za-z][A-Za-z0-9+.-]*:")
    // Python's `^` with MULTILINE is "start, or after \n"; `\n` is in `space`, so the
    // lookbehind covers it and `^` stays the start of the input.
    private static let tag = regex(
        "(?:(?<=[\(space)])|^)#([^\(space)#!\"$%\\&'()*+,.:;<=>?@\\[\\\\\\]\\^`{|}~]+)")

    private static func regex(_ pattern: String, dotAll: Bool = false) -> NSRegularExpression {
        // swiftlint:disable:next force_try
        try! NSRegularExpression(pattern: pattern, options: dotAll ? [.dotMatchesLineSeparators] : [])
    }

    public static func extract(_ doc: NoteDocument) -> Extraction {
        guard let bodyText = doc.bodyText else { return Extraction() }
        let body = ScalarText(mask(bodyText))
        var found: [(Int, Link)] = body.matches(wiki).map { ($0.range.lowerBound, wikiLink(body, $0)) }
        var urls: [(Int, String)] = []
        for m in body.matches(markdownLink) {
            let url = body.group(m, 3) ?? body.group(m, 4) ?? ""
            if !ScalarText(url).matches(scheme).isEmpty {
                urls.append((m.range.lowerBound, url))
                continue
            }
            let (target, heading, block) = splitTarget(unquote(url))
            let text = body.group(m, 2) ?? ""
            found.append((m.range.lowerBound, Link(
                target: target, heading: heading, block: block, alias: text.isEmpty ? nil : text,
                embed: body.group(m, 1) == "!", markdown: true)))
        }
        let tags = body.matches(tag).compactMap { body.group($0, 1) }.filter { !$0.isPyDigit }
        return Extraction(
            links: found.enumerated().sorted { ($0.element.0, $0.offset) < ($1.element.0, $1.offset) }
                .map(\.element.1),
            tags: tags,
            externalURLs: urls.sorted { ($0.0, $0.1) < ($1.0, $1.1) }.map(\.1))
    }

    // MARK: - Masking

    static func mask(_ body: String) -> [Unicode.Scalar] {
        var text = Array(body.unicodeScalars)
        let starts = lineStarts(text)
        for (begin, end) in maskedBlockLines(body) {
            blank(&text, starts[min(begin, starts.count - 1)], starts[min(end, starts.count - 1)])
        }
        for pattern in [obsidianComment, htmlComment, inlineCode] {
            let current = ScalarText(text)
            for m in current.matches(pattern) { blank(&text, m.range.lowerBound, m.range.upperBound) }
        }
        return text
    }

    /// `[start, end)` replaced by spaces, newlines kept, so offsets stay put.
    private static func blank(_ text: inout [Unicode.Scalar], _ start: Int, _ end: Int) {
        guard start < end else { return }
        for i in start..<end where text[i] != "\n" { text[i] = " " }
    }

    /// Start offsets of the lines as Python's `str.splitlines(keepends=True)` cuts them, plus
    /// the end of the text: the line numbers below index into this list.
    private static func lineStarts(_ text: [Unicode.Scalar]) -> [Int] {
        var starts = [0]
        var i = 0
        while i < text.count {
            let v = text[i].value
            if v == 0x0D && i + 1 < text.count && text[i + 1] == "\n" {
                i += 2
                starts.append(i)
                continue
            }
            i += 1
            if [0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029].contains(v) {
                starts.append(i)
            }
        }
        if starts.last != text.count { starts.append(text.count) }
        return starts
    }

    /// Zero-based `[begin, end)` line ranges of code blocks and HTML blocks.
    private static func maskedBlockLines(_ body: String) -> [(Int, Int)] {
        let bytes = Array(body.utf8)
        guard !bytes.isEmpty else { return [] }
        let document = bytes.withUnsafeBufferPointer { buffer in
            buffer.withMemoryRebound(to: CChar.self) { cmark_parse_document($0.baseAddress, $0.count, 0) }
        }
        guard let document else { return [] }
        defer { cmark_node_free(document) }
        let iterator = cmark_iter_new(document)
        defer { cmark_iter_free(iterator) }
        var lines: [(Int, Int)] = []
        while true {
            let event = cmark_iter_next(iterator)
            if event == CMARK_EVENT_DONE { break }
            guard event == CMARK_EVENT_ENTER, let node = cmark_iter_get_node(iterator) else { continue }
            let type = cmark_node_get_type(node)
            if type == CMARK_NODE_CODE_BLOCK || type == CMARK_NODE_HTML_BLOCK {
                let start = Int(cmark_node_get_start_line(node)) - 1
                let end = Int(cmark_node_get_end_line(node))
                if start >= 0 && end > start { lines.append((start, end)) }
            }
        }
        return lines
    }

    // MARK: - Links

    private static func wikiLink(_ body: ScalarText, _ m: ScalarText.Match) -> Link {
        // [[target#heading|alias]]; `\|` is the pipe escaped inside a table cell.
        let inner = Array((body.group(m, 2) ?? "").unicodeScalars)
        var targetPart = inner[...]
        var alias: String?
        if let bar = inner.firstIndex(of: "|") {
            let cut = bar > 0 && inner[bar - 1] == "\\" ? bar - 1 : bar
            targetPart = inner[..<cut]
            alias = String(String.UnicodeScalarView(inner[(bar + 1)...]))
        }
        let (target, heading, block) = splitTarget(String(String.UnicodeScalarView(targetPart)))
        return Link(target: target, heading: heading, block: block, alias: alias,
                    embed: body.group(m, 1) == "!", markdown: false)
    }

    private static func splitTarget(_ raw: String) -> (String, String?, String?) {
        let scalars = raw.unicodeScalars
        guard let hash = scalars.firstIndex(of: "#") else { return (raw.pyStrip(), nil, nil) }
        let target = String(scalars[..<hash]).pyStrip()
        let rest = String(scalars[scalars.index(after: hash)...])
        if rest.unicodeScalars.first == "^" {
            return (target, nil, String(rest.unicodeScalars.dropFirst()).pyStrip())
        }
        return (target, rest.pyStrip(), nil)
    }

    /// Python's `urllib.parse.unquote`: `%XX` sequences decoded as UTF-8, invalid bytes
    /// replaced with U+FFFD.
    static func unquote(_ s: String) -> String {
        guard s.contains("%") else { return s }
        var bytes: [UInt8] = []
        let utf8 = Array(s.utf8)
        var i = 0
        while i < utf8.count {
            if utf8[i] == UInt8(ascii: "%"), i + 2 < utf8.count,
               let high = hexValue(utf8[i + 1]), let low = hexValue(utf8[i + 2]) {
                bytes.append(high << 4 | low)
                i += 3
            } else {
                bytes.append(utf8[i])
                i += 1
            }
        }
        return String(decoding: bytes, as: UTF8.self)
    }

    private static func hexValue(_ c: UInt8) -> UInt8? {
        switch c {
        case UInt8(ascii: "0")...UInt8(ascii: "9"): c - UInt8(ascii: "0")
        case UInt8(ascii: "a")...UInt8(ascii: "f"): c - UInt8(ascii: "a") + 10
        case UInt8(ascii: "A")...UInt8(ascii: "F"): c - UInt8(ascii: "A") + 10
        default: nil
        }
    }
}

/// Text as an array of Unicode scalars, with regex matches reported in scalar offsets.
struct ScalarText {
    struct Match {
        let range: Range<Int>
        let groups: [Range<Int>?]
    }

    let scalars: [Unicode.Scalar]
    let string: String

    init(_ scalars: [Unicode.Scalar]) {
        self.scalars = scalars
        var view = String.UnicodeScalarView()
        view.append(contentsOf: scalars)
        string = String(view)
    }

    init(_ string: String) { self.init(Array(string.unicodeScalars)) }

    func matches(_ re: NSRegularExpression) -> [Match] {
        let results = re.matches(in: string, range: NSRange(location: 0, length: string.utf16.count))
        guard !results.isEmpty else { return [] }
        // UTF-16 offset to scalar offset.
        var map: [Int] = []
        map.reserveCapacity(string.utf16.count + 1)
        for (i, s) in scalars.enumerated() {
            map.append(i)
            if s.value > 0xFFFF { map.append(i) }
        }
        map.append(scalars.count)
        func convert(_ r: NSRange) -> Range<Int>? {
            r.location == NSNotFound ? nil : map[r.location]..<map[r.location + r.length]
        }
        return results.map { result in
            Match(range: convert(result.range)!,
                  groups: (0..<result.numberOfRanges).map { convert(result.range(at: $0)) })
        }
    }

    func group(_ m: Match, _ i: Int) -> String? {
        m.groups[i].map { String(String.UnicodeScalarView(scalars[$0])) }
    }
}

extension String {
    /// Python's `str.isdigit()`: every character has Numeric_Type Decimal or Digit.
    var isPyDigit: Bool {
        !isEmpty && unicodeScalars.allSatisfy {
            $0.properties.numericType == .decimal || $0.properties.numericType == .digit
        }
    }
}
