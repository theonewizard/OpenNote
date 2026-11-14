import Foundation
import OpenNoteCore
@testable import OpenNoteEditor
import Testing

#if canImport(AppKit)
import AppKit
#endif

let corpus = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("tests/compatibility/vaults")

func corpusNotes() -> [String] {
    let names = (try? FileManager.default.contentsOfDirectory(atPath: corpus.path)) ?? []
    return names.filter {
        FileManager.default.fileExists(atPath: corpus.appendingPathComponent("\($0)/note.md").path)
    }.sorted()
}

func note(_ name: String) throws -> Data {
    try Data(contentsOf: corpus.appendingPathComponent("\(name)/note.md"))
}

@Suite struct EditorDocumentTests {
    @Test(arguments: corpusNotes())
    func unchangedTextSavesTheOriginalBytes(_ name: String) throws {
        let raw = try note(name)
        let doc = EditorDocument(data: raw)
        if doc.isReadOnly {
            #expect(throws: ReadOnlyNote.self) { try doc.data() }
        } else {
            #expect(try doc.data() == raw)
            #expect(!doc.isModified)
        }
    }

    @Test func typedLineBreaksFollowTheNotesLineEnding() {
        let crlf = EditorDocument(data: Data("a\r\nb\r\n".utf8))
        #expect(crlf.insertion("\n") == "\r\n")
        #expect(crlf.insertion("x\ny\r\nz\rw") == "x\r\ny\r\nz\r\nw")
        #expect(crlf.insertion("plain") == "plain")
        let lf = EditorDocument(data: Data("a\nb\n".utf8))
        #expect(lf.insertion("p\r\nq") == "p\nq")
    }

    @Test func anEditChangesOnlyItsOwnBytes() throws {
        let raw = Data("\u{FEFF}---\r\ntags: [a]\r\n---\r\nmixed\nendings\r\nno newline".utf8)
        var doc = EditorDocument(data: raw)
        doc.text = doc.text.replacingOccurrences(of: "mixed", with: "MIXED")
        #expect(try doc.data() == Data("\u{FEFF}---\r\ntags: [a]\r\n---\r\nMIXED\nendings\r\nno newline".utf8))
    }
}

@Suite struct StylerTests {
    func styles(_ text: String) -> [(String, MarkdownStyle)] {
        let ns = text as NSString
        return MarkdownStyler.runs(in: text).map { (ns.substring(with: $0.range), $0.style) }
    }

    @Test func headingsLinksTagsAndCode() {
        let found = styles("# Title\n[[Note|alias]] #tag #123 `#not` [x](y.md)\n")
        #expect(found.contains { $0 == ("# Title", .heading(1)) })
        #expect(found.contains { $0 == ("[[Note|alias]]", .wikiLink) })
        #expect(found.contains { $0 == ("#tag", .tag) })
        #expect(!found.contains { $0.0 == "#123" })
        #expect(found.contains { $0 == ("`#not`", .inlineCode) })
        #expect(found.contains { $0 == ("[x](y.md)", .link) })
    }

    @Test func fencedCodeAndFrontmatterCoverWholeBlocks() {
        let found = styles("---\ntags: [a]\n---\ntext\n```swift\nlet x = 1\n```\nafter\n")
        #expect(found.contains { $0 == ("---\ntags: [a]\n---\n", .frontmatter) })
        #expect(found.contains { $0 == ("```swift\nlet x = 1\n```\n", .codeBlock) })
    }

    @Test func runsStayInsideTheTextWithAstralCharacters() {
        let text = "😀 **bold** [[😀]] #😀"
        let length = (text as NSString).length
        #expect(MarkdownStyler.runs(in: text).allSatisfy { NSMaxRange($0.range) <= length })
    }
}

#if canImport(AppKit)
/// The real TextKit 2 view (macOS): loading, styling and typing never change bytes that were
/// not edited (P4-04 acceptance: corpus edits preserve bytes).
@MainActor @Suite struct TextKitTests {
    @Test(arguments: corpusNotes())
    func corpusNotesSurviveTheTextViewByteForByte(_ name: String) throws {
        let raw = try note(name)
        let controller = MarkdownEditorController(document: EditorDocument(data: raw))
        controller.restyle()
        var doc = EditorDocument(data: raw)
        doc.text = controller.textView.string
        if !doc.isReadOnly {
            #expect(try doc.data() == raw)
        }
        #expect(controller.textView.isEditable == !doc.isReadOnly)
    }

    @Test func typingReturnInACRLFNoteInsertsCRLFAndNothingElseChanges() throws {
        let raw = try note("fm-crlf")
        let controller = MarkdownEditorController(document: EditorDocument(data: raw))
        let view = controller.textView
        let end = (view.string as NSString).length
        view.setSelectedRange(NSRange(location: end, length: 0))
        view.insertText("\nadded", replacementRange: view.selectedRange())
        var expected = raw
        expected.append(Data("\r\nadded".utf8))
        #expect(try controller.document.data() == expected)
    }

}
#endif
