import UIKit
import UniformTypeIdentifiers
import os

/// The share sheet's "OpenNote" (P4-08): saves the shared text and web address as one
/// Markdown file in the App Group inbox and closes. The app moves the file into the vault's
/// Inbox folder the next time it is active. The extension holds no token and never opens
/// the vault.
final class ShareViewController: UIViewController {
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        Task {
            await save()
            extensionContext?.completeRequest(returningItems: nil)
        }
    }

    private func save() async {
        var parts: [String] = []
        for item in extensionContext?.inputItems as? [NSExtensionItem] ?? [] {
            if let text = item.attributedContentText?.string { parts.append(text) }
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL {
                    parts.append(url.absoluteString)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                          let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
                    parts.append(text)
                }
            }
        }
        // The item's text and its plain-text attachment are usually the same string.
        var seen = Set<String>()
        // Capped like every capture (100 000 characters).
        let text = String(parts.filter { !$0.isEmpty && seen.insert($0).inserted }.joined(separator: "\n\n")
            .prefix(100_000))
        guard !text.isEmpty, let inbox = SharedInbox.url else { return }
        do {
            try FileManager.default.createDirectory(at: inbox, withIntermediateDirectories: true)
            try Data(text.utf8).write(to: inbox.appending(path: UUID().uuidString + ".md"), options: .atomic)
        } catch {
            Logger(subsystem: "dev.opennote.OpenNote", category: "share").error("shared item not saved: \(error)")
        }
    }
}
