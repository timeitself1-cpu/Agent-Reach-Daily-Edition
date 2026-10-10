# Static reading verification

Checked against the October 8, 2026 publication, revision 8, using Node 24 and a local production build served over HTTP.

- 55 Node tests passed, including raw HTML checks for every headline, complete summary, optional context, source link and unique story anchor. Existing embedded-data, navigation, sharing, search and accessibility tests passed.
- Publication validation and `npm run build` passed. Existing publication warnings about duplicate outlets and Google News redirects remain warnings.
- Headless Chrome: Home, dated Daily, Latest, Technology, World and Archive at 320, 390, 768 and 1440 pixels, with JavaScript enabled, disabled and all `/assets/*.js` requests blocked (72 combinations). No horizontal overflow or uncaught script errors. Complete reading routes exposed every expected article; static summaries were not clipped, and source disclosures opened with all evidence entries visible.
- Desktop and mobile screenshots reviewed. Edition history is tucked into a native disclosure, source lists have separated rows and readable UTC timestamps, and fragment targets have a visible outline.

To reproduce the static checks, run `npm ci`, `npm test`, then `npm run build`. Serve `dist`, disable JavaScript in the browser, and open the routes above. Test a dated `#story-<id>` link for a story near the end of an edition, open its source disclosure, and expand the edition details. Repeat with script requests blocked to verify that fallback styling does not depend on `<noscript>`.

Search requires JavaScript and links to the archive in its fallback. This verification covers local build output; it does not claim a production deployment.
