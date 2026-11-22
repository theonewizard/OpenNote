import CryptoKit
import Foundation
import OpenAPIRuntime

public enum AuthError: Error, Equatable {
    /// The callback URL is not the answer to this login (wrong state, no code, or an error).
    case invalidCallback
    /// The server refused the code or the refresh token: the user has to sign in again.
    case rejected
    /// There are no credentials (never signed in, signed out, or the device was revoked).
    case signedOut
    /// Any other answer from the token endpoint; worth another try later.
    case status(Int)
}

public enum ServerAddress {
    /// The server's base URL from what the user typed. `https` is assumed and required; plain
    /// `http` is accepted for a loopback host only (a development server on this machine).
    public static func parse(_ text: String) -> URL? {
        let typed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !typed.isEmpty,
              var parts = URLComponents(string: typed.contains("://") ? typed : "https://" + typed),
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil else { return nil }
        let loopback = ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host.lowercased())
        guard parts.scheme == "https" || (parts.scheme == "http" && loopback) else { return nil }
        parts.query = nil
        parts.fragment = nil
        while parts.path.hasSuffix("/") { parts.path.removeLast() }
        return parts.url
    }
}

/// What to log for a failed server call: the operation and its cause, never the request.
public func logDescription(_ error: any Error) -> String {
    guard let error = error as? ClientError else { return String(describing: error) }
    return "\(error.operationID): \(error.underlyingError)"
}

/// RFC 7636 proof key: a random verifier and its S256 challenge.
public struct PKCE: Sendable {
    public let verifier: String

    public init() {
        verifier = Self.base64URL(SymmetricKey(size: .bits256).withUnsafeBytes { Data($0) })
    }

    init(verifier: String) { self.verifier = verifier }

    public var challenge: String {
        Self.base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
    }

    static func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}

/// What a login yields (`TokenResponse`); the Keychain holds exactly this.
public struct Credentials: Codable, Sendable, Equatable {
    public var accessToken: String
    public var expiresAt: Date
    public var refreshToken: String
    public var deviceID: String

    public init(accessToken: String, expiresAt: Date, refreshToken: String, deviceID: String) {
        self.accessToken = accessToken
        self.expiresAt = expiresAt
        self.refreshToken = refreshToken
        self.deviceID = deviceID
    }
}

/// The native client's side of the server's OAuth 2.0 endpoints (ADR-0012): authorization
/// code with PKCE, then rotating refresh tokens bound to this device.
public struct OAuthClient: Sendable {
    public static let clientID = "opennote-apple"
    public static let redirectURI = "opennote://auth/callback"
    public static let callbackScheme = "opennote"

    public let serverURL: URL
    let transport: any ClientTransport
    let client: Client
    let now: @Sendable () -> Date

    public init(serverURL: URL, transport: any ClientTransport, now: @escaping @Sendable () -> Date = { Date() }) {
        self.serverURL = serverURL
        self.transport = transport
        self.client = Client(serverURL: serverURL, transport: transport)
        self.now = now
    }

    /// The page to open in the web authentication session.
    public func authorizeURL(challenge: String, state: String) -> URL {
        var parts = URLComponents(url: serverURL.appendingPathComponent("api/v1/auth/authorize"),
                                  resolvingAgainstBaseURL: false)!
        parts.queryItems = [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: Self.clientID),
            URLQueryItem(name: "redirect_uri", value: Self.redirectURI),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "state", value: state),
        ]
        return parts.url!
    }

    /// The authorization code in the callback, if the callback answers the login `state` began.
    public static func code(from callback: URL, state: String) throws(AuthError) -> String {
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { items.first { $0.name == name }?.value }
        guard callback.absoluteString.hasPrefix(redirectURI), value("state") == state,
              let code = value("code"), !code.isEmpty else { throw .invalidCallback }
        return code
    }

    /// Exchanges the code; the server registers this device under `deviceName`.
    public func exchange(code: String, verifier: String, deviceName: String,
                         platform: String) async throws -> Credentials {
        try await token(.init(clientId: Self.clientID, code: code, codeVerifier: verifier, deviceName: deviceName,
                              devicePlatform: platform, grantType: .authorizationCode,
                              redirectUri: Self.redirectURI))
    }

    /// Rotates the refresh token. `AuthError.rejected`: it is spent, expired or revoked.
    public func refresh(_ refreshToken: String) async throws -> Credentials {
        try await token(.init(clientId: Self.clientID, grantType: .refreshToken, refreshToken: refreshToken))
    }

    private func token(_ form: Components.Schemas.BodyToken) async throws -> Credentials {
        let output: Operations.Token.Output
        do {
            output = try await client.token(body: .urlEncodedForm(form))
        } catch let error as ClientError {
            // A ClientError prints its whole input: here the code, the verifier or the
            // refresh token. Only the cause leaves this function.
            throw error.underlyingError
        }
        switch output {
        case let .ok(ok):
            let body = try ok.body.json
            return Credentials(accessToken: body.accessToken,
                               expiresAt: now().addingTimeInterval(TimeInterval(body.expiresIn)),
                               refreshToken: body.refreshToken, deviceID: body.deviceId)
        case let .default(statusCode, _):
            throw statusCode == 400 || statusCode == 401 ? AuthError.rejected : AuthError.status(statusCode)
        }
    }
}
