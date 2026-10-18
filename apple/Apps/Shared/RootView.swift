import OpenNoteCore
import SwiftUI

/// Placeholder for the three panes: sidebar, note list, note.
/// In compact width (iPhone) the split view collapses into a navigation stack.
struct RootView: View {
    var body: some View {
        NavigationSplitView {
            List {
                Text("No vaults yet")
                    .foregroundStyle(.secondary)
                LabeledContent("Version", value: OpenNoteCore.version)
            }
            .navigationTitle("OpenNote")
        } content: {
            ContentUnavailableView("No Notes", systemImage: "note.text")
        } detail: {
            ContentUnavailableView("No Note Selected", systemImage: "doc.text")
        }
    }
}
