import Foundation
import OpenNoteCore
import Testing

/// tests/compatibility/parity: inputs with the Python parsers' answers, one rule at a time.
@Suite struct ParityTests {
    @Test func frontmatterMatchesPython() throws {
        for c in try Fixtures.parity("frontmatter.json") {
            let yaml = c["yaml"]!.string!
            let doc = NoteDocument(Data("---\n\(yaml)\n---\nBody\n".utf8))
            let (props, error) = Frontmatter.readProperties(doc)
            #expect(error == c["frontmatter_error"]!.bool!, "frontmatter_error for \(yaml.debugDescription)")
            let expected: PropertyMap? = if case let .object(o)? = c["frontmatter"] { o.propertyMap } else { nil }
            #expect(props == expected, "properties for \(yaml.debugDescription)")
        }
    }

    @Test func pathRulesMatchPython() throws {
        for c in try Fixtures.parity("paths.json") {
            let path = c["path"]!.string!
            #expect(Array(VaultPath.normalize(path).unicodeScalars) == Array(c["normalized"]!.string!.unicodeScalars),
                    "normalize \(path.debugDescription)")
            #expect(Array(VaultPath.casefoldKey(path).unicodeScalars) == Array(c["casefold_key"]!.string!.unicodeScalars),
                    "casefold_key \(path.debugDescription)")
            #expect(VaultPath.classify(path).rawValue == c["kind"]!.string!, "classify \(path.debugDescription)")
            for (note, key) in [(true, "violations_note"), (false, "violations_attachment")] {
                let got = VaultPath.validate(path, note: note).map { v -> JSON in
                    .object(["code": .string(v.code), "segment": v.segment.map(JSON.string) ?? .null])
                }
                #expect(.array(got) == c[key]!, "\(key) for \(path.debugDescription)")
            }
        }
    }

    @Test func extractionMatchesPython() throws {
        for c in try Fixtures.parity("extraction.json") {
            let body = c["body"]!.string!
            let result = Extractor.extract(NoteDocument(Data(body.utf8)))
            #expect(.array(result.links.map { $0.json(includeEmbed: true) }) == c["links"]!,
                    "links in \(body.debugDescription)")
            #expect(.array(result.tags.map(JSON.string)) == c["tags"]!, "tags in \(body.debugDescription)")
            #expect(.array(result.externalURLs.map(JSON.string)) == c["external_urls"]!,
                    "external URLs in \(body.debugDescription)")
        }
    }
}
