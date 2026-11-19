// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteCore",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteCore", targets: ["OpenNoteCore"]),
    ],
    dependencies: [
        // SHA-256 on Linux, where CryptoKit does not exist (Apple platforms use CryptoKit).
        .package(url: "https://github.com/apple/swift-crypto.git", exact: "5.0.1"),
        // Frontmatter YAML (libyaml); scalars are resolved in Frontmatter.swift as ruamel does.
        .package(url: "https://github.com/jpsim/Yams", exact: "6.2.2"),
        // CommonMark block structure for masking code and HTML blocks, as markdown-it does.
        .package(url: "https://github.com/swiftlang/swift-cmark.git", exact: "0.9.0"),
    ],
    targets: [
        .target(
            name: "OpenNoteCore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto", condition: .when(platforms: [.linux])),
                .product(name: "Yams", package: "Yams"),
                .product(name: "cmark-gfm", package: "swift-cmark"),
            ]
        ),
        .testTarget(name: "OpenNoteCoreTests", dependencies: ["OpenNoteCore"]),
    ],
    swiftLanguageModes: [.v6]
)
