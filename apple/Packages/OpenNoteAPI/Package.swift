// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteAPI",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteAPI", targets: ["OpenNoteAPI"]),
    ],
    dependencies: [
        // The client is generated at build time from Sources/OpenNoteAPI/openapi.json.
        .package(url: "https://github.com/apple/swift-openapi-generator", exact: "1.14.1"),
        .package(url: "https://github.com/apple/swift-openapi-runtime", exact: "1.13.1"),
        // The transport every server call goes through (streamed responses for /events and blobs).
        .package(url: "https://github.com/apple/swift-openapi-urlsession", exact: "1.4.0"),
        // Already in the graph through the runtime; named here because BearerAuth imports it.
        .package(url: "https://github.com/apple/swift-http-types", exact: "1.8.0"),
    ],
    targets: [
        .target(
            name: "OpenNoteAPI",
            dependencies: [
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
                .product(name: "HTTPTypes", package: "swift-http-types"),
            ],
            plugins: [
                .plugin(name: "OpenAPIGenerator", package: "swift-openapi-generator"),
            ]
        ),
        .testTarget(
            name: "OpenNoteAPITests",
            dependencies: [
                "OpenNoteAPI",
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "HTTPTypes", package: "swift-http-types"),
            ]
        ),
    ],
    swiftLanguageModes: [.v6]
)
