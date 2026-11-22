import Foundation
import OpenAPIRuntime

/// Client for the OpenNote server API. Phase 0 placeholder.
public enum OpenNoteAPI {
    public static let moduleName = "OpenNoteAPI"
}

/// The server writes RFC 3339 timestamps with fractional seconds, except when they are zero
/// (Python's `isoformat`). The runtime's own transcoders accept one form or the other.
struct ServerDates: DateTranscoder {
    func encode(_ date: Date) throws -> String {
        date.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))
    }

    func decode(_ text: String) throws -> Date {
        if let date = try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(text) { return date }
        return try Date.ISO8601FormatStyle().parse(text)
    }
}

extension Client {
    /// The generated client for an OpenNote server, reading timestamps as the server writes
    /// them. Use this initializer for any call whose answer carries a date.
    public init(server: URL, transport: any ClientTransport, middlewares: [any ClientMiddleware] = []) {
        self.init(serverURL: server, configuration: Configuration(dateTranscoder: ServerDates()),
                  transport: transport, middlewares: middlewares)
    }
}
