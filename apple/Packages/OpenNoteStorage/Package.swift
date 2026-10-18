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
        .target(
            name: "OpenNoteStorage",
            dependencies: [
                .product(name: "OpenNoteCore", package: "OpenNoteCore"),
            ]
        ),
        .testTarget(name: "OpenNoteStorageTests", dependencies: ["OpenNoteStorage"]),
    ],
    swiftLanguageModes: [.v6]
)
