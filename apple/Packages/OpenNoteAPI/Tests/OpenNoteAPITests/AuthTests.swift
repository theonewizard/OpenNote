import Foundation
import HTTPTypes
import OpenAPIRuntime
@testable import OpenNoteAPI
import Synchronization
import Testing

/// Answers each request with `respond`, after collecting its body.
final class StubTransport: ClientTransport, Sendable {
    typealias Respond = @Sendable (HTTPRequest, String) throws -> (HTTPResponse, HTTPBody?)
    let respond: Respond

    init(_ respond: @escaping Respond) { self.respond = respond }

    func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL,
              operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        var text = ""
        if let body { text = try await String(collecting: body, upTo: 1 << 20) }
        return try respond(request, text)
    }
}

/// A value the stub's @Sendable closures can record into.
final class Locked<Value: Sendable>: Sendable {
    private let value: Mutex<Value>
    init(_ value: Value) { self.value = Mutex(value) }
    func with<R: Sendable>(_ body: (inout Value) -> R) -> R { value.withLock { body(&$0) } }
}

final class MemoryStore: CredentialStore {
    let saved: Locked<Credentials?>
    init(_ credentials: Credentials? = nil) { saved = Locked(credentials) }
    func load() -> Credentials? { saved.with { $0 } }
    func save(_ credentials: Credentials?) { saved.with { $0 = credentials } }
}

let server = URL(string: "https://notes.example")!
let start = Date(timeIntervalSince1970: 1_800_000_000)

func json(_ status: Int, _ text: String, type: String = "application/json") -> (HTTPResponse, HTTPBody?) {
    (HTTPResponse(status: .init(code: status), headerFields: [.contentType: type]), HTTPBody(text))
}

/// The server's error answer (RFC 9457).
func problem(_ status: Int) -> (HTTPResponse, HTTPBody?) {
    json(status, #"{"type":"about:blank","title":"x","status":\#(status)}"#, type: "application/problem+json")
}

func tokens(_ n: Int) -> String {
    """
    {"access_token":"access-\(n)","token_type":"Bearer","expires_in":900,"refresh_token":"refresh-\(n)",
     "device_id":"0192f5c6-0000-7000-8000-00000000000d"}
    """
}

func credentials(_ n: Int, expiresIn: TimeInterval = 900) -> Credentials {
    Credentials(accessToken: "access-\(n)", expiresAt: start.addingTimeInterval(expiresIn),
                refreshToken: "refresh-\(n)", deviceID: "0192f5c6-0000-7000-8000-00000000000d")
}

@Suite struct LoginTests {
    @Test func serverAddressNeedsHTTPSExceptOnLoopback() {
        #expect(ServerAddress.parse(" notes.example/ ")?.absoluteString == "https://notes.example")
        #expect(ServerAddress.parse("https://notes.example:8443/base/?x=1#f")?.absoluteString
            == "https://notes.example:8443/base")
        #expect(ServerAddress.parse("http://localhost:8000")?.absoluteString == "http://localhost:8000")
        #expect(ServerAddress.parse("http://127.0.0.1:5173/")?.absoluteString == "http://127.0.0.1:5173")
        #expect(ServerAddress.parse("http://notes.example") == nil)
        #expect(ServerAddress.parse("https://user:secret@notes.example") == nil)
        #expect(ServerAddress.parse("ftp://notes.example") == nil)
        #expect(ServerAddress.parse("") == nil)
    }

    // RFC 7636, appendix B.
    @Test func pkceChallengeIsTheS256OfTheVerifier() {
        let pkce = PKCE(verifier: "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        #expect(pkce.challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    }

    @Test func pkceVerifiersAreRandomAndURLSafe() {
        let a = PKCE(), b = PKCE()
        #expect(a.verifier != b.verifier)
        #expect(a.verifier.wholeMatch(of: /[A-Za-z0-9_-]{43}/) != nil)
    }

    @Test func authorizeURLNamesTheClientItsRedirectAndTheChallenge() {
        let oauth = OAuthClient(serverURL: server, transport: StubTransport { _, _ in json(500, "{}") })
        let url = oauth.authorizeURL(challenge: "CHALLENGE", state: "STATE")
        #expect(url.absoluteString == "https://notes.example/api/v1/auth/authorize?response_type=code"
            + "&client_id=opennote-apple&redirect_uri=opennote://auth/callback&code_challenge=CHALLENGE"
            + "&code_challenge_method=S256&state=STATE")
    }

    @Test func callbackGivesTheCodeOnlyForThisLogin() throws {
        let good = URL(string: "opennote://auth/callback?code=onc_abc&state=S1")!
        #expect(try OAuthClient.code(from: good, state: "S1") == "onc_abc")
        for bad in ["opennote://auth/callback?code=onc_abc&state=OTHER", "opennote://auth/callback?state=S1",
                    "opennote://auth/callback?error=access_denied&state=S1",
                    "opennote://capture?code=onc_abc&state=S1"] {
            #expect(throws: AuthError.invalidCallback) { try OAuthClient.code(from: URL(string: bad)!, state: "S1") }
        }
    }

    @Test func exchangePostsTheCodeWithItsVerifierAndTheDevice() async throws {
        let seen = Locked<[String]>([])
        let oauth = OAuthClient(serverURL: server, transport: StubTransport { request, body in
            seen.with { $0 = [request.method.rawValue, request.path ?? "", request.headerFields[.contentType] ?? "", body] }
            return json(200, tokens(1))
        }, now: { start })
        let result = try await oauth.exchange(code: "onc_abc", verifier: "VERIFIER", deviceName: "Flemming's Mac",
                                              platform: "macos")
        #expect(result == credentials(1))
        let request = seen.with { $0 }
        #expect(Array(request.prefix(3)) == ["POST", "/api/v1/auth/token", "application/x-www-form-urlencoded"])
        let form = Set(request[3].split(separator: "&").map(String.init))
        #expect(form == ["client_id=opennote-apple", "code=onc_abc", "code_verifier=VERIFIER",
                         "device_name=Flemming%27s+Mac", "device_platform=macos", "grant_type=authorization_code",
                         "redirect_uri=opennote%3A%2F%2Fauth%2Fcallback"])
    }

    @Test func refusedGrantIsRejectedAndOtherFailuresAreNot() async {
        func refresh(_ status: Int) async -> AuthError? {
            let oauth = OAuthClient(serverURL: server, transport: StubTransport { _, _ in problem(status) })
            do {
                _ = try await oauth.refresh("refresh-0")
                return nil
            } catch {
                return error as? AuthError
            }
        }
        #expect(await refresh(400) == .rejected)
        #expect(await refresh(401) == .rejected)
        #expect(await refresh(503) == .status(503))
    }
}

struct Offline: Error {}

@Suite struct LoggingTests {
    @Test func aFailedTokenCallNeverCarriesItsSecrets() async {
        let oauth = OAuthClient(serverURL: server, transport: StubTransport { _, _ in throw Offline() })
        await #expect(throws: Offline.self) { try await oauth.refresh("refresh-SECRET") }
        do {
            _ = try await oauth.exchange(code: "code-SECRET", verifier: "verifier-SECRET", deviceName: "d", platform: "p")
        } catch {
            #expect(!String(describing: error).contains("SECRET"))
        }
    }

    @Test func logDescriptionNamesTheOperationAndLeavesTheRequestOut() async {
        let api = Client(server: server, transport: StubTransport { _, _ in throw Offline() })
        do {
            _ = try await api.listVaults(query: .init(cursor: "cursor-PRIVATE"))
        } catch {
            #expect(String(describing: error).contains("PRIVATE"))  // why the helper exists
            #expect(logDescription(error) == "list_vaults: Offline()")
        }
    }
}

@Suite struct SessionTests {
    /// A session whose token endpoint hands out access-2, access-3… and counts the calls.
    func session(_ stored: Credentials?, now: @escaping @Sendable () -> Date = { start }, status: Int = 200,
                 onSignedOut: @escaping @Sendable () -> Void = {}) throws -> (Session, MemoryStore, Locked<[String]>) {
        let bodies = Locked<[String]>([])
        let store = MemoryStore(stored)
        let oauth = OAuthClient(serverURL: server, transport: StubTransport { _, body in
            let n = bodies.with { $0.append(body); return $0.count }
            return status == 200 ? json(200, tokens(n + 1)) : problem(status)
        }, now: now)
        return (try Session(oauth: oauth, store: store, now: now, onSignedOut: onSignedOut), store, bodies)
    }

    @Test func aFreshTokenIsUsedAsItIs() async throws {
        let (session, _, calls) = try session(credentials(1))
        #expect(try await session.accessToken() == "access-1")
        #expect(calls.with { $0.isEmpty })
    }

    @Test func anExpiringTokenIsRefreshedOnceForEveryoneWaiting() async throws {
        let (session, store, calls) = try session(credentials(1, expiresIn: 30))
        let got = try await withThrowingTaskGroup(of: String.self) { group in
            for _ in 0..<5 { group.addTask { try await session.accessToken() } }
            return try await group.reduce(into: Set<String>()) { $0.insert($1) }
        }
        #expect(got == ["access-2"])
        #expect(calls.with { $0.count } == 1)
        #expect(calls.with { $0[0] }.contains("refresh_token=refresh-1"))
        #expect(store.load() == credentials(2))
    }

    @Test func aRejectedRefreshSignsOutAndForgetsTheCredentials() async throws {
        let signedOut = Locked(false)
        let (session, store, _) = try session(credentials(1, expiresIn: 0), status: 400) {
            signedOut.with { $0 = true }
        }
        await #expect(throws: AuthError.signedOut) { try await session.accessToken() }
        #expect(store.load() == nil)
        #expect(signedOut.with { $0 })
        #expect(await session.isSignedIn == false)
    }

    @Test func signInStoresAndSignOutForgets() async throws {
        let (session, store, _) = try session(nil)
        await #expect(throws: AuthError.signedOut) { try await session.accessToken() }
        try await session.signIn(credentials(7))
        #expect(store.load() == credentials(7))
        #expect(try await session.accessToken() == "access-7")
        try await session.signOut()
        #expect(store.load() == nil)
        #expect(await session.isSignedIn == false)
    }

    @Test func signOutTellsTheServerAndForgetsEvenWhenItCannotBeReached() async throws {
        let seen = Locked<[String]>([])
        let store = MemoryStore(credentials(1))
        let oauth = OAuthClient(serverURL: server, transport: StubTransport { request, _ in
            seen.with { $0.append("\(request.path ?? "") \(request.headerFields[.authorization] ?? "")") }
            throw Offline()
        }, now: { start })
        let session = try Session(oauth: oauth, store: store, now: { start })
        try await session.signOut()
        #expect(seen.with { $0 } == ["/api/v1/auth/logout Bearer access-1"])
        #expect(store.load() == nil)
    }

    @Test func bearerAuthRefreshesAndRepeatsOnceAfterA401() async throws {
        let (session, _, calls) = try session(credentials(1))
        let seen = Locked<[String]>([])
        let api = Client(serverURL: server, transport: StubTransport { request, _ in
            let header = request.headerFields[.authorization] ?? ""
            seen.with { $0.append(header) }
            return header == "Bearer access-1" ? problem(401) : json(200, #"{"items":[],"next_cursor":null}"#)
        }, middlewares: [BearerAuth(session: session)])
        _ = try await api.listVaults().ok
        #expect(seen.with { $0 } == ["Bearer access-1", "Bearer access-2"])
        #expect(calls.with { $0.count } == 1)
    }
}

@Suite struct ServerDateTests {
    // What the server sends: microseconds, or no fraction at all when they are zero.
    @Test(arguments: ["2026-11-22T00:05:08.250581Z", "2026-11-22T00:05:08Z"])
    func vaultTimestampsAreReadWithAndWithoutFractionalSeconds(_ created: String) async throws {
        let api = Client(server: server, transport: StubTransport { _, _ in
            json(200, """
                {"items":[{"id":"0192f5c6-0000-7000-8000-000000000001","name":"Test","role":"owner","revision":1,
                 "created_at":"\(created)","settings":{}}],"next_cursor":null}
                """)
        })
        let vault = try #require(try await api.listVaults().ok.body.json.items.first)
        #expect(Int(vault.createdAt.timeIntervalSince1970) == 1_795_305_908)
    }
}

@Suite struct KeychainTests {
    @Test func keychainStoreKeepsReplacesAndDeletesOneItemPerServer() throws {
        let store = KeychainStore(service: "dev.opennote.OpenNote.tests.\(UUID().uuidString)", server: server)
        defer { try? store.save(nil) }
        #expect(try store.load() == nil)
        try store.save(credentials(1))
        #expect(try store.load() == credentials(1))
        try store.save(credentials(2))
        #expect(try store.load() == credentials(2))
        try store.save(nil)
        #expect(try store.load() == nil)
    }
}
