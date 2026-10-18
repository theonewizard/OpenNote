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
    ],
    targets: [
        .target(
            name: "OpenNoteCore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto", condition: .when(platforms: [.linux])),
            ]
        ),
        .testTarget(name: "OpenNoteCoreTests", dependencies: ["OpenNoteCore"]),
    ],
    swiftLanguageModes: [.v6]
)
