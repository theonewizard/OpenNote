#if os(iOS)
import XCTest

/// Login and first sync against a running OpenNote server (P4-03 acceptance). Skipped unless
/// the server is named, because every other test runs offline:
///
///     TEST_RUNNER_OPENNOTE_LIVE_SERVER=http://localhost:5173 TEST_RUNNER_OPENNOTE_LIVE_USER=alice \
///     TEST_RUNNER_OPENNOTE_LIVE_PASSWORD=… TEST_RUNNER_OPENNOTE_LIVE_VAULT=Test \
///       xcodebuild test … -only-testing:OpenNoteUITests-iOS/LiveServerTests
///
/// The user must have a vault of that name holding a note called "Hello from the server".
@MainActor final class LiveServerTests: XCTestCase {
    func testSignInOpenAVaultAndSyncBothWays() throws {
        let env = ProcessInfo.processInfo.environment
        guard let server = env["OPENNOTE_LIVE_SERVER"], let user = env["OPENNOTE_LIVE_USER"],
              let password = env["OPENNOTE_LIVE_PASSWORD"], let vault = env["OPENNOTE_LIVE_VAULT"] else {
            throw XCTSkip("needs a running server (see the comment above)")
        }
        continueAfterFailure = false
        let app = XCUIApplication()
        // Empty values override what an earlier run stored: start signed out, with no vault.
        app.launchArguments = ["-vaultFolder", "", "-serverURL", "", "-vaultID", ""]
        app.launch()

        let address = app.textFields.firstMatch
        XCTAssertTrue(address.waitForExistence(timeout: 15))
        address.tap()
        address.typeText(server)
        app.buttons["Sign In"].tap()

        // iOS asks before an app opens a sign-in page.
        let consent = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Continue"]
        if consent.waitForExistence(timeout: 10) { consent.tap() }

        // The server's own login page, in the web authentication session.
        let page = app.webViews.firstMatch
        let name = page.textFields.firstMatch
        XCTAssertTrue(name.waitForExistence(timeout: 30))
        name.tap()
        name.typeText(user)
        let secret = page.secureTextFields.firstMatch
        secret.tap()
        secret.typeText(password + "\n")  // Return submits; the keyboard covers the button
        // Safari offers to keep the password before it lets the page go on.
        let notNow = app.buttons["Not Now"]
        if notNow.waitForExistence(timeout: 10) { notNow.tap() }

        // Back in the app, signed in: the server's vaults are listed.
        let choice = app.buttons[vault]
        XCTAssertTrue(choice.waitForExistence(timeout: 30))
        choice.tap()

        // Pulled from the server.
        XCTAssertTrue(app.staticTexts["Hello from the server"].waitForExistence(timeout: 60))

        // Pushed to the server: the caller checks it there (`GET /api/v1/notes`).
        app.buttons["New Note"].firstMatch.tap()
        let editor = app.textViews.firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap()
        editor.typeText("written on the phone")
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Untitled"].waitForExistence(timeout: 10))
        sleep(8)  // the engine pushes 2 s after a local change
    }
}
#endif
