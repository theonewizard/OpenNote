import SwiftUI

@main
struct OpenNoteApp: App {
    var body: some Scene {
        WindowGroup(id: "main") {
            RootView()
                // A capture link goes to a window that is already open, not to a new one.
                .handlesExternalEvents(preferring: ["*"], allowing: ["*"])
        }
        .commands { AppCommands() }
        Settings {
            AccountView()
                .frame(width: 460)
        }
    }
}
