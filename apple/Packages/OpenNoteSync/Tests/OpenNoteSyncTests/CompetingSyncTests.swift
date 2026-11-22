import Foundation
@testable import OpenNoteSync
import Testing

/// A vault folder at `path` under a fresh temp directory.
private func vault(_ path: String) throws -> URL {
    let root = FileManager.default.temporaryDirectory
        .appendingPathComponent("opennote-competing-\(UUID().uuidString)")
        .appendingPathComponent(path)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return root
}

private func write(_ text: String, to url: URL) throws {
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data(text.utf8).write(to: url)
}

@Test func plainFolderHasNoCompetingSync() throws {
    #expect(CompetingSync.detect(root: try vault("Users/ada/Notes")) == [])
}

@Test func iCloudDriveFolder() throws {
    let root = try vault("Users/ada/Library/Mobile Documents/com~apple~CloudDocs/Notes")
    #expect(CompetingSync.detect(root: root) == [.iCloudDrive])
}

@Test func fileProviderCloudFolderNamesTheProvider() throws {
    let root = try vault("Users/ada/Library/CloudStorage/Dropbox/Notes")
    #expect(CompetingSync.detect(root: root) == [.cloudStorage("Dropbox")])
}

@Test func olderDropboxFolder() throws {
    let root = try vault("Users/ada/Dropbox/Work/Notes")
    try write("{}", to: root.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(".dropbox"))
    #expect(CompetingSync.detect(root: root) == [.dropbox])
}

@Test func obsidianSyncSwitchedOn() throws {
    let root = try vault("Notes")
    let plugins = root.appendingPathComponent(".obsidian/core-plugins.json")
    try write(#"{"file-explorer": true, "sync": false}"#, to: plugins)
    #expect(CompetingSync.detect(root: root) == [])
    try write(#"{"file-explorer": true, "sync": true}"#, to: plugins)
    #expect(CompetingSync.detect(root: root) == [.obsidianSync])
    try write(#"["file-explorer", "sync"]"#, to: plugins)  // before Obsidian 1.0
    #expect(CompetingSync.detect(root: root) == [.obsidianSync])
}
