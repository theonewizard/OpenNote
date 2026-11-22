import XCTest

/// Smoke tests of the real app on a fresh local vault (no account, no server): P4-05 on the
/// Mac, P4-06 on iPhone, P4-07 on iPad, and quick capture by URL for P4-08.
@MainActor final class SmokeTests: XCTestCase {
    var app: XCUIApplication!

    override func setUp() async throws {
        continueAfterFailure = false
        app = XCUIApplication()
        #if os(macOS)
        // The Mac app opens a folder the user chose and never creates one.
        let folder = FileManager.default.temporaryDirectory.appending(path: "OpenNoteUITest-\(UUID().uuidString)").path
        try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        #else
        let folder = "UITest-\(UUID().uuidString)"
        #endif
        // Launch arguments override the stored defaults: a new vault, and never the server
        // this machine's real app may be signed in to.
        app.launchArguments = ["-vaultFolder", folder, "-serverURL", "", "-vaultID", ""]
        app.launch()
    }

    func testCreateEditFindAndReopenANote() {
        XCTAssertTrue(newNote.waitForExistence(timeout: 15))
        press(newNote)
        let editor = app.textViews.firstMatch
        // CI keeps no artefacts: on failure the log carries what was on screen instead.
        XCTAssertTrue(editor.waitForExistence(timeout: 10), app.debugDescription)
        press(editor)
        editor.typeText("# Groceries\nmilk and eggs")
        // Saved 1.5 s after the last key; leaving the note saves at once.
        showNoteList()
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        press(search)
        search.typeText("eggs")
        XCTAssertTrue(app.staticTexts["Untitled"].waitForExistence(timeout: 10))

        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["Untitled"].waitForExistence(timeout: 15))
        press(app.staticTexts["Untitled"].firstMatch)
        let reopened = app.textViews.firstMatch
        XCTAssertTrue(reopened.waitForExistence(timeout: 10))
        XCTAssertEqual(reopened.value as? String, "# Groceries\nmilk and eggs")
    }

    func testQuickCaptureByURLMakesANoteInTheInbox() {
        XCTAssertTrue(newNote.waitForExistence(timeout: 15))
        app.open(URL(string: "opennote://capture?text=Call%20the%20plumber")!)
        XCTAssertTrue(app.staticTexts["Call the plumber"].waitForExistence(timeout: 15))
    }

    #if os(iOS)
    func testIPadShowsFoldersNotesAndTheNoteSideBySide() throws {
        try XCTSkipUnless(UIDevice.current.userInterfaceIdiom == .pad, "iPad only (P4-07)")
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(newNote.waitForExistence(timeout: 15))
        newNote.tap()
        XCTAssertTrue(app.textViews.firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["All Notes"].firstMatch.isHittable)
        XCTAssertTrue(app.staticTexts["Untitled"].firstMatch.isHittable)
        XCTAssertTrue(app.textViews.firstMatch.isHittable)
    }
    #endif

    private var newNote: XCUIElement { app.buttons["New Note"].firstMatch }

    /// A pointer click on the Mac, where `tap()` is a touch event that buttons ignore.
    private func press(_ element: XCUIElement) {
        #if os(macOS)
        element.click()
        #else
        element.tap()
        #endif
    }

    /// On iPhone the panes are a stack that starts on the note list: leave the note.
    private func showNoteList() {
        #if os(iOS)
        if !newNote.exists { app.navigationBars.buttons.firstMatch.tap() }
        #endif
    }
}
