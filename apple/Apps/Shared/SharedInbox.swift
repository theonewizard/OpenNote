import Foundation

/// The App Group folder the share extension writes to and the app empties (P4-08). Built into
/// both targets.
enum SharedInbox {
    static let group = "group.dev.opennote.OpenNote"

    static var url: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group)?.appending(path: "Inbox")
    }
}
