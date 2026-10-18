// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteEditor",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteEditor", targets: ["OpenNoteEditor"]),
    ],
    dependencies: [
        .package(path: "../OpenNoteCore"),
    ],
    targets: [
        .target(
            name: "OpenNoteEditor",
            dependencies: [
                .product(name: "OpenNoteCore", package: "OpenNoteCore"),
            ]
        ),
        .testTarget(name: "OpenNoteEditorTests", dependencies: ["OpenNoteEditor"]),
    ],
    swiftLanguageModes: [.v6]
)
