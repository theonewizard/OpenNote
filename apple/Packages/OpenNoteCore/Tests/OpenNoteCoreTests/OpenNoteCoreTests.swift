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

@Suite struct LinkResolverTests {
    let paths = ["Welcome.md", "Notes/Plan.md", "Projects/Plan.md", "Projects/Deep/Plan.md",
                 "Attachments/pixel.png", "Notes/Café.md"]

    func link(_ target: String) -> Link {
        Link(target: target, heading: nil, block: nil, alias: nil, embed: false, markdown: false)
    }

    @Test func headingOnlyLinkPointsAtItself() {
        #expect(LinkResolver.resolve(link(""), from: "Notes/Plan.md", in: paths) == "Notes/Plan.md")
    }

    @Test func ambiguousNamePrefersOwnFolderThenShortestPath() {
        #expect(LinkResolver.resolve(link("plan"), from: "Projects/Deep/x.md", in: paths) == "Projects/Deep/Plan.md")
        #expect(LinkResolver.resolve(link("Plan"), from: "Welcome.md", in: paths) == "Notes/Plan.md")
    }

    @Test func pathLinksResolveFromRootThenOwnFolder() {
        #expect(LinkResolver.resolve(link("Projects/Plan"), from: "Welcome.md", in: paths) == "Projects/Plan.md")
        #expect(LinkResolver.resolve(link("Deep/Plan.md"), from: "Projects/x.md", in: paths) == "Projects/Deep/Plan.md")
        #expect(LinkResolver.resolve(link("../Welcome"), from: "Notes/x.md", in: paths) == "Welcome.md")
        #expect(LinkResolver.resolve(link("../../Welcome"), from: "Notes/x.md", in: paths) == nil)
    }

    @Test func attachmentsKeepTheirExtensionAndMatchingIgnoresCaseAndNormalization() {
        #expect(LinkResolver.resolve(link("PIXEL.png"), from: "Welcome.md", in: paths) == "Attachments/pixel.png")
        #expect(LinkResolver.resolve(link("Cafe\u{301}"), from: "Welcome.md", in: paths) == "Notes/Café.md")
        #expect(LinkResolver.resolve(link("Missing"), from: "Welcome.md", in: paths) == nil)
    }
}
