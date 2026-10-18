// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteSync",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteSync", targets: ["OpenNoteSync"]),
    ],
    dependencies: [
        .package(path: "../OpenNoteCore"),
        .package(path: "../OpenNoteStorage"),
        .package(path: "../OpenNoteAPI"),
    ],
    targets: [
        .target(
            name: "OpenNoteSync",
            dependencies: [
                .product(name: "OpenNoteCore", package: "OpenNoteCore"),
                .product(name: "OpenNoteStorage", package: "OpenNoteStorage"),
                .product(name: "OpenNoteAPI", package: "OpenNoteAPI"),
            ]
        ),
        .testTarget(name: "OpenNoteSyncTests", dependencies: ["OpenNoteSync"]),
    ],
    swiftLanguageModes: [.v6]
)
