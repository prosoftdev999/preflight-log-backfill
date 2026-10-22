These files cover the FleetDesk morning shift of 14 September 2026, which started at 08:30 UTC. All hosts, addresses, tokens and cookies are from a test setup.

`api_access.jsonl` has one line per request the API edge on `http://api.fleetdesk.test` passed to its upstreams, in arrival order: `ts` (arrival time, UTC, milliseconds), `rid`, `client` (the workstation's address), `method`, `url` (path and query), `status`, `request_headers` (every field as received, in order) and `response_headers`. It holds no OPTIONS requests.

`console_access.jsonl` lists every document request served by `http://console.fleetdesk.test`, with `ts`, `client`, `method`, `path`, `status`, `referer` and `user_agent`. `/desk/` pages are opened as top-level tabs, which dispatchers never reloaded or navigated and which closed only together with their browser; `/embed/` pages are only loaded in iframes placed directly in the top-level pages of partner companies' sites, whose logs we lack. Every console page URL carries a `pv` number unique to that page load. Console pages use the referrer policy `no-referrer-when-downgrade`.

`gateway/edge.yaml` and `gateway/reports-svc.cors.json` are the edge's and the reports service's CORS configuration as they stood at the end of the shift.

Both logs were written by hosts whose clocks agreed and were not adjusted during the shift.

Each workstation ran headless Chromium 153.0.8010.12 under Playwright 1.63.0; that build is installed here. Workstations share nothing. The console signs in (`POST /v1/session`, whose response sets the `fd_sid` cookie) only when it has no `fd_sid` cookie. It makes every API call with `fetch()` in `cors` mode and sets no request headers other than `Authorization`, `Content-Type`, `Idempotency-Key` and `X-Desk-Trace`. It uses `credentials` `omit` or `include`, and only `/desk/` pages ever use `include`. It uses `cache` `default` or `no-store`, and each call site in the console's code always passes the same fetch options. `include` requests carry the `fd_sid` cookie, except the sign-in; `omit` requests never do. No request was redirected or failed, and nothing else in those browsers talked to the API.

Playwright never intercepted or answered requests, nothing changed a browser's cache settings, and every OPTIONS request went over the network to the edge.
