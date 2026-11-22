import AppIntents
import SwiftUI

extension FocusedValues {
    /// The front window's state, for the menu commands.
    @Entry var noteWindow: NoteWindow?
}

/// The menus and their shortcuts (macOS menu bar; on iPad the same list is what holding ⌘
/// shows).
struct AppCommands: Commands {
    @FocusedValue(\.noteWindow) private var window
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("New Note") { window?.newNote() }
                .keyboardShortcut("n")
                .disabled(window == nil)
            Button("New Window") { openWindow(id: "main") }
                .keyboardShortcut("n", modifiers: [.command, .option])
        }
        CommandGroup(replacing: .saveItem) {
            Button("Save") { window?.save() }
                .keyboardShortcut("s")
                .disabled(window?.openPath == nil)
        }
        CommandMenu("Note") {
            Group {
                Button("Attach File…") { window?.showAttach = true }
                    .keyboardShortcut("a", modifiers: [.command, .shift])
                Button("Rename…") { window?.beginRename() }
                // No shortcut: ⌘⌫ in the editor deletes to the start of the line.
                Button("Delete") { window?.showDelete = true }
                #if os(macOS)
                Button("Show in Finder") {
                    if let path = window?.openPath, let root = AppModel.shared.vault?.root {
                        NSWorkspace.shared.activateFileViewerSelecting([root.appending(path: path)])
                    }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                #endif
            }
            .disabled(window?.openPath == nil)
            Divider()
            Button("Search Notes") { window?.searching = true }
                .keyboardShortcut("f", modifiers: [.command, .option])
                .disabled(window == nil)
            Button("Sync Now") { AppModel.shared.syncNow() }
                .keyboardShortcut("s", modifiers: [.command, .control])
        }
    }
}

/// Quick capture (P4-08): Shortcuts, Spotlight, Siri and the Action button save text as a
/// note in the Inbox folder without opening the app.
struct CaptureNoteIntent: AppIntent {
    static let title: LocalizedStringResource = "Capture Note"
    static let description = IntentDescription("Saves text as a new note in the Inbox folder of your vault.")

    @Parameter(title: "Text") var text: String

    @MainActor func perform() async throws -> some IntentResult {
        try AppModel.shared.capture(text)
        return .result()
    }
}

struct OpenNoteShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: CaptureNoteIntent(), phrases: ["Capture a note in \(.applicationName)"],
                    shortTitle: "Capture Note", systemImageName: "square.and.pencil")
    }
}
