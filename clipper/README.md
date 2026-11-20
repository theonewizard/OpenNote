# OpenNote Web Clipper

A Manifest V3 browser extension for Chromium browsers and Firefox (128+) that saves the
current page, or the selection, as a Markdown note in an OpenNote vault (P6-04).

The extension sends the page's HTML to `POST /api/v1/clips`; the server converts it to
Markdown (the same converter as the Evernote import), keeps images as remote links, drops
scripts and forms, and writes `Clippings/<title>.md` with `title`, `source`, `created`
and `tags` frontmatter. There is no build step and no dependency.

## Install (unpacked)

- Chromium: `chrome://extensions`, turn on Developer mode, *Load unpacked*, pick this folder.
- Firefox: `about:debugging#/runtime/this-firefox`, *Load Temporary Add-on*, pick `manifest.json`.

## Set up

1. In OpenNote create a personal access token with **write** scope limited to the vault
   you clip into (`POST /api/v1/tokens`).
2. Open the extension's options, enter the server URL and the token, press *Connect*
   (the browser asks for access to that one server), pick the vault, and save.

The token is kept in the browser's extension storage on this device. Revoke it in
OpenNote to cut the extension off.
