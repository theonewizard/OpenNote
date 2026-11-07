import Foundation
import OpenNoteCore

/// The shared compatibility corpus and parity fixtures at the repository root
/// (`tests/compatibility`), found from this file's path.
enum Fixtures {
    static let compatibility = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()  // OpenNoteCoreTests
        .deletingLastPathComponent()  // Tests
        .deletingLastPathComponent()  // OpenNoteCore
        .deletingLastPathComponent()  // Packages
        .deletingLastPathComponent()  // apple
        .deletingLastPathComponent()  // repository root
        .appendingPathComponent("tests/compatibility")

    /// Corpus cases holding a single `note.md`, by name.
    static var noteCases: [String] {
        let vaults = compatibility.appendingPathComponent("vaults")
        let names = (try? FileManager.default.contentsOfDirectory(atPath: vaults.path)) ?? []
        return names.filter {
            FileManager.default.fileExists(atPath: vaults.appendingPathComponent("\($0)/note.md").path)
        }.sorted()
    }

    static func note(_ name: String) throws -> Data {
        try Data(contentsOf: compatibility.appendingPathComponent("vaults/\(name)/note.md"))
    }

    static func expected(_ name: String) throws -> JSON {
        try JSON.load(compatibility.appendingPathComponent("vaults/\(name)/expected.json"))
    }

    static func parity(_ file: String) throws -> [JSON] {
        guard case let .array(cases) = try JSON.load(compatibility.appendingPathComponent("parity/\(file)")) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        return cases
    }
}

/// A decoded JSON value; objects keep no order (Python dict equality).
enum JSON: Decodable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSON])
    case object([String: JSON])

    static func load(_ url: URL) throws -> JSON {
        try JSONDecoder().decode(JSON.self, from: Data(contentsOf: url))
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let d = try? c.decode(Double.self) { self = .number(d) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSON].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSON].self)) }
    }

    subscript(key: String) -> JSON? {
        if case let .object(o) = self { return o[key] }
        return nil
    }

    var string: String? {
        if case let .string(s) = self { return s }
        return nil
    }

    var bool: Bool? {
        if case let .bool(b) = self { return b }
        return nil
    }

    var array: [JSON]? {
        if case let .array(a) = self { return a }
        return nil
    }

    /// The frontmatter value this JSON stands for.
    var property: PropertyValue {
        switch self {
        case .null: .null
        case let .bool(b): .bool(b)
        case let .number(d): .double(d)
        case let .string(s): .string(s)
        case let .array(a): .array(a.map(\.property))
        case let .object(o): .object(o.propertyMap)
        }
    }
}

extension [String: JSON] {
    var propertyMap: PropertyMap {
        var map = PropertyMap()
        for (k, v) in self { map[k] = v.property }
        return map
    }
}

extension Link {
    /// The shape of a link in expected.json and the parity fixtures.
    func json(includeEmbed: Bool) -> JSON {
        func opt(_ s: String?) -> JSON { s.map(JSON.string) ?? .null }
        var o: [String: JSON] = [
            "target": .string(target), "heading": opt(heading), "block": opt(block),
            "alias": opt(alias), "markdown": .bool(markdown),
        ]
        if includeEmbed { o["embed"] = .bool(embed) }
        return .object(o)
    }
}
