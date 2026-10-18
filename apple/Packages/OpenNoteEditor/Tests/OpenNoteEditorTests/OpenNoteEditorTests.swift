import OpenNoteEditor
import Testing

@Test func moduleNameIsSet() {
    #expect(OpenNoteEditor.moduleName == "OpenNoteEditor")
}

@Test func linksDependencies() {
    #expect(OpenNoteEditor.coreVersion == "0.1.0")
}
