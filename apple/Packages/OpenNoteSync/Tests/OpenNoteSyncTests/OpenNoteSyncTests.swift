import OpenNoteSync
import Testing

@Test func moduleNameIsSet() {
    #expect(OpenNoteSync.moduleName == "OpenNoteSync")
}

@Test func linksDependencies() {
    #expect(OpenNoteSync.coreVersion == "0.1.0")
    #expect(OpenNoteSync.dependencyModules == ["OpenNoteStorage", "OpenNoteAPI"])
}
