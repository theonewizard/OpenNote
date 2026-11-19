// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteStorage",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteStorage", targets: ["OpenNoteStorage"]),
    ],
    dependencies: [
        .package(path: "../OpenNoteCore"),
    ],
    targets: [
        // The system SQLite: in the SDK on Apple platforms, libsqlite3-dev on Linux.
        .systemLibrary(name: "CSQLite", providers: [.apt(["libsqlite3-dev"])]),
        // renameat2 / renamex_np and F_FULLFSYNC, which Swift's Glibc and Darwin overlays
        // do not all expose.
        .target(name: "CFileSwap"),
        .target(
            name: "OpenNoteStorage",
            dependencies: [
                "CSQLite",
                "CFileSwap",
                .product(name: "OpenNoteCore", package: "OpenNoteCore"),
            ]
        ),
        .testTarget(name: "OpenNoteStorageTests", dependencies: ["OpenNoteStorage"]),
    ],
    swiftLanguageModes: [.v6]
)
