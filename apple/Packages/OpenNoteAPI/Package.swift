// swift-tools-version: 6.4
import PackageDescription

let package = Package(
    name: "OpenNoteAPI",
    platforms: [.macOS(.v15), .iOS(.v18)],
    products: [
        .library(name: "OpenNoteAPI", targets: ["OpenNoteAPI"]),
    ],
    dependencies: [
        // The client is generated at build time from Sources/OpenNoteAPI/openapi.yaml.
        .package(url: "https://github.com/apple/swift-openapi-generator", exact: "1.14.1"),
        .package(url: "https://github.com/apple/swift-openapi-runtime", exact: "1.13.1"),
        .package(url: "https://github.com/apple/swift-openapi-urlsession", exact: "1.3.2"),
    ],
    targets: [
        .target(
            name: "OpenNoteAPI",
            dependencies: [
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
            ],
            plugins: [
                .plugin(name: "OpenAPIGenerator", package: "swift-openapi-generator"),
            ]
        ),
        .testTarget(name: "OpenNoteAPITests", dependencies: ["OpenNoteAPI"]),
    ],
    swiftLanguageModes: [.v6]
)
