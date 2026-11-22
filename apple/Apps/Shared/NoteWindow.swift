import Foundation
import Observation
import OpenNoteCore
import OpenNoteEditor
import OpenNoteStorage

/// What the folder list has selected.
enum FolderChoice: Hashable {
    case all
    case folder(String)
}

/// One window's state: the folder and note it shows, the note being edited, and the actions
/// the toolbar and the menus share.
@MainActor @Observable
final class NoteWindow {
    private let app = AppModel.shared

    var folder: FolderChoice? = .all
    /// The selected note's path; setting it saves the open note and opens the new one.
    var selection: String? { didSet { if selection != openPath { open(selection) } } }
    var search = ""
    var searching = false
    private(set) var matches: Set<String>?

    private(set) var openPath: String?
    private(set) var document = EditorDocument(data: Data())
    /// The note changed on disk while it has unsaved edits here; nothing is overwritten.
    private(set) var changedElsewhere = false
    /// The hash of the bytes the editor loaded or last saved, and the text they held.
    private var base: String?
    private var savedText = ""
    private var saveTask: Task<Void, Never>?

    var renameText = ""
    var showRename = false
    var showDelete = false
    var showAttach = false

    // MARK: - Lists

    var notes: [ScannedFile] {
        if let matches { return app.notes.filter { matches.contains($0.path) } }
        guard case let .folder(folder) = folder else { return app.notes }
        return app.notes.filter { Self.folder(of: $0.path) == folder }
    }

    static func folder(of path: String) -> String {
        path.split(separator: "/").dropLast().joined(separator: "/")
    }

    static func title(of path: String) -> String {
        let name = path.split(separator: "/").last.map(String.init) ?? path
        return name.lowercased().hasSuffix(".md") ? String(name.dropLast(3)) : name
    }

    /// Notes whose name or text contains the search text.
    func runSearch() async {
        let query = search.trimmingCharacters(in: .whitespaces)
        guard !query.isEmpty, let vault = app.vault else {
            matches = nil
            return
        }
        let found = await Self.search(vault, app.notes.map(\.path), for: query)
        if !Task.isCancelled { matches = found }
    }

    // ponytail: reads every note on each search; an FTS5 table in the state database is the
    // upgrade when a vault is large enough for this to be slow.
    @concurrent private static func search(_ vault: Vault, _ paths: [String], for query: String) async -> Set<String> {
        var found = Set<String>()
        for path in paths where !Task.isCancelled {
            if path.localizedCaseInsensitiveContains(query) {
                found.insert(path)
            } else if let data = try? vault.read(path),
                      String(decoding: data, as: UTF8.self).localizedCaseInsensitiveContains(query) {
                found.insert(path)
            }
        }
        return found
    }

    // MARK: - The open note

    var isDirty: Bool { openPath != nil && !document.isReadOnly && document.text != savedText }

    private func open(_ path: String?) {
        saveOrKeepCopy()
        saveTask?.cancel()
        changedElsewhere = false
        guard let path, let vault = app.vault else {
            openPath = nil
            return
        }
        do {
            let data = try vault.read(path)
            document = EditorDocument(data: data)
            base = ContentHash.sha256(data)
            savedText = document.text
            openPath = path
        } catch {
            openPath = nil
            selection = nil
            app.report(error)
        }
    }

    /// The editor's binding: every keystroke lands here; the note is saved 1.5 s after the last.
    func edited(_ new: EditorDocument) {
        document = new
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .seconds(1.5))
            if !Task.isCancelled { save() }
        }
    }

    /// Writes the note if it has unsaved edits and the file is still the one that was loaded.
    func save() {
        guard isDirty, !changedElsewhere, let path = openPath, let vault = app.vault else { return }
        do {
            let written = try vault.write(path, try document.data(), expectedBase: base)
            base = written.contentHash
            savedText = document.text
            app.changed()
        } catch VaultError.externalChange {
            changedElsewhere = true
        } catch {
            app.report(error)
        }
    }

    /// Leaving the note (another note, the window, the app going away): saves it, and if the
    /// file changed elsewhere, keeps the edits as a new note beside it. They are never dropped
    /// without the user asking (`reloadFromDisk`).
    func saveOrKeepCopy() {
        save()
        guard isDirty, let path = openPath, let data = try? document.data() else { return }
        do {
            _ = try app.create(String(path.dropLast(3)) + " (unsaved edits).md", data)
            savedText = document.text
        } catch {
            app.report(error)
        }
    }

    /// Takes the version on disk, dropping the edits made here.
    func reloadFromDisk() {
        savedText = document.text
        open(openPath)
    }

    /// The folder was rescanned: follow a change to the open note made outside this window
    /// (a pulled revision, Obsidian, another window). The file itself is asked, not the scan,
    /// which may be older than this window's last save.
    func folderChanged() {
        guard let path = openPath, let vault = app.vault else { return }
        let current = (try? vault.currentHash(path)) ?? nil
        guard current != base else { return }
        // Unsaved edits stay in the editor until the user decides.
        if isDirty { changedElsewhere = true } else if current == nil { selection = nil } else { open(path) }
    }

    // MARK: - Actions

    func newNote() {
        var prefix = ""
        if case let .folder(folder) = folder { prefix = folder + "/" }
        do {
            let path = try app.create(prefix + "Untitled.md", Data())
            search = ""
            matches = nil
            selection = path
        } catch {
            app.report(error)
        }
    }

    func beginRename() {
        guard let path = openPath else { return }
        renameText = String(path.dropLast(path.lowercased().hasSuffix(".md") ? 3 : 0))
        showRename = true
    }

    /// Moves the note to `renameText` (`Folder/Name`), creating folders as needed.
    func rename() {
        guard let old = openPath, let vault = app.vault else { return }
        let segments = renameText.split(separator: "/").map { VaultPath.sanitizedName(String($0)) }
        guard let last = segments.last else { return }
        let target = (segments.dropLast() + [VaultPath.sanitizedName(last + ".md", note: true)]).joined(separator: "/")
        guard target != old else { return }
        save()
        do {
            guard try vault.currentHash(target) == nil else {
                app.errorMessage = "There is already a file with that name."
                return
            }
            let data = try vault.read(old)
            try vault.write(target, data, expectedBase: nil)
            try vault.delete(old, expectedBase: ContentHash.sha256(data))
            openPath = target  // the same note at its new path: keep the editor as it is
            selection = target
            app.changed()
        } catch {
            app.report(error)
        }
    }

    /// Moves the note to the recovery area, unsaved edits included.
    func delete() {
        guard let path = openPath, let vault = app.vault, let base else { return }
        saveTask?.cancel()
        do {
            try vault.delete(path, expectedBase: base)
            savedText = document.text
            selection = nil
            app.changed()
        } catch {
            app.report(error)
        }
    }

    /// Copies files next to the open note and embeds each one in it.
    func attach(_ urls: [URL]) {
        for url in urls {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                // Mapped, not read: a large attachment is paged in as it is written out.
                attach(try Data(contentsOf: url, options: .mappedIfSafe), named: url.lastPathComponent)
            } catch {
                app.report(error)
            }
        }
    }

    func attach(_ data: Data, named name: String) {
        guard let note = openPath, !document.isReadOnly else { return }
        let folder = Self.folder(of: note)
        do {
            let path = try app.create((folder.isEmpty ? "" : folder + "/") + VaultPath.sanitizedName(name), data)
            let leaf = path.split(separator: "/").last.map(String.init) ?? path
            var new = document
            let lineBreak = document.insertion("\n")
            // ponytail: appended, not inserted at the cursor; the editor's binding carries
            // text only. Hand the selection through MarkdownEditor when that matters.
            new.text += (new.text.isEmpty || new.text.hasSuffix("\n") ? "" : lineBreak) + "![[\(leaf)]]" + lineBreak
            edited(new)
        } catch {
            app.report(error)
        }
    }
}
