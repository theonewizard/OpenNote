// `opennote-sync`: one sync round of the Apple sync engine against a real server, for the
// cross-client end-to-end suite (roadmap P5-09, scripts/sync-e2e.sh). It stands in for the
// Apple apps until they exist (Phase 4): the same SyncEngine and OpenAPISyncAPI, over a
// plain URLSession transport, with the device's bearer token from OPENNOTE_TOKEN.
//
//     OPENNOTE_TOKEN=… opennote-sync <server-url> <vault-id> <vault-folder> <support-folder>
//
// Exits 0 after a round that completed, printing each flagged file as `<flag> <path>`.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import HTTPTypes
import OpenAPIRuntime
import OpenNoteSync

/// Sends each request with URLSession; bodies are small in the suite, so both are buffered.
struct URLSessionTransport: ClientTransport {
    func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL,
              operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        guard let url = URL(string: baseURL.absoluteString + (request.path ?? "")) else {
            throw URLError(.badURL)
        }
        var urlRequest = URLRequest(url: url, timeoutInterval: 60)
        urlRequest.httpMethod = request.method.rawValue
        for field in request.headerFields {
            urlRequest.addValue(field.value, forHTTPHeaderField: field.name.canonicalName)
        }
        if let body {
            urlRequest.httpBody = try await Data(collecting: body, upTo: 64 << 20)
        }
        let (data, response): (Data, URLResponse) = try await withCheckedThrowingContinuation { done in
            URLSession.shared.dataTask(with: urlRequest) { data, response, error in
                if let error { return done.resume(throwing: error) }
                done.resume(returning: (data ?? Data(), response!))
            }.resume()
        }
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        var fields = HTTPFields()
        for case let (name as String, value as String) in http.allHeaderFields {
            if let field = HTTPField.Name(name) { fields[field] = value }
        }
        return (HTTPResponse(status: .init(code: http.statusCode), headerFields: fields), HTTPBody(data))
    }
}

/// Adds the device's bearer token to every request (sync protocol §8).
struct BearerToken: ClientMiddleware {
    let token: String
    func intercept(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String,
                   next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?))
        async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        request.headerFields[.authorization] = "Bearer \(token)"
        return try await next(request, body, baseURL)
    }
}

let arguments = CommandLine.arguments
guard arguments.count == 5, let server = URL(string: arguments[1]),
      let token = ProcessInfo.processInfo.environment["OPENNOTE_TOKEN"], !token.isEmpty else {
    FileHandle.standardError.write(Data("usage: OPENNOTE_TOKEN=… opennote-sync <server-url> <vault-id> <vault-folder> <support-folder>\n".utf8))
    exit(2)
}
let api = OpenAPISyncAPI(serverURL: server, vaultID: arguments[2], transport: URLSessionTransport(),
                         middlewares: [BearerToken(token: token)])
do {
    let engine = try SyncEngine(root: URL(fileURLWithPath: arguments[3], isDirectory: true),
                                supportDirectory: URL(fileURLWithPath: arguments[4], isDirectory: true),
                                vaultID: arguments[2], api: api)
    try await engine.sync()
    for file in try await engine.flaggedFiles() {
        print("\(file.flag ?? "") \(file.localPath ?? file.remotePath ?? file.fileID)")
    }
} catch {
    FileHandle.standardError.write(Data("sync failed: \(error)\n".utf8))
    exit(1)
}
