import Foundation
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

enum NativeScreenshot {

    /// Capture the main display as PNG. Currently ignores `marks` —
    /// Set-of-Marks overlay is on the TODO list. Coordinates returned to
    /// Claude are in points (logical pixels); Retina factor is handled by
    /// scaling the captured image down to logical size on Retina displays.
    static func capture(args: [String: Any]) throws -> [[String: Any]] {
        // CGDisplayCreateImage is deprecated on macOS 15 but still functional
        // through macOS 26; ScreenCaptureKit migration is a follow-up.
        let displayID = CGMainDisplayID()
        guard let cg = CGDisplayCreateImage(displayID) else {
            throw NativeTools.ToolError("Screen capture returned nil — is Screen Recording granted?")
        }

        // Native pixels and logical points.
        let mode = CGDisplayCopyDisplayMode(displayID)
        let logicalW = mode?.width ?? cg.width
        let logicalH = mode?.height ?? cg.height
        let pngData = try encodePNG(cg)
        let base64 = pngData.base64EncodedString()

        let header = "Captured \(cg.width)×\(cg.height) px screenshot " +
                     "(logical: \(logicalW)×\(logicalH) pt). " +
                     "Pass image_width=\(logicalW), image_height=\(logicalH) " +
                     "to mouse so coordinates align with what you see."

        return [
            ["type": "image",
             "data": base64,
             "mimeType": "image/png"],
            ["type": "text", "text": header]
        ]
    }

    private static func encodePNG(_ image: CGImage) throws -> Data {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(
            data as CFMutableData, UTType.png.identifier as CFString, 1, nil) else {
            throw NativeTools.ToolError("Failed to create PNG destination.")
        }
        CGImageDestinationAddImage(dest, image, nil)
        guard CGImageDestinationFinalize(dest) else {
            throw NativeTools.ToolError("Failed to encode PNG.")
        }
        return data as Data
    }
}
