import OpenNoteAPI
import Testing

@Test func moduleNameIsSet() {
    #expect(OpenNoteAPI.moduleName == "OpenNoteAPI")
}

// Compiles only when swift-openapi-generator's plugin generated the client from openapi.json.
@Test func generatedClientExists() {
    #expect(String(describing: Client.self) == "Client")
}

// Compiles only when nullable properties reach the Swift client: the generator leaves out
// every property spelled `anyOf: [..., {"type": "null"}]` (docs/development/setup.md §8).
@Test func nullablePropertiesAreGenerated() {
    let entry = Components.Schemas.SyncEntry(
        contentHash: nil, deleted: true, deviceId: "d", fileId: "f", kind: "note", op: "delete",
        path: "a.md", revision: 2, seq: 7, size: 0)
    #expect(entry.contentHash == nil)
    let result = Components.Schemas.PushResult(
        contentHash: "sha256:00", fileId: "f", path: "a.md", problem: nil, revision: 3, seq: 9, status: .applied)
    #expect(result.revision == 3)
}
