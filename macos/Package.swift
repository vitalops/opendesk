// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "OpenDesk",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "OpenDesk", targets: ["OpenDesk"])
    ],
    targets: [
        .executableTarget(
            name: "OpenDesk",
            path: "Sources/OpenDesk",
            exclude: [],
            resources: [
                .copy("Resources/bridge")
            ]
        )
    ]
)
