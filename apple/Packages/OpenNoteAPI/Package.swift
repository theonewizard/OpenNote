// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteAPI",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteAPI", targets: ["OpenNoteAPI"]),
    ],
    targets: [
        .target(name: "OpenNoteAPI"),
        .testTarget(name: "OpenNoteAPITests", dependencies: ["OpenNoteAPI"]),
    ],
    swiftLanguageModes: [.v6]
)
