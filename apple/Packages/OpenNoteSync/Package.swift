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
        // Already in the graph through OpenNoteAPI; named here because the engine imports them.
        .package(url: "https://github.com/apple/swift-openapi-runtime", exact: "1.13.1"),
        .package(url: "https://github.com/apple/swift-http-types", exact: "1.8.0"),
    ],
    targets: [
        .target(
            name: "OpenNoteSync",
            dependencies: [
                .product(name: "OpenNoteCore", package: "OpenNoteCore"),
                .product(name: "OpenNoteStorage", package: "OpenNoteStorage"),
                .product(name: "OpenNoteAPI", package: "OpenNoteAPI"),
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "HTTPTypes", package: "swift-http-types"),
            ]
        ),
        .testTarget(
            name: "OpenNoteSyncTests",
            dependencies: [
                "OpenNoteSync",
                .product(name: "OpenNoteCore", package: "OpenNoteCore"),
                .product(name: "OpenNoteStorage", package: "OpenNoteStorage"),
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "HTTPTypes", package: "swift-http-types"),
            ]
        ),
    ],
    swiftLanguageModes: [.v6]
)
