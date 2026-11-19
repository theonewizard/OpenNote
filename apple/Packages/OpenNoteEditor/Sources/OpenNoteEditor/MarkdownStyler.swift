import Foundation
import OpenNoteCore

/// What a span of Markdown is, for live styling. Styling only sets attributes; the characters
/// are never touched.
public enum MarkdownStyle: Sendable, Equatable, Hashable {
    case frontmatter
    case heading(Int)
    case strong, emphasis, strikethrough
    case inlineCode, codeBlock
    case quote
    case link, wikiLink, embed
    case tag
    case comment
    /// `#`, `**`, `[[`, `]]` and the like, drawn dimmer than the text they mark.
    case marker
}

public struct StyleRun: Sendable, Equatable {
    /// UTF-16 range, as TextKit counts.
    public let range: NSRange
    public let style: MarkdownStyle

    public init(_ range: NSRange, _ style: MarkdownStyle) {
        self.range = range
        self.style = style
    }
}

/// Finds the spans to style in a note's text. Line-based and forgiving, like Obsidian's
/// source mode: it highlights, it never parses the note into a tree. Later runs win, so the
/// order below goes from broad (lines) to narrow (code, frontmatter).
public enum MarkdownStyler {
    private static func regex(_ p: String, _ o: NSRegularExpression.Options = []) -> NSRegularExpression {
        // swiftlint:disable:next force_try
        try! NSRegularExpression(pattern: p, options: o)
    }

    private static let heading = regex("^(#{1,6})[ \\t]+.*$", .anchorsMatchLines)
    private static let quote = regex("^[ ]{0,3}>.*$", .anchorsMatchLines)
    private static let fence = regex("^[ ]{0,3}(`{3,}|~{3,})")
    private static let strong = regex("(\\*\\*|__)(?=\\S)(.+?)(?<=\\S)\\1")
    private static let emphasis = regex("(?<![*_\\w])([*_])(?=[^\\s*_])(.+?)(?<=[^\\s*_])\\1(?![*_\\w])")
    private static let strike = regex("~~(?=\\S)(.+?)(?<=\\S)~~")
    private static let wiki = regex("(!?)(\\[\\[)([^\\[\\]\\n]+?)(\\]\\])")
    private static let mdLink = regex("(!?)\\[([^\\]\\n]*)\\]\\(([^)\\n]*)\\)")
    private static let tag = regex("(?<![^\\s])#[^\\s#!\"$%&'()*+,.:;<=>?@\\[\\\\\\]^`{|}~]+")
    private static let inlineCode = regex("(`+)(?!`)(.+?)(?<!`)\\1(?!`)")
    private static let comment = regex("%%.*?%%|<!--.*?-->", .dotMatchesLineSeparators)

    public static func runs(in text: String) -> [StyleRun] {
        let ns = text as NSString
        let all = NSRange(location: 0, length: ns.length)
        var runs: [StyleRun] = []

        for m in heading.matches(in: text, range: all) {
            runs.append(StyleRun(m.range, .heading(m.range(at: 1).length)))
            runs.append(StyleRun(m.range(at: 1), .marker))
        }
        for m in quote.matches(in: text, range: all) { runs.append(StyleRun(m.range, .quote)) }
        for m in strong.matches(in: text, range: all) { runs += marked(m, .strong) }
        for m in emphasis.matches(in: text, range: all) { runs += marked(m, .emphasis) }
        for m in strike.matches(in: text, range: all) { runs.append(StyleRun(m.range, .strikethrough)) }
        for m in mdLink.matches(in: text, range: all) {
            runs.append(StyleRun(m.range, m.range(at: 1).length > 0 ? .embed : .link))
        }
        for m in wiki.matches(in: text, range: all) {
            runs.append(StyleRun(m.range, m.range(at: 1).length > 0 ? .embed : .wikiLink))
            runs.append(StyleRun(NSUnionRange(m.range(at: 1), m.range(at: 2)), .marker))
            runs.append(StyleRun(m.range(at: 4), .marker))
        }
        for m in tag.matches(in: text, range: all) where !isNumeric(ns.substring(with: m.range).dropFirst()) {
            runs.append(StyleRun(m.range, .tag))
        }
        for m in inlineCode.matches(in: text, range: all) { runs.append(StyleRun(m.range, .inlineCode)) }
        for m in comment.matches(in: text, range: all) { runs.append(StyleRun(m.range, .comment)) }
        runs += codeBlocks(ns)
        if let frontmatter = frontmatterRange(text) { runs.append(StyleRun(frontmatter, .frontmatter)) }
        return runs
    }

    /// The whole match, with the delimiters in group 1 at both ends marked.
    private static func marked(_ m: NSTextCheckingResult, _ style: MarkdownStyle) -> [StyleRun] {
        let width = m.range(at: 1).length
        return [StyleRun(m.range, style),
                StyleRun(NSRange(location: m.range.location, length: width), .marker),
                StyleRun(NSRange(location: NSMaxRange(m.range) - width, length: width), .marker)]
    }

    private static func isNumeric(_ s: Substring) -> Bool { String(s).isPyDigitLike }

    /// Fenced code blocks: from an opening fence to a closing fence of the same character, at
    /// least as long, or to the end of the text.
    private static func codeBlocks(_ ns: NSString) -> [StyleRun] {
        var runs: [StyleRun] = []
        var open: (start: Int, marker: String)?
        var location = 0
        while location < ns.length {
            let line = ns.lineRange(for: NSRange(location: location, length: 0))
            let content = ns.substring(with: line)
            if let m = fence.firstMatch(in: content, range: NSRange(location: 0, length: (content as NSString).length)) {
                let marker = (content as NSString).substring(with: m.range(at: 1))
                if let current = open {
                    if marker.first == current.marker.first && marker.count >= current.marker.count
                        && content.trimmingCharacters(in: .whitespacesAndNewlines).allSatisfy({ $0 == marker.first }) {
                        runs.append(StyleRun(NSRange(location: current.start, length: NSMaxRange(line) - current.start), .codeBlock))
                        open = nil
                    }
                } else {
                    open = (line.location, marker)
                }
            }
            location = NSMaxRange(line)
        }
        if let current = open {
            runs.append(StyleRun(NSRange(location: current.start, length: ns.length - current.start), .codeBlock))
        }
        return runs
    }

    /// The frontmatter block, delimiters included, by the storage contract's rule (§2.2).
    private static func frontmatterRange(_ text: String) -> NSRange? {
        let doc = NoteDocument(Data(text.utf8))
        guard doc.frontmatter != nil else { return nil }
        // Through the closing delimiter line: the body starts right after it.
        let prefix = String(decoding: Array(text.utf8)[..<doc.body.lowerBound], as: UTF8.self)
        return NSRange(location: 0, length: (prefix as NSString).length)
    }
}

extension String {
    /// Every character is a decimal digit (`#123` is not a tag in Obsidian).
    var isPyDigitLike: Bool {
        !isEmpty && unicodeScalars.allSatisfy {
            $0.properties.numericType == .decimal || $0.properties.numericType == .digit
        }
    }
}
