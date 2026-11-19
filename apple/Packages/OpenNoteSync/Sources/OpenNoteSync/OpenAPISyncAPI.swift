import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenNoteAPI
import OpenNoteStorage

/// `SyncAPI` for one vault over the generated client (`OpenNoteAPI.Client`).
///
/// The blob `HEAD` and `PUT` and the event stream go through the same transport and
/// middlewares by hand: the server's `Upload-Offset` on a 404 or 409 is not in the OpenAPI
/// document, and a `HEAD` 404 has no problem body for the generated client to decode.
public struct OpenAPISyncAPI: SyncAPI {
    let client: Client
    let vaultID: String
    let serverURL: URL
    let transport: any ClientTransport
    let middlewares: [any ClientMiddleware]

    /// `middlewares` carry the device's bearer token (sync protocol §8).
    public init(serverURL: URL, vaultID: String, transport: any ClientTransport,
                middlewares: [any ClientMiddleware] = []) {
        self.client = Client(serverURL: serverURL, transport: transport, middlewares: middlewares)
        self.vaultID = vaultID
        self.serverURL = serverURL
        self.transport = transport
        self.middlewares = middlewares
    }

    // MARK: - Blobs

    public func headBlob(_ sha256: String) async throws -> BlobStatus {
        let (response, _) = try await send(.head, blobPath(sha256), operationID: "head_blob")
        switch response.status.code {
        case 200: return .present
        case 404: return .missing(uploadOffset: Self.uploadOffset(response) ?? 0)
        default: throw SyncAPIError.status(response.status.code, nil)
        }
    }

    public func putBlob(_ sha256: String, _ data: Data, range: BlobRange?) async throws -> ChunkResult {
        var fields = HTTPFields()
        fields[.contentType] = "application/octet-stream"
        if let range { fields[Self.contentRange] = range.header }
        let (response, _) = try await send(.put, blobPath(sha256), fields: fields, body: HTTPBody(data),
                                           operationID: "put_blob")
        switch response.status.code {
        case 204: return .stored
        case 202, 409:
            if let offset = Self.uploadOffset(response) { return .continueAt(offset) }
            throw SyncAPIError.status(response.status.code, nil)
        default: throw SyncAPIError.status(response.status.code, nil)
        }
    }

    public func downloadBlob(_ sha256: String, to file: URL) async throws {
        let output = try await client.getBlob(path: .init(sha256: sha256), query: .init(vaultId: vaultID))
        switch output {
        case let .ok(ok):
            let body = try ok.body.binary
            FileManager.default.createFile(atPath: file.path, contents: nil)
            let handle = try FileHandle(forWritingTo: file)
            defer { try? handle.close() }
            for try await chunk in body {
                try handle.write(contentsOf: chunk)
            }
        case let .default(statusCode, _):
            throw SyncAPIError.status(statusCode, nil)
        }
    }

    // MARK: - Pull and push

    public func changes(after cursor: String?) async throws -> ChangesPage {
        let output = try await client.getChanges(path: .init(vaultId: vaultID), query: .init(cursor: cursor, limit: 500))
        switch output {
        case let .ok(ok):
            let page = try ok.body.json
            return ChangesPage(entries: page.entries.map(Self.entry), nextCursor: page.nextCursor, hasMore: page.hasMore)
        case let .default(statusCode, _):
            if statusCode == 410 { throw SyncAPIError.cursorExpired }
            throw SyncAPIError.status(statusCode, nil)
        }
    }

    public func snapshot(page: String?) async throws -> SnapshotPage {
        let output = try await client.getSnapshot(path: .init(vaultId: vaultID), query: .init(page: page, limit: 1000))
        switch output {
        case let .ok(ok):
            let body = try ok.body.json
            return SnapshotPage(entries: body.entries.map(Self.entry), cursor: body.cursor, nextPage: body.nextPage)
        case let .default(statusCode, _):
            throw SyncAPIError.status(statusCode, nil)
        }
    }

    public func push(_ ops: [OutboxOp], idempotencyKey: String) async throws -> [PushOutcome] {
        let body = Components.Schemas.SyncPush(operations: ops.map { op in
            switch op.op {
            case .create:
                return .create(.init(clientOpId: op.clientOpID, contentHash: op.contentHash ?? "", fileId: op.fileID,
                                     kind: .init(rawValue: op.kind.rawValue)!, op: .init(rawValue: "create")!,
                                     path: op.path ?? ""))
            case .update:
                return .update(.init(baseRevision: Int(op.baseRevision), clientOpId: op.clientOpID,
                                     contentHash: op.contentHash ?? "", fileId: op.fileID,
                                     op: .init(rawValue: "update")!))
            case .move:
                return .move(.init(baseRevision: Int(op.baseRevision), clientOpId: op.clientOpID, fileId: op.fileID,
                                   newPath: op.path ?? "", op: .init(rawValue: "move")!))
            case .delete:
                return .delete(.init(baseRevision: Int(op.baseRevision), clientOpId: op.clientOpID, fileId: op.fileID,
                                     op: .init(rawValue: "delete")!))
            }
        })
        let output = try await client.push(path: .init(vaultId: vaultID), headers: .init(idempotencyKey: idempotencyKey),
                                           body: .json(body))
        switch output {
        case let .ok(ok):
            return try ok.body.json.results.map { result in
                let problem = try result.problem.map { try Self.dictionary($0) } ?? [:]
                return PushOutcome(
                    status: PushOutcome.Status(rawValue: result.status.rawValue) ?? .rejected,
                    fileID: result.fileId, revision: result.revision.map { Int64($0) },
                    contentHash: result.contentHash, path: result.path, problemType: problem["type"] as? String,
                    problemDetail: problem["detail"] as? String, originalFileID: problem["original_file_id"] as? String)
            }
        case let .default(statusCode, _):
            throw SyncAPIError.status(statusCode, nil)
        }
    }

    // MARK: - Change hints

    public func events() async throws -> AsyncThrowingStream<SyncHint, any Error> {
        var fields = HTTPFields()
        fields[.accept] = "text/event-stream"
        let (response, body) = try await send(.get, "/api/v1/events", fields: fields, operationID: "events")
        guard response.status.code == 200, let body else { throw SyncAPIError.status(response.status.code, nil) }
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    for try await event in body.asDecodedServerSentEvents() {
                        if let hint = Self.hint(event) { continuation.yield(hint) }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func hint(_ event: ServerSentEvent) -> SyncHint? {
        guard let data = event.data.flatMap({ $0.data(using: .utf8) }),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        switch event.event {
        case "ready": return .ready(vaults: json["vaults"] as? [String] ?? [])
        case "change":
            guard let vault = json["vault_id"] as? String, let seq = json["seq"] as? Int else { return nil }
            return .change(vaultID: vault, seq: Int64(seq))
        default: return nil
        }
    }

    // MARK: - Helpers

    static let contentRange = HTTPField.Name("Content-Range")!
    static let uploadOffsetName = HTTPField.Name("Upload-Offset")!

    static func uploadOffset(_ response: HTTPResponse) -> Int64? {
        response.headerFields[uploadOffsetName].flatMap { Int64($0) }
    }

    static func entry(_ e: Components.Schemas.SyncEntry) -> RemoteEntry {
        RemoteEntry(seq: Int64(e.seq), fileID: e.fileId, revision: Int64(e.revision), path: e.path, kind: e.kind,
                    contentHash: e.contentHash, size: Int64(e.size), deleted: e.deleted)
    }

    /// The problem object as plain JSON, whatever Swift shape the generator gave it.
    static func dictionary(_ value: some Encodable) throws -> [String: Any] {
        let data = try JSONEncoder().encode(value)
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }

    func blobPath(_ sha256: String) -> String {
        "/api/v1/blobs/\(sha256)?vault_id=\(vaultID)"
    }

    /// One request through the middlewares, outermost first, as the generated client sends it.
    func send(_ method: HTTPRequest.Method, _ path: String, fields: HTTPFields = [:], body: HTTPBody? = nil,
              operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        let request = HTTPRequest(method: method, scheme: nil, authority: nil, path: path, headerFields: fields)
        var next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?) = {
            [transport] request, body, url in
            try await transport.send(request, body: body, baseURL: url, operationID: operationID)
        }
        for middleware in middlewares.reversed() {
            let inner = next
            next = { request, body, url in
                try await middleware.intercept(request, body: body, baseURL: url, operationID: operationID, next: inner)
            }
        }
        return try await next(request, body, serverURL)
    }
}
