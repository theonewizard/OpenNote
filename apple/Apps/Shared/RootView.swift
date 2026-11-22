import AuthenticationServices
import OpenNoteAPI
import OpenNoteCore
import OpenNoteEditor
import SwiftUI
import UniformTypeIdentifiers

/// The welcome screen until a vault is open, then the three panes: folders, notes, note.
/// In compact width (iPhone) the split view collapses into a navigation stack.
struct RootView: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var app = AppModel.shared
    @State private var window = NoteWindow()
    @State private var columns = NavigationSplitViewVisibility.all

    var body: some View {
        Group {
            if app.vault == nil {
                WelcomeView()
            } else {
                NavigationSplitView(columnVisibility: $columns) {
                    FolderList(window: window)
                } content: {
                    NoteList(window: window)
                } detail: {
                    NoteView(window: window)
                }
                .focusedSceneValue(\.noteWindow, window)
            }
        }
        .alert("OpenNote", isPresented: Binding(get: { app.errorMessage != nil }, set: { _ in app.errorMessage = nil })) {
            Button("OK") {}
        } message: {
            Text(app.errorMessage ?? "")
        }
        .onChange(of: scenePhase, initial: true) { _, phase in
            if phase == .active { app.activated() } else { window.saveOrKeepCopy() }
        }
        .onChange(of: app.revision) { window.folderChanged() }
        .onOpenURL { app.open($0) }
    }
}

struct FolderList: View {
    @Bindable var window: NoteWindow
    private let app = AppModel.shared
    @State private var showAccount = false

    var body: some View {
        List(selection: $window.folder) {
            Label("All Notes", systemImage: "tray.full").tag(FolderChoice.all)
            Section("Folders") {
                ForEach(app.folders, id: \.self) { folder in
                    Label(folder, systemImage: "folder").tag(FolderChoice.folder(folder))
                }
            }
        }
        .navigationTitle(app.vaultName)
        .safeAreaInset(edge: .bottom) {
            Text(app.statusText)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal)
                .padding(.vertical, 6)
                .accessibilityIdentifier("sync-status")
        }
        #if os(iOS)
        .toolbar {
            Button("Account", systemImage: "person.crop.circle") { showAccount = true }
        }
        .sheet(isPresented: $showAccount) {
            NavigationStack {
                AccountView()
                    .navigationTitle("Account")
                    .toolbar { Button("Done") { showAccount = false } }
            }
        }
        #endif
    }
}

struct NoteList: View {
    @Bindable var window: NoteWindow

    var body: some View {
        List(window.notes, id: \.path, selection: $window.selection) { note in
            VStack(alignment: .leading, spacing: 2) {
                Text(NoteWindow.title(of: note.path))
                Text(Date(timeIntervalSince1970: Double(note.mtimeNs) / 1e9), format: .dateTime.day().month().year().hour().minute())
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .overlay {
            if window.notes.isEmpty {
                ContentUnavailableView("No Notes", systemImage: "note.text")
            }
        }
        .navigationTitle(title)
        .searchable(text: $window.search, isPresented: $window.searching, prompt: "Search notes")
        .task(id: window.search) { await window.runSearch() }
        .toolbar {
            Button("New Note", systemImage: "square.and.pencil") { window.newNote() }
        }
    }

    private var title: String {
        if case let .folder(folder) = window.folder { return folder }
        return "All Notes"
    }
}

struct NoteView: View {
    @Bindable var window: NoteWindow
    #if os(iOS)
    @State private var showCamera = false
    #endif

    var body: some View {
        if let path = window.openPath {
            VStack(spacing: 0) {
                if window.changedElsewhere {
                    HStack {
                        Text("This note was changed elsewhere. Your edits here are not saved; leaving the note keeps them as a copy.")
                        Spacer()
                        Button("Reload") { window.reloadFromDisk() }
                    }
                    .padding(8)
                    .background(.yellow.opacity(0.25))
                }
                editor
            }
            .navigationTitle(NoteWindow.title(of: path))
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                Button("Attach", systemImage: "paperclip") { window.showAttach = true }
                #if os(iOS)
                if UIImagePickerController.isSourceTypeAvailable(.camera) {
                    Button("Take Photo", systemImage: "camera") { showCamera = true }
                }
                #endif
                Button("Rename", systemImage: "pencil") { window.beginRename() }
                Button("Delete", systemImage: "trash", role: .destructive) { window.showDelete = true }
            }
            .fileImporter(isPresented: $window.showAttach, allowedContentTypes: [.item], allowsMultipleSelection: true) {
                if case let .success(urls) = $0 { window.attach(urls) }
            }
            .alert("Rename Note", isPresented: $window.showRename) {
                TextField("Folder/Name", text: $window.renameText)
                Button("Rename") { window.rename() }
                Button("Cancel", role: .cancel) {}
            }
            .confirmationDialog("Delete this note?", isPresented: $window.showDelete) {
                Button("Delete", role: .destructive) { window.delete() }
            }
            .onDisappear { window.saveOrKeepCopy() }
            #if os(iOS)
            .fullScreenCover(isPresented: $showCamera) {
                CameraPicker { image in
                    if let data = image.jpegData(compressionQuality: 0.9) {
                        let stamp = Date.now.formatted(.iso8601.year().month().day().time(includingFractionalSeconds: false)
                            .timeSeparator(.omitted))
                        window.attach(data, named: "Photo \(stamp).jpg")
                    }
                }
                .ignoresSafeArea()
            }
            #endif
        } else {
            ContentUnavailableView("No Note Selected", systemImage: "doc.text")
        }
    }

    private var editor: some View {
        let document = Binding(get: { window.document }, set: { window.edited($0) })
        #if os(macOS)
        return MarkdownEditor(document: document) { window.attach($0) }
        #else
        return MarkdownEditor(document: document)
        #endif
    }
}

/// Shown until a vault is open: sign in to a server and pick one of its vaults, or use a
/// folder with no account.
struct WelcomeView: View {
    private let app = AppModel.shared
    @State private var chosen: ServerVault?
    @State private var showFolderPicker = false

    var body: some View {
        VStack(spacing: 16) {
            Text("OpenNote").font(.largeTitle.bold())
            SignIn { vault in
                #if os(macOS)
                chosen = vault
                showFolderPicker = true
                #else
                app.openVault(folder: VaultPath.sanitizedName(vault.name), vaultID: vault.id)
                #endif
            }
            if !app.isSignedIn {
                Divider()
                #if os(macOS)
                Button("Open a Folder Without an Account…") {
                    chosen = nil
                    showFolderPicker = true
                }
                #else
                Button("Use on This Device Only") { app.openVault(folder: "Notes", vaultID: nil) }
                #endif
            }
        }
        .frame(maxWidth: 420)
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // macOS: the vault lives in a folder the user chooses, so Obsidian can open it too.
        .fileImporter(isPresented: $showFolderPicker, allowedContentTypes: [.folder]) {
            if case let .success(url) = $0 { app.openVault(folder: url.path, vaultID: chosen?.id) }
        }
    }
}

/// Server address and Sign In; once signed in, the server's vaults to choose from.
struct SignIn: View {
    @Environment(\.webAuthenticationSession) private var webAuthentication
    private let app = AppModel.shared
    @State private var address = AppModel.shared.serverURL?.absoluteString ?? ""
    @State private var vaults: [ServerVault]?
    @State private var busy = false
    let choose: (ServerVault) -> Void

    var body: some View {
        VStack(spacing: 12) {
            if app.isSignedIn {
                Text("Signed in to \(app.serverURL?.host() ?? "")").foregroundStyle(.secondary)
                if let vaults, vaults.isEmpty {
                    Text("This server has no vault for you yet. Create one in the web app.")
                }
                ForEach(vaults ?? [], id: \.id) { vault in
                    Button(vault.name) { choose(vault) }
                        .disabled(vault.id == app.vaultID)
                }
                Button("Sign Out") { Task { await app.signOut() } }
            } else {
                TextField("Server address", text: $address, prompt: Text("https://notes.example.com"))
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    #endif
                Button("Sign In") { Task { await signIn() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy || address.isEmpty)
            }
        }
        .task(id: app.isSignedIn) {
            guard app.isSignedIn, vaults == nil else { return }
            do {
                vaults = try await app.serverVaults()
            } catch {
                app.report(error)
            }
        }
    }

    private func signIn() async {
        busy = true
        defer { busy = false }
        do {
            let login = try app.beginLogin(address)
            let callback = try await webAuthentication.authenticate(
                using: login.url, callback: .customScheme(OAuthClient.callbackScheme), additionalHeaderFields: [:])
            vaults = try await app.finishLogin(login, callback: callback)
        } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            return  // the user closed the sheet
        } catch {
            app.report(error)
        }
    }
}

/// Account and vault: the Settings window on the Mac, a sheet on iOS.
struct AccountView: View {
    private let app = AppModel.shared

    var body: some View {
        Form {
            Section("Vault") {
                LabeledContent("Folder", value: app.vaultFolder ?? "None")
                LabeledContent("Status", value: app.statusText)
                if app.vault != nil {
                    #if os(macOS)
                    Button("Show in Finder") { NSWorkspace.shared.open(app.vault!.root) }
                    #endif
                    Button("Sync Now") { app.syncNow() }
                        .disabled(app.syncState == .local || app.syncState == .signedOut)
                    Button("Close Vault") { app.closeVault() }
                }
            }
            Section("Server") {
                // With a vault open, choosing a server vault syncs the open folder with it.
                SignIn { vault in
                    if let folder = app.vaultFolder { app.openVault(folder: folder, vaultID: vault.id) }
                }
            }
            Section {
                LabeledContent("Version", value: OpenNoteCore.version)
            }
        }
        .formStyle(.grouped)
    }
}
