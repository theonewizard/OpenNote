import SwiftUI

@main
struct OpenNoteApp: App {
    var body: some Scene {
        WindowGroup(id: "main") {
            RootView()
        }
        .commands { AppCommands() }
    }
}
