import Foundation
import Observation
import OpenNoteAPI
import OpenNoteCore
import OpenNoteStorage
import OpenNoteSync
import UserNotifications
import os
#if canImport(UIKit)
import UIKit
#endif

let log = Logger(subsystem: "dev.opennote.OpenNote", category: "app")

/// A vault on the server the signed-in user may open.
typealias ServerVault = Components.Schemas.Vault

/// A login between opening the browser and its callback.
struct PendingLogin {
    let server: URL
    let pkce = PKCE()
    let state = PKCE().verifier
    var url: URL { OAuthClient(serverURL: server, transport: transport).authorizeURL(challenge: pkce.challenge, state: state) }
}

struct AppError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

private let transport = urlSessionTransport()

/// The app's state, one per process: which vault folder is open, what is in it, and the
/// server session that syncs it. The folder is read and written through `Vault` alone; the
/// sync engine works on the same folder beside it, as it would beside Obsidian (R-P4-002).
@MainActor @Observable
final class AppModel {
    static let shared = AppModel()

    enum SyncState: Equatable {
        case local, syncing, synced(Date), failed(String), signedOut
    }

    // Configuration, kept in UserDefaults; a launch argument (`-vaultFolder …`) overrides it.
    private(set) var serverURL: URL?
    private(set) var vaultID: String?
    /// macOS: the folder's path. iOS: the folder's name under Documents.
    private(set) var vaultFolder: String?

    private(set) var vault: Vault?
    /// Notes, newest first.
    private(set) var notes: [ScannedFile] = []
    /// Every folder that holds a note, with its parents.
    private(set) var folders: [String] = []
    /// Counts reloads, so views can react to a changed folder without comparing lists.
    private(set) var revision = 0
    private(set) var syncState = SyncState.local
    private(set) var isSignedIn = false
    var errorMessage: String?

    private var known: [String: ScannedFile] = [:]
    private var session: Session?
    private var engine: SyncEngine?
    private var engineTask: Task<Void, Never>?

    private init() {
        let defaults = UserDefaults.standard
        func value(_ key: String) -> String? { defaults.string(forKey: key).flatMap { $0.isEmpty ? nil : $0 } }
        serverURL = value("serverURL").flatMap(ServerAddress.parse)
        vaultID = value("vaultID")
        vaultFolder = value("vaultFolder")
        if let serverURL, let session = makeSession(serverURL) {
            self.session = session
            Task { isSignedIn = await session.isSignedIn }
        }
        openFolder()
    }

    private func persist() {
        let defaults = UserDefaults.standard
        defaults.set(serverURL?.absoluteString, forKey: "serverURL")
        defaults.set(vaultID, forKey: "vaultID")
        defaults.set(vaultFolder, forKey: "vaultFolder")
    }

    // MARK: - Vault folder

    var vaultName: String { vault?.root.lastPathComponent ?? "OpenNote" }

    private var supportDirectory: URL {
        let key = ContentHash.sha256(Data((vaultFolder ?? "").utf8)).dropFirst(7).prefix(12)
        return URL.applicationSupportDirectory.appending(path: "OpenNote/\(vaultID ?? "local")-\(key)")
    }

    /// Opens `folder`, synced with the server vault `vaultID` when there is one.
    func openVault(folder: String, vaultID: String?) {
        stopSync()
        vaultFolder = folder
        self.vaultID = vaultID
        persist()
        openFolder()
    }

    /// Back to the welcome screen. The folder and its files stay where they are.
    func closeVault() {
        stopSync()
        vaultFolder = nil
        vaultID = nil
        persist()
        vault = nil
        notes = []
        folders = []
        known = [:]
        revision += 1
    }

    private func openFolder() {
        guard let vaultFolder else { return }
        #if os(macOS)
        // Never created here: a folder that is missing (a drive not mounted, a folder moved)
        // must not come back empty, or the engine would report every note as deleted.
        let root = URL(fileURLWithPath: vaultFolder, isDirectory: true)
        var isFolder: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: root.path, isDirectory: &isFolder) && isFolder.boolValue
        #else
        let root = URL.documentsDirectory.appending(path: vaultFolder, directoryHint: .isDirectory)
        let exists = (try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)) != nil
        #endif
        guard exists else {
            // The choice is kept: the folder may be back the next time the app starts.
            log.error("vault folder unavailable")
            errorMessage = "The vault folder could not be opened. Choose it again, or start OpenNote when it is back."
            vault = nil
            return
        }
        vault = Vault(root: root, recoveryRoot: supportDirectory.appending(path: "recovery"))
        known = [:]
        startSync()
        Task { await reload() }
    }

    /// Rescans the folder. Cheap after the first time: only changed files are hashed again.
    func reload() async {
        guard let vault else { return }
        guard let scan = await Self.scan(vault, known: known), vault.root == self.vault?.root else { return }
        known = Dictionary(scan.map { ($0.path, $0) }) { first, _ in first }
        notes = scan.filter { $0.kind == .note }.sorted { $0.mtimeNs > $1.mtimeNs }
        var all = Set<String>()
        for note in notes {
            var parts = note.path.split(separator: "/").dropLast()
            while !parts.isEmpty {
                all.insert(parts.joined(separator: "/"))
                parts.removeLast()
            }
        }
        folders = all.sorted { $0.localizedStandardCompare($1) == .orderedAscending }
        revision += 1
    }

    @concurrent private static func scan(_ vault: Vault, known: [String: ScannedFile]) async -> [ScannedFile]? {
        do {
            return try vault.scan(known: known)
        } catch {
            log.error("vault scan failed: \(String(describing: error))")
            return nil
        }
    }

    /// Creates a file at `wanted`, or at the first free numbered name beside it; returns its path.
    func create(_ wanted: String, _ data: Data) throws -> String {
        guard let vault else { throw AppError("Open a vault in OpenNote first.") }
        var taken = Array(known.keys)
        for _ in 0..<100 {
            let path = VaultPath.freePath(wanted, taken: taken)
            do {
                try vault.write(path, data, expectedBase: nil)
                changed()
                return path
            } catch VaultError.externalChange {
                taken.append(path)  // appeared since the last scan
            }
        }
        throw AppError("The file could not be created.")
    }

    /// The folder changed through this app: show it and let the engine pick it up.
    func changed() {
        Task {
            await reload()
            await engine?.notifyLocalChange()
        }
    }

    /// The app came to the front: files may have changed outside it (Obsidian, Finder, Files).
    func activated() {
        importShared()
        changed()
    }

    // MARK: - Capture (P4-08)

    /// Saves `text` as a new note in the vault's Inbox folder.
    func capture(_ text: String) throws {
        let body = String(text.prefix(100_000))
        guard !body.allSatisfy(\.isWhitespace) else { return }
        let fallback = "Note " + Date.now.formatted(.iso8601.year().month().day())
        let name = VaultPath.noteName(forText: body, fallback: fallback)
        _ = try create("Inbox/" + name, Data((body.hasSuffix("\n") ? body : body + "\n").utf8))
    }

    /// `opennote://capture?text=…` (Shortcuts, links, the UI tests).
    func open(_ url: URL) {
        guard url.scheme == OAuthClient.callbackScheme, url.host() == "capture",
              let text = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                  .queryItems?.first(where: { $0.name == "text" })?.value else { return }
        do {
            try capture(text)
        } catch {
            report(error)
        }
    }

    /// Moves what the share extension left in the App Group inbox into the vault (iOS; the
    /// Mac has no share extension, and asking for a group container there prompts the user).
    private func importShared() {
        #if os(iOS)
        guard vault != nil, let inbox = SharedInbox.url,
              let items = try? FileManager.default.contentsOfDirectory(at: inbox, includingPropertiesForKeys: nil)
        else { return }
        for item in items where item.pathExtension == "md" {
            do {
                try capture(String(decoding: try Data(contentsOf: item), as: UTF8.self))
                try FileManager.default.removeItem(at: item)
            } catch {
                log.error("shared item not imported: \(error)")
            }
        }
        #endif
    }

    // MARK: - Sign in (P4-03)

    /// The session for `server`, with whatever credentials the Keychain holds for it.
    private func makeSession(_ server: URL) -> Session? {
        do {
            return try Session(
                oauth: OAuthClient(serverURL: server, transport: transport), store: KeychainStore(server: server),
                onSignedOut: { Task { @MainActor in AppModel.shared.sessionEnded() } })
        } catch {
            log.error("keychain unavailable: \(error)")
            errorMessage = "The sign-in could not be read from the Keychain."
            return nil
        }
    }

    /// The login to open in the web authentication session.
    func beginLogin(_ address: String) throws -> PendingLogin {
        guard let server = ServerAddress.parse(address) else {
            throw AppError("Enter the server's address, starting with https://")
        }
        return PendingLogin(server: server)
    }

    /// Exchanges the callback's code, stores the credentials and lists the server's vaults.
    func finishLogin(_ login: PendingLogin, callback: URL) async throws -> [ServerVault] {
        let code = try OAuthClient.code(from: callback, state: login.state)
        let oauth = OAuthClient(serverURL: login.server, transport: transport)
        let credentials = try await oauth.exchange(code: code, verifier: login.pkce.verifier,
                                                   deviceName: Platform.deviceName, platform: Platform.name)
        guard let session = makeSession(login.server) else {
            throw AppError("The sign-in could not be saved in the Keychain.")
        }
        try await session.signIn(credentials)
        stopSync()
        self.session = session
        serverURL = login.server
        persist()
        isSignedIn = true
        let vaults = try await serverVaults()
        // Signed in again for the vault that is already open: carry on syncing it.
        if vaults.contains(where: { $0.id == vaultID }) { startSync() }
        return vaults
    }

    func serverVaults() async throws -> [ServerVault] {
        guard let serverURL, let session else { throw AuthError.signedOut }
        let client = Client(server: serverURL, transport: transport, middlewares: [BearerAuth(session: session)])
        var vaults: [ServerVault] = []
        var cursor: String?
        for _ in 0..<50 {  // bounded: 50 pages is far more vaults than one person has
            let page = try await client.listVaults(query: .init(cursor: cursor)).ok.body.json
            vaults += page.items
            cursor = page.nextCursor
            if cursor == nil { break }
        }
        return vaults
    }

    func signOut() async {
        stopSync()
        do {
            try await session?.signOut()
        } catch {
            report(error)
        }
        sessionEnded()
    }

    private func sessionEnded() {
        stopSync()
        isSignedIn = false
        syncState = vaultID == nil ? .local : .signedOut
    }

    // MARK: - Sync

    private func startSync() {
        stopSync()
        guard let serverURL, let vaultID, let session, let vault else { return }
        let api = OpenAPISyncAPI(serverURL: serverURL, vaultID: vaultID, transport: transport,
                                 middlewares: [BearerAuth(session: session)])
        do {
            let engine = try SyncEngine(root: vault.root, supportDirectory: supportDirectory, vaultID: vaultID, api: api)
            self.engine = engine
            syncState = .syncing
            engineTask = Task {
                guard await session.isSignedIn else { return sessionEnded() }
                await engine.setOnRound { error in
                    Task { @MainActor in await AppModel.shared.roundEnded(engine, error) }
                }
                await engine.run()
            }
        } catch {
            log.error("sync engine not started: \(error)")
            syncState = .failed("Sync could not start.")
        }
    }

    private func stopSync() {
        engineTask?.cancel()
        engineTask = nil
        engine = nil
        syncState = .local
    }

    func syncNow() {
        Task { await engine?.notifyLocalChange() }
    }

    private func roundEnded(_ engine: SyncEngine, _ error: (any Error)?) async {
        guard engine === self.engine else { return }
        if let error {
            log.error("sync round failed: \(logDescription(error))")
            syncState = .failed(error is SyncAPIError ? "The server refused the sync." : "The server cannot be reached.")
        } else {
            syncState = .synced(.now)
        }
        await reload()
        await notifyFlagged(engine)
    }

    /// A local notification for files the server newly refused or restored (P4-08): the one
    /// outcome of a sync that needs the user. Each file is announced once.
    private func notifyFlagged(_ engine: SyncEngine) async {
        do {
            let files = try await engine.flaggedFiles()
            let defaults = UserDefaults.standard
            let seen = Set(defaults.stringArray(forKey: "notifiedFlags") ?? [])
            let fresh = files.filter { !seen.contains($0.fileID) }
            defaults.set(files.map(\.fileID), forKey: "notifiedFlags")
            guard let first = fresh.first else { return }
            let center = UNUserNotificationCenter.current()
            guard try await center.requestAuthorization(options: [.alert, .sound]) else { return }
            let content = UNMutableNotificationContent()
            content.title = "OpenNote"
            let name = first.localPath ?? "A file"
            content.body = fresh.count == 1 ? "\(name) could not be synced."
                : "\(name) and \(fresh.count - 1) more could not be synced."
            try await center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        } catch {
            log.error("notification not delivered: \(error)")
        }
    }

    // MARK: - Messages

    var statusText: String {
        switch syncState {
        case .local: "On this device only"
        case .syncing: "Syncing…"
        case let .synced(date): "Synced " + date.formatted(date: .omitted, time: .shortened)
        case let .failed(message): message
        case .signedOut: "Signed out"
        }
    }

    func report(_ error: any Error) {
        log.error("\(logDescription(error))")
        errorMessage = switch error {
        case VaultError.invalidPath: "That name cannot be used for a file."
        case VaultError.externalChange: "The file was changed elsewhere."
        case VaultError.notFound: "The file is no longer there."
        case is VaultError: "The file could not be written."
        case AuthError.invalidCallback, AuthError.rejected, AuthError.signedOut: "Signing in did not work. Try again."
        case let error as AppError: error.errorDescription
        default: "The server could not be reached, or gave an unexpected answer."
        }
    }
}

enum Platform {
    #if os(macOS)
    static let name = "macos"
    static var deviceName: String { Host.current().localizedName ?? "Mac" }
    #else
    static let name = "ios"
    @MainActor static var deviceName: String { UIDevice.current.name }
    #endif
}
