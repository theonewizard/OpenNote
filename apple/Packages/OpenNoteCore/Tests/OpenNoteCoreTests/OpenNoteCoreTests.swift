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

@Suite struct NewFileNameTests {
    @Test func sanitizedNamesPassThePathRules() {
        let names = ["My: note?.md", "..hidden", "trailing. ", "a/b\\c", "CON.md", "", "#tag [x]|y^.md", "tab\there",
                     String(repeating: "é", count: 200) + ".md", "Cafe\u{301}.md"]
        for name in names {
            let clean = VaultPath.sanitizedName(name, note: name.hasSuffix(".md"))
            #expect(VaultPath.validate(clean, note: name.hasSuffix(".md")).isEmpty, "\(name) -> \(clean)")
        }
    }

    @Test func sanitizedNameKeepsWhatIsAllowed() {
        #expect(VaultPath.sanitizedName("Plan 2026.md", note: true) == "Plan 2026.md")
        #expect(VaultPath.sanitizedName("My: note?.md", note: true) == "My- note-.md")
        #expect(VaultPath.sanitizedName("photo #1.png") == "photo #1.png")
        #expect(VaultPath.sanitizedName("", note: true) == "Untitled")
        #expect(VaultPath.sanitizedName("Cafe\u{301}.md", note: true) == "Café.md")
        #expect(VaultPath.sanitizedName(String(repeating: "é", count: 200) + ".md", note: true).hasSuffix(".md"))
    }

    @Test func capturedTextIsNamedAfterItsFirstLine() {
        #expect(VaultPath.noteName(forText: "\n## Shopping list\nmilk", fallback: "Note") == "Shopping list.md")
        #expect(VaultPath.noteName(forText: "https://example.com/a?b=1", fallback: "Note") == "https---example.com-a-b=1.md")
        #expect(VaultPath.noteName(forText: " \n", fallback: "Note 2026-11-22") == "Note 2026-11-22.md")
        #expect(VaultPath.noteName(forText: String(repeating: "x", count: 200), fallback: "Note").count == 63)
    }

    @Test func freePathNumbersBeforeTheExtensionAndIgnoresCase() {
        #expect(VaultPath.freePath("Notes/Untitled.md", taken: []) == "Notes/Untitled.md")
        #expect(VaultPath.freePath("Notes/Untitled.md", taken: ["notes/UNTITLED.md"]) == "Notes/Untitled 1.md")
        #expect(VaultPath.freePath("Untitled.md", taken: ["Untitled.md", "Untitled 1.md"]) == "Untitled 2.md")
        #expect(VaultPath.freePath("a.b/README", taken: ["a.b/README"]) == "a.b/README 1")
    }
}
