import Foundation
import OpenNoteCore
import Testing

/// The compatibility corpus (testing strategy §3): the invariants the Python suite checks in
/// backend/tests/compatibility, against the same files.
@Suite struct CorpusTests {
    @Test func corpusIsPresent() {
        #expect(Fixtures.noteCases.count >= 25)
    }

    @Test(arguments: Fixtures.noteCases)
    func roundTripIsByteIdentical(_ name: String) throws {
        let raw = try Fixtures.note(name)
        let doc = NoteDocument(raw)
        #expect(doc.raw == raw)
        if let body = doc.bodyText {
            #expect(try doc.replacing(doc.body, with: body) == raw)
        }
    }

    @Test(arguments: Fixtures.noteCases)
    func frontmatterMatchesExpected(_ name: String) throws {
        let expected = try Fixtures.expected(name)
        let (props, error) = Frontmatter.readProperties(NoteDocument(try Fixtures.note(name)))
        #expect(error == expected["frontmatter_error"]?.bool)
        if case let .object(o)? = expected["frontmatter"] {
            #expect(props == o.propertyMap)
        } else {
            #expect(props == nil)
        }
    }

    @Test(arguments: Fixtures.noteCases)
    func extractionMatchesExpected(_ name: String) throws {
        let expected = try Fixtures.expected(name)
        guard expected["links"] != nil else { return }
        let result = Extractor.extract(NoteDocument(try Fixtures.note(name)))
        #expect(.array(result.links.filter { !$0.embed }.map { $0.json(includeEmbed: false) }) == expected["links"])
        #expect(.array(result.links.filter(\.embed).map { $0.json(includeEmbed: false) }) == expected["embeds"])
        #expect(.array(result.tags.map(JSON.string)) == expected["tags"])
        #expect(.array(result.externalURLs.map(JSON.string)) == expected["external_urls"])
    }

    @Test func tenMegabyteNoteRoundTrips() throws {
        let line = Data("- line of a large note\n".utf8)
        var raw = Data()
        while raw.count < 10 * 1024 * 1024 { raw.append(line) }
        raw = raw.prefix(10 * 1024 * 1024)
        let doc = NoteDocument(raw)
        #expect(doc.raw == raw)
        #expect(try doc.replacing(doc.body, with: doc.bodyText!) == raw)
    }
}
