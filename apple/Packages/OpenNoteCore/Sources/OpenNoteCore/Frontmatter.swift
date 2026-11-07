import Foundation
import Yams

/// A frontmatter value as the backend reports it (JSON-shaped; dates as ISO strings).
public indirect enum PropertyValue: Sendable, Equatable, CustomStringConvertible {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([PropertyValue])
    case object(PropertyMap)

    /// Python's `==`: an int equals the float of the same value (YAML `1` vs `1.0`).
    public static func == (lhs: PropertyValue, rhs: PropertyValue) -> Bool {
        switch (lhs, rhs) {
        case (.null, .null): true
        case let (.bool(a), .bool(b)): a == b
        case let (.int(a), .int(b)): a == b
        case let (.double(a), .double(b)): a == b
        case let (.int(a), .double(b)), let (.double(b), .int(a)): Double(a) == b
        case let (.string(a), .string(b)): a == b
        case let (.array(a), .array(b)): a == b
        case let (.object(a), .object(b)): a == b
        default: false
        }
    }

    public var description: String {
        switch self {
        case .null: "null"
        case let .bool(b): "\(b)"
        case let .int(i): "\(i)"
        case let .double(d): "\(d)"
        case let .string(s): "\"\(s)\""
        case let .array(a): "[\(a.map(\.description).joined(separator: ", "))]"
        case let .object(o): "{\(o.keys.map { "\"\($0)\": \(o[$0]!)" }.joined(separator: ", "))}"
        }
    }
}

/// An ordered string-keyed mapping. Equality ignores order, like a Python dict.
public struct PropertyMap: Sendable, Equatable {
    public private(set) var keys: [String] = []
    private var values: [String: PropertyValue] = [:]

    public init() {}

    public subscript(key: String) -> PropertyValue? {
        get { values[key] }
        set {
            if newValue == nil {
                keys.removeAll { $0 == key }
            } else if values[key] == nil {
                keys.append(key)
            }
            values[key] = newValue
        }
    }

    public var count: Int { keys.count }

    public static func == (lhs: PropertyMap, rhs: PropertyMap) -> Bool { lhs.values == rhs.values }
}

/// The frontmatter is not a valid YAML mapping; the body stays editable.
public struct FrontmatterInvalid: Error, Equatable {
    public let reason: String
}

/// Reading frontmatter properties (storage contract §2.2), the Swift twin of
/// `read_properties` in `backend/app/notes/frontmatter.py`.
///
/// The YAML is parsed by Yams (libyaml) into nodes; scalars are resolved here with the rules
/// of ruamel.yaml's round-trip loader (YAML 1.2 core schema plus timestamps and `<<` merge
/// keys), so both implementations agree on the compatibility corpus and on
/// `tests/compatibility/parity/frontmatter.json`.
public enum Frontmatter {
    public static let listKeys = ["tags", "aliases"]

    /// (properties, frontmatterError). `tags` and `aliases` are always lists when they are
    /// strings: the legacy comma-separated form is split.
    public static func readProperties(_ doc: NoteDocument) -> (PropertyMap?, Bool) {
        let data: PropertyMap?
        do {
            data = try load(doc)
        } catch {
            return (nil, true)
        }
        guard var props = data else { return (nil, false) }
        for key in listKeys {
            if case let .string(s)? = props[key] {
                props[key] = .array(s.split(separator: ",", omittingEmptySubsequences: false)
                    .map { String($0).pyStrip() }.filter { !$0.isEmpty }.map(PropertyValue.string))
            }
        }
        return (props, false)
    }

    /// The frontmatter mapping (nil when there is none); `FrontmatterInvalid` when it is not
    /// a YAML mapping.
    public static func load(_ doc: NoteDocument) throws -> PropertyMap? {
        guard let yaml = doc.frontmatterText else { return nil }
        let node: Node?
        do {
            node = try Yams.compose(yaml: yaml, .basic)
        } catch {
            throw FrontmatterInvalid(reason: "frontmatter is not valid YAML")
        }
        guard let node else { return PropertyMap() }
        if case let .scalar(s) = node, s.style == .plain, case .null = try resolvePlain(s.string) {
            return PropertyMap()  // e.g. only comments: ruamel loads None
        }
        guard case let .mapping(mapping) = node else {
            throw FrontmatterInvalid(reason: "frontmatter is not a mapping")
        }
        return try convert(mapping)
    }

    // MARK: - Nodes to values

    private static func convert(_ node: Node) throws -> PropertyValue {
        switch node {
        case let .scalar(s): return try scalar(s)
        case let .sequence(seq): return .array(try seq.map(convert))
        case let .mapping(m): return .object(try convert(m))
        case .alias: throw FrontmatterInvalid(reason: "unresolved alias")
        }
    }

    private static func convert(_ mapping: Node.Mapping) throws -> PropertyMap {
        var out = PropertyMap()
        var merged: [Node.Mapping] = []
        for (key, value) in mapping {
            if case let .scalar(k) = key, k.style == .plain, k.string == "<<" {
                switch value {
                case let .mapping(m): merged.append(m)
                case let .sequence(seq):
                    for item in seq {
                        guard case let .mapping(m) = item else {
                            throw FrontmatterInvalid(reason: "merge item is not a mapping")
                        }
                        merged.append(m)
                    }
                default: throw FrontmatterInvalid(reason: "merge value is not a mapping")
                }
                continue
            }
            out[try keyString(key)] = try convert(value)
        }
        // Explicit keys win over merged ones; among merged mappings the first wins.
        for m in merged {
            let sub = try convert(m)
            for k in sub.keys where out[k] == nil { out[k] = sub[k] }
        }
        return out
    }

    /// Python's `str(key)` of the constructed key, as `_plain` in frontmatter.py does it.
    private static func keyString(_ key: Node) throws -> String {
        guard case let .scalar(s) = key else {
            throw FrontmatterInvalid(reason: "only scalar keys are supported")
        }
        guard s.style == .plain else { return s.string }
        switch try resolvePlain(s.string) {
        case .null: return "None"
        case let .bool(b): return b ? "True" : "False"
        case let .int(i): return String(i)
        case let .double(d): return pyFloatRepr(d)
        case let .string(str): return str
        case let .timestamp(iso, hasTime): return hasTime ? iso.replacingOccurrences(of: "T", with: " ") : iso
        }
    }

    private static func scalar(_ s: Node.Scalar) throws -> PropertyValue {
        guard s.style == .plain else { return .string(s.string) }
        // An explicit tag (`!!str 5`, `!custom x`) keeps the text. ruamel hands back a
        // TaggedScalar there, which the backend cannot serialize; text is the useful reading.
        // Untagged scalars have the empty (implicit) tag name.
        if !s.tag.rawValue.isEmpty { return .string(s.string) }
        switch try resolvePlain(s.string) {
        case .null: return .null
        case let .bool(b): return .bool(b)
        case let .int(i): return .int(i)
        // JSON has no infinity or NaN; the backend reports such a value as its text too.
        case let .double(d): return d.isFinite ? .double(d) : .string(s.string)
        case let .string(str): return .string(str)
        case let .timestamp(iso, _): return .string(iso)
        }
    }

    // MARK: - ruamel.yaml's YAML 1.2 implicit resolvers

    enum Resolved {
        case null, bool(Bool), int(Int), double(Double), string(String)
        case timestamp(String, hasTime: Bool)
    }

    private static let boolRE = regex("^(?:true|True|TRUE|false|False|FALSE)$")
    private static let floatRE = regex("""
        ^(?:[-+]?(?:[0-9][0-9_]*)\\.[0-9_]*(?:[eE][-+]?[0-9]+)?\
        |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)\
        |[-+]?\\.[0-9_]+(?:[eE][-+][0-9]+)?\
        |[-+]?\\.(?:inf|Inf|INF)\
        |\\.(?:nan|NaN|NAN))$
        """)
    private static let intRE = regex("^(?:[-+]?0b[0-1_]+|[-+]?0o?[0-7_]+|[-+]?[0-9_]+|[-+]?0x[0-9a-fA-F_]+)$")
    private static let nullRE = regex("^(?:~|null|Null|NULL|)$")
    private static let timestampRE = regex("""
        ^([0-9]{4})-([0-9][0-9]?)-([0-9][0-9]?)\
        (?:(?:[Tt]|[ \\t]+)([0-9][0-9]?):([0-9][0-9]):([0-9][0-9])(?:\\.([0-9]*))?\
        (?:[ \\t]*(Z|([-+])([0-9][0-9]?)(?::([0-9][0-9]))?))?)?$
        """)
    // The resolver's own pattern: a date alone must be YYYY-MM-DD.
    private static let timestampResolveRE = regex("""
        ^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}\
        |[0-9]{4}-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \\t]+)[0-9][0-9]?:[0-9]{2}:[0-9]{2}(?:\\.[0-9]*)?\
        (?:[ \\t]*(?:Z|[-+][0-9][0-9]?(?::[0-9]{2})?))?)$
        """)

    private static func regex(_ pattern: String) -> NSRegularExpression {
        // swiftlint:disable:next force_try
        try! NSRegularExpression(pattern: pattern)
    }

    private static func matches(_ re: NSRegularExpression, _ s: String) -> Bool {
        re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    /// The value ruamel.yaml constructs for a plain scalar. Throws where ruamel raises
    /// (an impossible date).
    static func resolvePlain(_ s: String) throws -> Resolved {
        let first = s.unicodeScalars.first
        func firstIn(_ chars: String) -> Bool { first.map { chars.unicodeScalars.contains($0) } ?? false }
        if firstIn("tTfF") && matches(boolRE, s) { return .bool(s.first == "t" || s.first == "T") }
        if firstIn("-+0123456789.") && matches(floatRE, s) { return .double(constructFloat(s)) }
        if firstIn("-+0123456789") && matches(intRE, s) { return constructInt(s) }
        if (first == nil || firstIn("~nN")) && matches(nullRE, s) { return .null }
        if firstIn("0123456789") && matches(timestampResolveRE, s) { return try constructTimestamp(s) }
        return .string(s)
    }

    private static func constructFloat(_ s: String) -> Double {
        var v = s.replacingOccurrences(of: "_", with: "").lowercased()
        var sign = 1.0
        if v.hasPrefix("-") { sign = -1; v.removeFirst() } else if v.hasPrefix("+") { v.removeFirst() }
        if v.contains("inf") { return sign * .infinity }
        if v.contains("nan") { return .nan }
        // Python's float() accepts "3.", ".5" and "3.e2"; give Swift a digit on both sides.
        if v.hasPrefix(".") { v = "0" + v }
        v = v.replacingOccurrences(of: ".e", with: ".0e")
        if v.hasSuffix(".") { v += "0" }
        return sign * (Double(v) ?? .nan)
    }

    private static func constructInt(_ s: String) -> Resolved {
        var v = s.replacingOccurrences(of: "_", with: "")
        var negative = false
        if v.hasPrefix("-") { negative = true; v.removeFirst() } else if v.hasPrefix("+") { v.removeFirst() }
        var radix = 10
        for (prefix, r) in [("0b", 2), ("0x", 16), ("0o", 8)] where v.hasPrefix(prefix) {
            radix = r
            v.removeFirst(2)
        }
        if v.isEmpty { return .int(0) }  // "_" after the sign only; ruamel gives 0 too
        if let magnitude = Int(v, radix: radix) { return .int(negative ? -magnitude : magnitude) }
        // Beyond Int64: Python keeps an exact int; the nearest double is as close as JSON gets.
        let d = radix == 10 ? Double(v) ?? .nan  // correctly rounded
            : v.reduce(0.0) { $0 * Double(radix) + Double(Int(String($1), radix: radix) ?? 0) }
        return .double(negative ? -d : d)
    }

    /// `create_timestamp` in ruamel.yaml.util, then Python's `isoformat()`.
    private static func constructTimestamp(_ s: String) throws -> Resolved {
        guard let m = timestampRE.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else {
            return .string(s)
        }
        func group(_ i: Int) -> String? { Range(m.range(at: i), in: s).map { String(s[$0]) } }
        let year = Int(group(1)!)!, month = Int(group(2)!)!, day = Int(group(3)!)!
        guard (1...9999).contains(year), (1...12).contains(month),
              (1...daysIn(month, year)).contains(day) else {
            throw FrontmatterInvalid(reason: "day is out of range for month")
        }
        let date = String(format: "%04d-%02d-%02d", year, month, day)
        guard let hourText = group(4) else { return .timestamp(date, hasTime: false) }
        var (y, mo, d) = (year, month, day)
        var (h, mi, sec) = (Int(hourText)!, Int(group(5)!)!, Int(group(6)!)!)
        guard h < 24, mi < 60, sec < 60 else {
            throw FrontmatterInvalid(reason: "time is out of range")
        }
        var frac = 0
        if let fraction = group(7), !fraction.isEmpty {
            frac = Int(String((fraction + "000000").prefix(6)))!
            if fraction.count > 6, let digit = Int(String(Array(fraction)[6])), digit > 4 { frac += 1 }
            if frac > 999_999 {
                // ruamel rounds .9999995 up by adding a second, carrying into the date.
                frac = 0
                sec += 1
                if sec == 60 { sec = 0; mi += 1 }
                if mi == 60 { mi = 0; h += 1 }
                if h == 24 { h = 0; d += 1 }
                if d > daysIn(mo, y) { d = 1; mo += 1 }
                if mo == 13 { mo = 1; y += 1 }
            }
        }
        var iso = String(format: "%04d-%02d-%02dT%02d:%02d:%02d", y, mo, d, h, mi, sec)
        if frac > 0 { iso += String(format: ".%06d", frac) }
        if let sign = group(9) {
            let tzHour = Int(group(10)!)!, tzMinute = group(11).map { Int($0)! } ?? 0
            guard tzHour * 60 + tzMinute < 24 * 60 else {
                throw FrontmatterInvalid(reason: "offset must be a timedelta strictly between -24h and 24h")
            }
            let zero = tzHour == 0 && tzMinute == 0
            iso += (zero ? "+" : sign) + String(format: "%02d:%02d", tzHour, tzMinute)
        } else if group(8) == "Z" {
            iso += "+00:00"
        }
        return .timestamp(iso, hasTime: true)
    }

    private static func daysIn(_ month: Int, _ year: Int) -> Int {
        switch month {
        case 2: (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 ? 29 : 28
        case 4, 6, 9, 11: 30
        default: 31
        }
    }

    /// Python's `repr(float)` for the common cases (keys only).
    private static func pyFloatRepr(_ d: Double) -> String {
        if d.isNaN { return "nan" }
        if d.isInfinite { return d < 0 ? "-inf" : "inf" }
        return "\(d)"
    }
}

extension String {
    /// Python's `str.strip()`: removes `str.isspace` characters at both ends.
    func pyStrip() -> String {
        let scalars = unicodeScalars
        guard let start = scalars.firstIndex(where: { !$0.isPySpace }) else { return "" }
        let end = scalars.lastIndex(where: { !$0.isPySpace })!
        return String(scalars[start...end])
    }
}

extension Unicode.Scalar {
    /// Python's `str.isspace()` (and `\s` in a `str` pattern).
    var isPySpace: Bool {
        switch value {
        case 0x09...0x0D, 0x1C...0x20, 0x85, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F,
             0x205F, 0x3000: true
        default: false
        }
    }
}
