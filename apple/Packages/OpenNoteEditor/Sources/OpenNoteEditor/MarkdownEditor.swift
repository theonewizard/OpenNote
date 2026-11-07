#if canImport(AppKit) || canImport(UIKit)
import Foundation
import OpenNoteCore
import SwiftUI

#if canImport(AppKit)
import AppKit
public typealias PlatformTextView = NSTextView
typealias PlatformFont = NSFont
typealias PlatformColor = NSColor
#else
import UIKit
public typealias PlatformTextView = UITextView
typealias PlatformFont = UIFont
typealias PlatformColor = UIColor
#endif

/// Fonts and colours for each Markdown style.
public struct MarkdownTheme: Sendable {
    public var fontSize: CGFloat

    public init(fontSize: CGFloat = 15) { self.fontSize = fontSize }

    var base: [NSAttributedString.Key: Any] {
        [.font: PlatformFont.systemFont(ofSize: fontSize), .foregroundColor: Self.label]
    }

    func attributes(for style: MarkdownStyle) -> [NSAttributedString.Key: Any] {
        switch style {
        case let .heading(level):
            let size = fontSize * [1.6, 1.4, 1.25, 1.15, 1.05, 1.0][max(0, min(level - 1, 5))]
            return [.font: PlatformFont.systemFont(ofSize: size, weight: .bold)]
        case .strong: return [.font: PlatformFont.systemFont(ofSize: fontSize, weight: .bold)]
        case .emphasis: return [.obliqueness: 0.2]
        case .strikethrough: return [.strikethroughStyle: NSUnderlineStyle.single.rawValue]
        case .inlineCode, .codeBlock:
            return [.font: PlatformFont.monospacedSystemFont(ofSize: fontSize * 0.95, weight: .regular)]
        case .quote, .comment, .frontmatter, .marker: return [.foregroundColor: Self.secondary]
        case .link, .wikiLink, .embed, .tag: return [.foregroundColor: Self.accent]
        }
    }

    #if canImport(AppKit)
    static var label: PlatformColor { .labelColor }
    static var secondary: PlatformColor { .secondaryLabelColor }
    static var accent: PlatformColor { .controlAccentColor }
    #else
    static var label: PlatformColor { .label }
    static var secondary: PlatformColor { .secondaryLabel }
    static var accent: PlatformColor { .tintColor }
    #endif
}

/// Owns a TextKit 2 text view showing one note. The view's string is the note's text and
/// nothing else: styling sets attributes only, typed line breaks follow the note's line
/// ending, and every automatic substitution (smart quotes, dashes, text replacement,
/// autocorrection) is off, so what the user did not type never changes.
@MainActor
public final class MarkdownEditorController: NSObject {
    public let textView: PlatformTextView
    public private(set) var document: EditorDocument
    public var theme: MarkdownTheme { didSet { restyle() } }
    /// Called after every edit with the updated document.
    public var onChange: ((EditorDocument) -> Void)?

    public init(document: EditorDocument, theme: MarkdownTheme = MarkdownTheme()) {
        self.document = document
        self.theme = theme
        #if canImport(AppKit)
        textView = NSTextView(usingTextLayoutManager: true)
        #else
        textView = UITextView(usingTextLayoutManager: true)
        #endif
        super.init()
        configure()
        load(document)
    }

    /// Shows `document`, replacing whatever the view held (a reload after an outside change).
    public func load(_ document: EditorDocument) {
        self.document = document
        #if canImport(AppKit)
        textView.string = document.text
        #else
        textView.text = document.text
        #endif
        textView.isEditable = !document.isReadOnly
        restyle()
    }

    /// Re-applies the styling attributes over the whole text.
    public func restyle() {
        guard let storage = textStorage else { return }
        let text = storage.string
        let all = NSRange(location: 0, length: (text as NSString).length)
        storage.beginEditing()
        storage.setAttributes(theme.base, range: all)
        for run in MarkdownStyler.runs(in: text) where NSMaxRange(run.range) <= all.length {
            storage.addAttributes(theme.attributes(for: run.style), range: run.range)
        }
        storage.endEditing()
    }

    private var textStorage: NSTextStorage? {
        #if canImport(AppKit)
        textView.textStorage
        #else
        textView.textStorage
        #endif
    }

    private var currentText: String {
        #if canImport(AppKit)
        textView.string
        #else
        textView.text ?? ""
        #endif
    }

    private func configure() {
        textView.delegate = self
        #if canImport(AppKit)
        textView.isRichText = false
        textView.allowsUndo = true
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        textView.isAutomaticSpellingCorrectionEnabled = false
        textView.isAutomaticLinkDetectionEnabled = false
        textView.isAutomaticDataDetectionEnabled = false
        textView.isAutomaticTextCompletionEnabled = false
        textView.smartInsertDeleteEnabled = false
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.textContainerInset = NSSize(width: 12, height: 12)
        #else
        textView.autocorrectionType = .no
        textView.autocapitalizationType = .none
        textView.smartQuotesType = .no
        textView.smartDashesType = .no
        textView.smartInsertDeleteType = .no
        textView.dataDetectorTypes = []
        textView.alwaysBounceVertical = true
        textView.textContainerInset = UIEdgeInsets(top: 12, left: 8, bottom: 12, right: 8)
        #endif
    }

    /// The text to insert instead of `replacement`, or nil to let it through unchanged.
    func adjusted(_ replacement: String) -> String? {
        let fixed = document.insertion(replacement)
        return fixed == replacement ? nil : fixed
    }

    func textChanged() {
        document.text = currentText
        restyle()
        onChange?(document)
    }
}

#if canImport(AppKit)
extension MarkdownEditorController: NSTextViewDelegate {
    public func textView(_ textView: NSTextView, shouldChangeTextIn range: NSRange,
                         replacementString: String?) -> Bool {
        guard let replacementString, let fixed = adjusted(replacementString) else { return true }
        // Re-enters this method with `fixed`, which needs no adjustment; undo records it.
        if textView.shouldChangeText(in: range, replacementString: fixed) {
            textView.textStorage?.replaceCharacters(in: range, with: fixed)
            textView.setSelectedRange(NSRange(location: range.location + (fixed as NSString).length, length: 0))
            textView.didChangeText()
        }
        return false
    }

    public func textDidChange(_ notification: Notification) { textChanged() }
}

/// The editor in SwiftUI (macOS), bound to an `EditorDocument`.
public struct MarkdownEditor: NSViewRepresentable {
    @Binding public var document: EditorDocument
    public var theme: MarkdownTheme

    public init(document: Binding<EditorDocument>, theme: MarkdownTheme = MarkdownTheme()) {
        _document = document
        self.theme = theme
    }

    public func makeCoordinator() -> MarkdownEditorController {
        MarkdownEditorController(document: document, theme: theme)
    }

    public func makeNSView(context: Context) -> NSScrollView {
        let controller = context.coordinator
        controller.onChange = { document = $0 }
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.documentView = controller.textView
        return scroll
    }

    public func updateNSView(_ view: NSScrollView, context: Context) {
        let controller = context.coordinator
        if controller.document != document { controller.load(document) }
    }
}
#else
extension MarkdownEditorController: UITextViewDelegate {
    public func textView(_ textView: UITextView, shouldChangeTextIn range: NSRange,
                         replacementText text: String) -> Bool {
        guard let fixed = adjusted(text),
              let start = textView.position(from: textView.beginningOfDocument, offset: range.location),
              let end = textView.position(from: start, offset: range.length),
              let textRange = textView.textRange(from: start, to: end) else { return true }
        textView.replace(textRange, withText: fixed)  // re-enters with `fixed`
        return false
    }

    public func textViewDidChange(_ textView: UITextView) { textChanged() }
}

/// The editor in SwiftUI (iOS, iPadOS), bound to an `EditorDocument`.
public struct MarkdownEditor: UIViewRepresentable {
    @Binding public var document: EditorDocument
    public var theme: MarkdownTheme

    public init(document: Binding<EditorDocument>, theme: MarkdownTheme = MarkdownTheme()) {
        _document = document
        self.theme = theme
    }

    public func makeCoordinator() -> MarkdownEditorController {
        MarkdownEditorController(document: document, theme: theme)
    }

    public func makeUIView(context: Context) -> UITextView {
        let controller = context.coordinator
        controller.onChange = { document = $0 }
        return controller.textView
    }

    public func updateUIView(_ view: UITextView, context: Context) {
        let controller = context.coordinator
        if controller.document != document { controller.load(document) }
    }
}
#endif
#endif
