import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenNoteStorage
@testable import OpenNoteSync
import Synchronization
import Testing

/// Answers each request with `respond`, after recording it with its body.
final class StubTransport: ClientTransport, Sendable {
    typealias Respond = @Sendable (HTTPRequest, Data?) throws -> (HTTPResponse, HTTPBody?)
    let respond: Respond

    init(_ respond: @escaping Respond) { self.respond = respond }

    func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL,
              operationID: String) async throws -> (HTTPResponse, HTTPBody?) {
        var data: Data?
        if let body { data = try await Data(collecting: body, upTo: 1 << 24) }
        return try respond(request, data)
    }
}

/// A value the stub's @Sendable closures can record into.
final class Locked<Value: Sendable>: Sendable {
    private let value: Mutex<Value>
    init(_ value: Value) { self.value = Mutex(value) }
    func with<R: Sendable>(_ body: (inout Value) -> R) -> R { value.withLock { body(&$0) } }
}

let vault = "0192f5c6-0000-7000-8000-000000000001"
let server = URL(string: "https://notes.example")!

func api(_ respond: @escaping StubTransport.Respond) -> OpenAPISyncAPI {
    OpenAPISyncAPI(serverURL: server, vaultID: vault, transport: StubTransport(respond))
}

func json(_ status: Int, _ text: String, type: String = "application/json") -> (HTTPResponse, HTTPBody?) {
    (HTTPResponse(status: .init(code: status), headerFields: [.contentType: type]), HTTPBody(text))
}

@Suite struct OpenAPISyncAPITests {
    @Test func changesDecodeNullableFieldsAndA410MeansReconcile() async throws {
        let paths = Locked<[String]>([])
        let ok = api { request, _ in
            paths.with { $0.append(request.path ?? "") }
            return json(200, """
                {"entries": [{"seq": 7, "file_id": "f1", "revision": 2, "path": "a.md", "kind": "note",
                  "content_hash": null, "size": 0, "deleted": true, "device_id": "d", "op": "delete"}],
                 "next_cursor": "c2", "has_more": false}
                """)
        }
        let page = try await ok.changes(after: "c1")
        #expect(page == ChangesPage(entries: [RemoteEntry(seq: 7, fileID: "f1", revision: 2, path: "a.md", kind: "note",
                                                          contentHash: nil, size: 0, deleted: true)],
                                    nextCursor: "c2", hasMore: false))
        let path = paths.with { $0.first ?? "" }
        #expect(path.hasPrefix("/api/v1/sync/\(vault)/changes?"))
        #expect(path.contains("cursor=c1"))
        let gone = api { _, _ in
            json(410, #"{"type": "x", "title": "Cursor expired", "status": 410}"#, type: "application/problem+json")
        }
        await #expect(throws: SyncAPIError.cursorExpired) { try await gone.changes(after: "c0") }
    }

    @Test func pushSendsTheOperationsAndReadsTheProblem() async throws {
        let sent = Locked<(HTTPRequest?, Data?)>((nil, nil))
        let client = api { request, body in
            sent.with { $0 = (request, body) }
            return json(200, """
                {"results": [
                  {"status": "applied", "file_id": "f1", "revision": 1, "seq": 3, "content_hash": "sha256:01",
                   "path": "a.md", "problem": null},
                  {"status": "conflict", "file_id": "copy", "revision": 1, "seq": 4, "content_hash": "sha256:02",
                   "path": "b (conflict Mac 2026-11-19).md",
                   "problem": {"type": "https://opennote.example/problems/conflict", "title": "Conflict",
                               "status": 409, "original_file_id": "f2"}}]}
                """)
        }
        let ops = [
            OutboxOp(clientOpID: "c1", fileID: "f1", op: .create, path: "a.md", kind: .note,
                     contentHash: "sha256:01", createdAt: 0),
            OutboxOp(clientOpID: "c2", fileID: "f2", op: .update, kind: .note, baseRevision: 3,
                     contentHash: "sha256:02", createdAt: 0),
        ]
        let results = try await client.push(ops, idempotencyKey: "0192f5c6-0000-7000-8000-0000000000ff")
        #expect(results.map(\.status) == [.applied, .conflict])
        #expect(results[0].revision == 1 && results[0].problemType == nil)
        #expect(results[1].originalFileID == "f2")
        let (request, body) = sent.with { $0 }
        #expect(request?.method == .post)
        #expect(request?.headerFields[HTTPField.Name("Idempotency-Key")!] == "0192f5c6-0000-7000-8000-0000000000ff")
        let decoded = try JSONSerialization.jsonObject(with: body ?? Data()) as? [String: Any]
        let operations = decoded?["operations"] as? [[String: Any]] ?? []
        #expect(operations.count == 2)
        #expect(operations.first?["op"] as? String == "create")
        #expect(operations.first?["kind"] as? String == "note")
        #expect(operations.last?["op"] as? String == "update")
        #expect(operations.last?["base_revision"] as? Int == 3)
    }

    @Test func blobsUseHeadAndContentRangeWithUploadOffset() async throws {
        let seen = Locked<[HTTPRequest]>([])
        let offset = HTTPField.Name("Upload-Offset")!
        let client = api { request, _ in
            seen.with { $0.append(request) }
            switch request.method {
            case .head: return (HTTPResponse(status: .notFound, headerFields: [offset: "5"]), nil)
            default: return (HTTPResponse(status: .accepted, headerFields: [offset: "10"]), nil)
            }
        }
        #expect(try await client.headBlob("ab") == .missing(uploadOffset: 5))
        let range = BlobRange(first: 5, last: 9, total: 20)
        #expect(try await client.putBlob("ab", Data("56789".utf8), range: range) == .continueAt(10))
        let put = seen.with { $0.last }
        #expect(put?.path == "/api/v1/blobs/ab?vault_id=\(vault)")
        #expect(put?.headerFields[HTTPField.Name("Content-Range")!] == "bytes 5-9/20")
        let done = api { _, _ in (HTTPResponse(status: .noContent), nil) }
        #expect(try await done.putBlob("ab", Data(), range: nil) == .stored)
    }

    @Test func eventsBecomeHints() async throws {
        let client = api { _, _ in
            json(200, """
                retry: 5000

                event: ready
                data: {"vaults":["v1"]}

                : keep-alive

                event: change
                data: {"vault_id":"v1","seq":7}


                """, type: "text/event-stream")
        }
        var hints: [SyncHint] = []
        for try await hint in try await client.events() { hints.append(hint) }
        #expect(hints == [.ready(vaults: ["v1"]), .change(vaultID: "v1", seq: 7)])
    }
}
