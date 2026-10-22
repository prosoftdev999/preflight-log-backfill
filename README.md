# Preflight Log Backfill

A browser-networking reconstruction project for recovering CORS preflight traffic that is missing from an API gateway access log.

The API edge answers browser `OPTIONS` preflight requests before its normal request logger runs. As a result, the access log contains the actual API calls made during a dispatch-console shift but does not contain the preflights that authorized many of those calls.

The objective is to reconstruct, for every logged API request, whether Chromium sent a CORS preflight immediately beforehand.

## Overview

A cross-origin API request does not always generate an `OPTIONS` request.

Whether a browser preflights a request depends on both the request itself and historical browser state:

```text
API request
    ↓
CORS request classification
    ↓
preflight cache lookup
    ↓
cache hit?
 ┌──┴───┐
 yes    no
 │       │
request  OPTIONS preflight
 │       │
 │       ↓
 │   CORS response
 │       ↓
 │   maybe cache result
 └───────┘
     ↓
actual API request
```

The reconstruction therefore requires replaying browser preflight-cache state across the shift rather than classifying requests independently.

## Repository Structure

```text
preflight-log-backfill/
├── environment/
├── solution/
├── tests/
├── instruction.md
└── task.toml
```

### `instruction.md`

Defines the reconstruction objective and required output.

### `environment/`

Contains the reproducible runtime and captured API/browser evidence.

### `solution/`

Contains the reference reconstruction implementation.

### `tests/`

Contains the independent verifier.

### `task.toml`

Contains task metadata and runtime configuration.

## Input Evidence

The task data is stored under:

```text
/app/data
```

The primary API request log is:

```text
/app/data/api_access.jsonl
```

Additional files describe the console activity, browser environment, edge configuration, and upstream CORS behavior.

The accompanying data README documents the capture and browser assumptions.

## CORS Preflights

Browsers use a CORS preflight when a cross-origin request is not considered sufficiently simple to send directly.

Conceptually, requests may need a preflight because of:

- HTTP method
- request headers
- `Content-Type`
- credentials
- previously cached CORS permissions

A request such as:

```http
GET /status
```

may be sent without a preflight.

A request carrying headers such as:

```text
Authorization
X-Desk-Trace
Idempotency-Key
```

may require one.

The exact result still depends on the browser's current preflight-cache state.

## Preflight Cache

A successful preflight can authorize later requests without another `OPTIONS` exchange.

A cache entry can carry information about:

```text
URL
allowed methods
allowed headers
credential state
expiry
```

A later request can reuse the entry only when the relevant conditions are satisfied.

Therefore:

```text
same URL
```

does not automatically mean:

```text
same preflight result
```

## Cache Expiry

CORS responses can provide:

```http
Access-Control-Max-Age
```

which controls how long the preflight result remains reusable.

The reconstruction must account for the effective response seen by Chromium at the historical point in the shift.

Expired entries cause the browser to preflight again.

## Gateway Configuration History

The configuration visible at the end of the shift is not necessarily the configuration that was active for the entire capture.

The edge was redeployed during the shift.

That means reconstruction must distinguish:

```text
before deployment
```

from:

```text
after deployment
```

when reproducing the CORS headers returned to the browser.

Historical response evidence is used to locate that transition.

## Multiple Max-Age Values

One route can produce more than one `Access-Control-Max-Age` field after the edge and upstream service responses are combined.

The resulting value must be interpreted the way the recorded Chromium version interpreted it.

This can lead to substantially different cache lifetime behavior from simply choosing one of the individual max-age values.

## Top-Level-Site Partitioning

The preflight cache is partitioned by browser network context.

The same console application can therefore have separate cache state when it runs:

```text
directly in the FleetDesk site
```

versus:

```text
inside an embedded partner portal
```

The top-level site associated with the request must be reconstructed before the correct cache can be selected.

## Browser Profiles

Each workstation can have more than one browser profile.

Different profiles do not share the same in-memory preflight cache.

Conceptually:

```text
workstation-12
├── main profile
│   └── preflight cache
└── guest profile
    └── separate preflight cache
```

Merging both profiles into one cache produces incorrect historical behavior.

## Tabs

Tabs inside the same browser profile can share the profile's preflight cache.

Therefore, creating one cache per page load or per tab is also incorrect.

The relevant lifetime is tied to the browser/profile run rather than to a single document.

## Browser Restarts

The main browser may restart during the shift.

Persistent browser state such as cookies or tokens can survive the restart while the in-memory preflight cache does not.

Conceptually:

```text
browser run 1
    ↓
cache populated
    ↓
browser exits
    ↓
cache lost
    ↓
browser run 2
    ↓
same persistent profile
    ↓
new empty preflight cache
```

This makes restart detection essential.

## Cache Bypass

Some requests are issued with fetch/cache behavior that bypasses normal preflight-cache reuse.

Such requests can:

- skip cache lookup
- cause a new preflight
- avoid storing the resulting authorization for later reuse

This behavior must be distinguished from ordinary cache-default requests.

## URL Length

Very long request URLs are treated differently by Chromium's preflight caching behavior in this capture.

Those requests can still preflight, but their result may not become a reusable cache entry.

This prevents later requests from receiving an apparent cache hit that Chromium would not actually have used.

## Reflected Allowed Headers

One API route reflects the browser's requested header set in its CORS response.

This means different request shapes to the same URL can replace the useful cache authorization for one another.

For example:

```text
read request
    ↓
allowed headers set A

assignment request
    ↓
allowed headers set B
```

A cache model that assumes one fixed header allowlist for the route will therefore diverge from the actual browser behavior.

## Historical Replay

The task is best understood as a browser-state replay problem.

```text
access log
   +
console page-load history
   +
CORS configuration
   +
response evidence
        ↓
identify browser/profile/run
        ↓
identify top-level site
        ↓
classify request
        ↓
replay preflight cache
        ↓
determine OPTIONS/no OPTIONS
        ↓
advance cache state
        ↓
next request
```

Every request can change the state used to classify later requests.

## Output

The solver writes:

```text
/app/output/preflights.json
```

with this structure:

```json
{
  "preflighted": {
    "q00001": false,
    "q00002": true,
    "q00003": false
  }
}
```

Every request ID from:

```text
/app/data/api_access.jsonl
```

must appear under `preflighted`.

Each value is a JSON boolean:

```text
true
```

when the browser sent a corresponding CORS preflight, and:

```text
false
```

when it did not.

No approximation or aggregate count is sufficient; the decision is reconstructed independently for every request.

## Scale

The captured shift contains tens of thousands of API calls across multiple workstations.

The browser activity also includes:

- multiple tabs
- separate browser profiles
- browser restarts
- embedded partner contexts
- route-specific CORS behavior
- changing gateway configuration

This makes the task a historical state-reconstruction problem rather than a simple HTTP-header classifier.

## Common Failure Modes

### Treating every unsafe request as a new preflight

Valid cached authorization can suppress later `OPTIONS` requests.

### Using one cache per workstation

Different browser profiles require separate cache state.

### Using one cache per tab

Tabs in the same profile can share cache state.

### Ignoring browser restarts

A restart clears the in-memory preflight cache.

### Ignoring top-level-site partitioning

Embedded portal requests can belong to a different cache partition.

### Applying the final gateway configuration to the whole shift

The configuration changed during the capture.

### Treating allowed headers as static

Some routes reflect the request's actual header set.

### Ignoring cache-bypass requests

No-store behavior can change both lookup and storage.

### Caching every successful preflight

Certain long-URL cases are not reusable.

## Technical Areas

This project exercises:

- CORS
- HTTP
- browser networking
- Chromium behavior
- preflight caching
- API gateways
- request headers
- browser profiles
- network partitioning
- historical configuration
- event replay
- state reconstruction
- access-log analysis
- frontend infrastructure
- capacity planning
- Python

## Goal

Preflight Log Backfill reconstructs network traffic that was handled successfully by the edge but omitted from the normal access log.

The central principle is:

> Whether a browser sends a preflight is a stateful historical decision, not just a property of the current HTTP request.

## License

No license is currently specified.
