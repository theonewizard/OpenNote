import OpenNoteAPI
import OpenNoteCore
import OpenNoteStorage

/// Sync engine: outbox and pull/push loop. Phase 0 placeholder.
public enum OpenNoteSync {
    public static let moduleName = "OpenNoteSync"
    public static let coreVersion = OpenNoteCore.version
    public static let dependencyModules = [OpenNoteStorage.moduleName, OpenNoteAPI.moduleName]
}
