import Foundation
import OpenNoteCore
import Testing

@Test func sha256MatchesStorageContract() {
    #expect(ContentHash.sha256(Data("hello\n".utf8)) ==
        "sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03")
}

@Test func sha256OfEmptyInput() {
    #expect(ContentHash.sha256(Data()) ==
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
}
