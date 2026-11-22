import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession
#if canImport(Security)
import Security
#endif

/// Where the credentials are kept between launches. `save(nil)` deletes them.
public protocol CredentialStore: Sendable {
    func load() throws -> Credentials?
    func save(_ credentials: Credentials?) throws
}

// The Keychain is Apple only; on Linux (the cross-client suite builds this package there)
// the store is left out.
#if canImport(Security)
public struct KeychainError: Error, Equatable {
    public let status: OSStatus
}

/// One generic-password Keychain item per server: readable after the first unlock (so a
/// background sync can use it), never synced to other devices (threat model, stolen tokens).
public struct KeychainStore: CredentialStore {
    let service: String
    let account: String

    public init(service: String = "dev.opennote.OpenNote", server: URL) {
        self.service = service
        self.account = server.absoluteString
    }

    private var query: [CFString: Any] {
        [kSecClass: kSecClassGenericPassword, kSecAttrService: service, kSecAttrAccount: account]
    }

    public func load() throws -> Credentials? {
        var result: CFTypeRef?
        let find = query.merging([kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne]) { $1 }
        let status = SecItemCopyMatching(find as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw KeychainError(status: status) }
        return try JSONDecoder().decode(Credentials.self, from: data)
    }

    public func save(_ credentials: Credentials?) throws {
        guard let credentials else {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
            return
        }
        let data = try JSONEncoder().encode(credentials)
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData: data] as CFDictionary)
        if status == errSecItemNotFound {
            let add = query.merging([
                kSecValueData: data, kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            ]) { $1 }
            status = SecItemAdd(add as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw KeychainError(status: status) }
    }
}
#endif

/// The signed-in state for one server: hands out a valid access token and keeps the stored
/// credentials current. Refresh tokens are single use and a reused one revokes the device, so
/// there is never more than one refresh in flight and its result is stored before it is used.
public actor Session {
    let oauth: OAuthClient
    let store: any CredentialStore
    let now: @Sendable () -> Date
    private var credentials: Credentials?
    private var refreshing: Task<Credentials, any Error>?
    private let onSignedOut: @Sendable () -> Void

    /// `onSignedOut` is called when the server no longer accepts this device (a refresh was
    /// rejected).
    public init(oauth: OAuthClient, store: any CredentialStore, now: @escaping @Sendable () -> Date = { Date() },
                onSignedOut: @escaping @Sendable () -> Void = {}) throws {
        self.oauth = oauth
        self.store = store
        self.now = now
        self.onSignedOut = onSignedOut
        credentials = try store.load()
    }

    public var isSignedIn: Bool { credentials != nil }

    /// Stores the credentials of a completed login.
    public func signIn(_ new: Credentials) throws {
        try store.save(new)
        credentials = new
    }

    /// Forgets the credentials, after telling the server to revoke this device's refresh
    /// tokens. The server is told on a best effort: signing out must work offline too.
    public func signOut() async throws {
        if credentials != nil {
            let client = Client(serverURL: oauth.serverURL, transport: oauth.transport,
                                middlewares: [BearerAuth(session: self)])
            _ = try? await client.logout()
        }
        credentials = nil
        try store.save(nil)
    }

    /// A valid access token, refreshed when it has under a minute left. `replacing` is a token
    /// the server just answered 401 to: it is refreshed unless that already happened.
    public func accessToken(replacing stale: String? = nil) async throws -> String {
        guard let current = credentials else { throw AuthError.signedOut }
        if current.accessToken != stale, current.expiresAt.timeIntervalSince(now()) > 60 {
            return current.accessToken
        }
        if let refreshing { return try await refreshing.value.accessToken }
        let task = Task { [oauth] in try await oauth.refresh(current.refreshToken) }
        refreshing = task
        defer { refreshing = nil }
        do {
            let fresh = try await task.value
            credentials = fresh
            try store.save(fresh)
            return fresh.accessToken
        } catch AuthError.rejected {
            credentials = nil
            try? store.save(nil)
            onSignedOut()
            throw AuthError.signedOut
        }
    }
}

/// Adds the session's access token to every request. A 401 gets one refresh and one repeat,
/// when the request body can be sent again.
public struct BearerAuth: ClientMiddleware {
    let session: Session

    public init(session: Session) { self.session = session }

    public func intercept(
        _ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String,
        next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        let token = try await session.accessToken()
        request.headerFields[.authorization] = "Bearer \(token)"
        let (response, responseBody) = try await next(request, body, baseURL)
        guard response.status == .unauthorized, body.map({ $0.iterationBehavior == .multiple }) ?? true else {
            return (response, responseBody)
        }
        request.headerFields[.authorization] = "Bearer \(try await session.accessToken(replacing: token))"
        return try await next(request, body, baseURL)
    }
}

/// The transport for every server call: URLSession, 60 s without data ends a request (the
/// event stream's heartbeat comes every 25 s).
public func urlSessionTransport() -> any ClientTransport {
    let configuration = URLSessionConfiguration.default
    configuration.timeoutIntervalForRequest = 60
    return URLSessionTransport(configuration: .init(session: URLSession(configuration: configuration)))
}
