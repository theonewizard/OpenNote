/// Obsidian-compatible link resolution (storage contract §2.5), the Swift twin of
/// `backend/app/notes/links.py`.
public enum LinkResolver {
    /// The vault path `link` points to, or nil when unresolved. Comparison is NFC and
    /// case-insensitive; ambiguous names prefer the linking file's folder, then the shortest
    /// path, then lexical order.
    public static func resolve(_ link: Link, from fromPath: String, in paths: [String]) -> String? {
        if link.target.isEmpty { return fromPath }
        var byKey: [String: String] = [:]
        for p in paths { byKey[VaultPath.casefoldKey(p)] = p }
        let folder = dirname(fromPath)
        let candidates = candidates(link.target)
        if link.target.unicodeScalars.contains("/") {
            for base in ["", folder] {
                for candidate in candidates {
                    let joined = normpath(base.isEmpty || candidate.scalarsStart(with: "/") ? candidate : base + "/" + candidate)
                    if !joined.scalarsStart(with: "../") && joined != "..",
                       let hit = byKey[VaultPath.casefoldKey(joined)] {
                        return hit
                    }
                }
            }
            return nil
        }
        let names = Set(candidates.map(VaultPath.casefoldKey))
        let matches = paths.filter { names.contains(VaultPath.casefoldKey(basename($0))) }
        func key(_ p: String) -> (Int, Int, Int) {
            (dirname(p) == folder ? 0 : 1, count(p), p.unicodeScalars.count)
        }
        return matches.min { a, b in
            let (ka, kb) = (key(a), key(b))
            return ka != kb ? ka < kb : a.unicodeScalars.lexicographicallyPrecedes(b.unicodeScalars)
        }
    }

    private static func count(_ p: String) -> Int { p.unicodeScalars.filter { $0 == "/" }.count }

    private static func candidates(_ target: String) -> [String] {
        let name = basename(target)
        return name.unicodeScalars.contains(".") && !name.scalarsEnd(with: ".") ? [target] : [target, target + ".md"]
    }

    private static func basename(_ p: String) -> String { p.scalarSplit("/").last ?? p }

    /// `posixpath.dirname`.
    private static func dirname(_ p: String) -> String {
        let scalars = Array(p.unicodeScalars)
        guard let slash = scalars.lastIndex(of: "/") else { return "" }
        var head = scalars[...slash]
        if !head.allSatisfy({ $0 == "/" }) {
            while head.last == "/" { head.removeLast() }
        }
        return String(String.UnicodeScalarView(head))
    }

    /// `posixpath.normpath` for the relative and absolute paths links produce.
    static func normpath(_ p: String) -> String {
        if p.isEmpty { return "." }
        let absolute = p.scalarsStart(with: "/")
        var out: [String] = []
        for part in p.scalarSplit("/") where !part.isEmpty && part != "." {
            if part != ".." || (!absolute && (out.isEmpty || out.last == "..")) {
                out.append(part)
            } else if !out.isEmpty {
                out.removeLast()
            }
        }
        let joined = (absolute ? "/" : "") + out.joined(separator: "/")
        return joined.isEmpty ? "." : joined
    }
}
