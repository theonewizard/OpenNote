import OpenNoteStorage
import Testing

@Test func moduleNameIsSet() {
    #expect(OpenNoteStorage.moduleName == "OpenNoteStorage")
}

@Test func linksDependencies() {
    #expect(OpenNoteStorage.coreVersion == "0.1.0")
}
