import Foundation
import OpenNoteCore

/// The note an editor works on: its whole text (frontmatter included, as Obsidian's source
/// mode shows it) over the original bytes. Saving replaces the text after the BOM in one span
/// (`NoteDocument.replacing`), so untouched bytes, the BOM and every line ending the user did
/// not change come back exactly as they were read (storage contract §2.1, ADR-0008).
public struct EditorDocument: Sendable, Equatable {
    public let original: NoteDocument
    public var text: String

    public init(_ original: NoteDocument) {
        self.original = original
        text = original.text ?? ""
    }

    public init(data: Data) { self.init(NoteDocument(data)) }

    /// A note that is not valid UTF-8 is shown read-only and never written back.
    public var isReadOnly: Bool { original.isReadOnly }

    public var isModified: Bool { !isReadOnly && text != original.text }

    /// The bytes to save.
    public func data() throws(ReadOnlyNote) -> Data {
        guard let originalText = original.text else { throw ReadOnlyNote() }
        return try original.replacing(0..<originalText.utf8.count, with: text)
    }

    /// Text the user types or pastes, with its line breaks in the note's dominant ending, so
    /// Return in a CRLF note inserts CRLF (contract §2.1: OpenNote's new lines follow the file).
    public func insertion(_ typed: String) -> String {
        typed.unicodeScalars.contains(where: { $0 == "\n" || $0 == "\r" })
            ? withNewlines(typed.replacingOccurrences(of: "\r(?!\n)", with: "\n", options: .regularExpression),
                           original.newline)
            : typed
    }
}
