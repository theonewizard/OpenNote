import Foundation

/// Another tool that syncs the same vault folder (roadmap P5-08). Two sync tools on one
/// folder each take the other's downloads for local edits and send them back, which ends in
/// duplicate conflict copies or edits arriving twice. The app warns when it finds one;
/// OpenNote still syncs, as only the user can tell which tool should go.
public enum CompetingSync: Equatable, Sendable {
    /// The folder is in iCloud Drive (`~/Library/Mobile Documents`).
    case iCloudDrive
    /// The folder is in a File Provider cloud folder (`~/Library/CloudStorage/<provider>`):
    /// Dropbox, OneDrive, Google Drive and others, named as the folder names them.
    case cloudStorage(String)
    /// The folder is inside a Dropbox folder of the older Dropbox app (a `.dropbox` file above it).
    case dropbox
    /// Obsidian Sync is switched on in the vault's `.obsidian/core-plugins.json`.
    case obsidianSync

    /// The competing tools found for the vault at `root`, from its path and files only.
    public static func detect(root: URL) -> [CompetingSync] {
        var found: [CompetingSync] = []
        let parts = root.resolvingSymlinksInPath().standardizedFileURL.pathComponents
        for (i, part) in parts.enumerated() where part == "Library" && i + 1 < parts.count {
            if parts[i + 1] == "Mobile Documents" {
                found.append(.iCloudDrive)
            } else if parts[i + 1] == "CloudStorage", i + 2 < parts.count {
                found.append(.cloudStorage(parts[i + 2]))
            }
        }
        var folder = root.resolvingSymlinksInPath().standardizedFileURL
        while true {
            if FileManager.default.fileExists(atPath: folder.appendingPathComponent(".dropbox").path) {
                found.append(.dropbox)
                break
            }
            let parent = folder.deletingLastPathComponent()
            if parent.path == folder.path { break }
            folder = parent
        }
        if obsidianSyncEnabled(root: root) { found.append(.obsidianSync) }
        return found
    }

    /// Obsidian writes `core-plugins.json` as an object of plugin ids to on/off, or (before
    /// 1.0) as an array of the ids that are on.
    static func obsidianSyncEnabled(root: URL) -> Bool {
        let file = root.appendingPathComponent(".obsidian/core-plugins.json")
        guard let data = try? Data(contentsOf: file),
              let json = try? JSONSerialization.jsonObject(with: data) else { return false }
        if let plugins = json as? [String: Any] { return plugins["sync"] as? Bool == true }
        if let plugins = json as? [String] { return plugins.contains("sync") }
        return false
    }
}
