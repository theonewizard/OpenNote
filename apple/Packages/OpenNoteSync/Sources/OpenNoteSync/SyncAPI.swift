import Foundation
import OpenNoteStorage

/// The server calls the engine makes (sync protocol §§3-5). `OpenAPISyncAPI` implements
/// them over the generated client; tests use an in-memory server.
public protocol SyncAPI: Sendable {
    /// `HEAD /blobs/{sha256}`: present, or missing with the bytes of a resumable upload so far.
    func headBlob(_ sha256: String) async throws -> BlobStatus
    /// `PUT /blobs/{sha256}`, whole (`range` nil) or one chunk with `Content-Range`.
    func putBlob(_ sha256: String, _ data: Data, range: BlobRange?) async throws -> ChunkResult
    /// `GET /blobs/{sha256}`, streamed into `file`. The caller checks the hash.
    func downloadBlob(_ sha256: String, to file: URL) async throws
    /// `GET /sync/{vault}/changes`; throws `SyncAPIError.cursorExpired` on 410.
    func changes(after cursor: String?) async throws -> ChangesPage
    /// `GET /sync/{vault}/snapshot`, one page.
    func snapshot(page: String?) async throws -> SnapshotPage
    /// `POST /sync/{vault}/push`, at most 100 operations; one result per operation, in order.
    func push(_ ops: [OutboxOp], idempotencyKey: String) async throws -> [PushOutcome]
    /// `GET /events`: change hints until the server ends the stream (after 15 minutes).
    func events() async throws -> AsyncThrowingStream<SyncHint, any Error>
}

public enum SyncAPIError: Error, Equatable {
    /// 410: the cursor is older than the tombstone window; reconcile from the snapshot.
    case cursorExpired
    /// Any other unexpected answer: the status and the problem's detail, if any.
    case status(Int, String?)
}

public enum BlobStatus: Sendable, Equatable {
    case present
    case missing(uploadOffset: Int64)
}

/// `bytes first-last/total`.
public struct BlobRange: Sendable, Equatable {
    public let first: Int64
    public let last: Int64
    public let total: Int64

    public init(first: Int64, last: Int64, total: Int64) {
        self.first = first
        self.last = last
        self.total = total
    }

    public var header: String { "bytes \(first)-\(last)/\(total)" }
}

public enum ChunkResult: Sendable, Equatable {
    /// 204: the whole blob is stored.
    case stored
    /// 202 (more to send) or 409 (continue elsewhere): the next chunk starts at `offset`.
    case continueAt(Int64)
}

/// One committed revision (`SyncEntry`).
public struct RemoteEntry: Sendable, Equatable {
    public var seq: Int64
    public var fileID: String
    public var revision: Int64
    public var path: String
    public var kind: String
    /// nil for a tombstone.
    public var contentHash: String?
    public var size: Int64
    public var deleted: Bool

    public init(seq: Int64, fileID: String, revision: Int64, path: String, kind: String, contentHash: String?,
                size: Int64, deleted: Bool) {
        self.seq = seq
        self.fileID = fileID
        self.revision = revision
        self.path = path
        self.kind = kind
        self.contentHash = contentHash
        self.size = size
        self.deleted = deleted
    }
}

public struct ChangesPage: Sendable, Equatable {
    public var entries: [RemoteEntry]
    public var nextCursor: String
    public var hasMore: Bool

    public init(entries: [RemoteEntry], nextCursor: String, hasMore: Bool) {
        self.entries = entries
        self.nextCursor = nextCursor
        self.hasMore = hasMore
    }
}

public struct SnapshotPage: Sendable, Equatable {
    public var entries: [RemoteEntry]
    /// The same on every page: pull from it once the last page is read (R-P5-003).
    public var cursor: String
    public var nextPage: String?

    public init(entries: [RemoteEntry], cursor: String, nextPage: String?) {
        self.entries = entries
        self.cursor = cursor
        self.nextPage = nextPage
    }
}

/// One operation's result (`PushResult`). For `conflict` the fields describe the conflict
/// copy and `originalFileID` names the file the edit was meant for.
public struct PushOutcome: Sendable, Equatable {
    public enum Status: String, Sendable { case applied, merged, conflict, rejected, duplicate }

    public var status: Status
    public var fileID: String
    public var revision: Int64?
    public var contentHash: String?
    public var path: String?
    public var problemType: String?
    public var problemDetail: String?
    public var originalFileID: String?

    public init(status: Status, fileID: String, revision: Int64? = nil, contentHash: String? = nil,
                path: String? = nil, problemType: String? = nil, problemDetail: String? = nil,
                originalFileID: String? = nil) {
        self.status = status
        self.fileID = fileID
        self.revision = revision
        self.contentHash = contentHash
        self.path = path
        self.problemType = problemType
        self.problemDetail = problemDetail
        self.originalFileID = originalFileID
    }
}

/// A change hint from `GET /events`. Advisory: the engine pulls on each one.
public enum SyncHint: Sendable, Equatable {
    case ready(vaults: [String])
    case change(vaultID: String, seq: Int64)
}
