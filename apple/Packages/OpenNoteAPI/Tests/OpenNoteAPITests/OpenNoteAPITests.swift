import OpenNoteAPI
import Testing

@Test func moduleNameIsSet() {
    #expect(OpenNoteAPI.moduleName == "OpenNoteAPI")
}

// Compiles only when swift-openapi-generator's plugin generated the client from openapi.json.
@Test func generatedClientExists() {
    #expect(String(describing: Client.self) == "Client")
}
