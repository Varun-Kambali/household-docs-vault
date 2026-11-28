# 0022. The app draws the page itself: server-rendered PNGs and the line outline
Date: 2026-11-28 · Status: accepted

## Context
An answer is only worth trusting when I can see where it came from, so the app has to show the page with the supporting line outlined. The web app's security policy is `default-src 'self'`, and the filed documents are PDFs, JPEGs, PNGs and HEIC photos. A browser's built-in PDF viewer would need the policy loosened, would not draw my outline, and cannot show a HEIC photo at all.

## Decision
**The server draws every page.** `GET /v1/documents/{id}/pages/{n}.png` renders a page of a filed document, and a matching route renders a page of an item still in the Inbox, at a width between 320 and 2000 px. A PDF page is rendered, a photo is opened, turned upright by its EXIF orientation and scaled. The browser gets a PNG, so the page needs no PDF viewer, no plugin and no extra rule in the policy. The line boxes come from `GET .../pages/{n}/lines`, and the web app draws the outline over the image.

**Card photos never get this far.** Every page route asks the card gate first (`is_card_photo`, [ADR 0014](0014-secrets-in-the-filing-pipeline.md)). A card is drawn from its masked copy, the raw photo is refused, and so is any item that shares its bytes.

**Headers.** The page and lines routes send `Cache-Control: no-store`, so a full Aadhaar or PAN page does not land in the browser's disk cache (the range review found `max-age=300` and I changed it before the phone reaches these routes in M4). The raw file route, which serves the filed original for Download, carries `Content-Security-Policy: sandbox; default-src 'none'`, `X-Content-Type-Options: nosniff` and `Content-Disposition: inline`, so an original opened in a tab can run nothing.

**EXIF orientation.** A phone photo stored sideways with an orientation tag used to be read by OCR and the vision model as it was stored, and shown the same way. `open_image` now turns it upright before reading, the viewer draws the same upright frame, and a photo that needs no turn goes to the models unchanged, so the recorded M2 readings stay valid. M2's reading eval, replayed on the validation recordings after the change, was unchanged. A HEIC photo goes through `sips` first and is turned the same way.

**Carry item closed.** The M2 carry list had "a PDF viewer under the app's CSP". This closes it: there is no PDF viewer.

## Alternatives considered
- **The browser's PDF viewer in an iframe.** Needs the policy loosened, draws no outline, and fails on photos.
- **pdf.js in the web app.** A large dependency to ship and secure, and the server must still render the photos.
- **Render once and keep PNGs on disk.** A second copy of every page, including ID pages, that I would then have to protect and clear.

## Consequences
A page takes a moment to draw the first time, and every page load is a request. That is fine on one Mac, and a cache would need the same protection as the files.
