Our API edge answers CORS preflights in its filter before the access log is written, so the log of one FleetDesk console shift holds every API request the dispatchers' browsers made except the OPTIONS requests, and capacity planning needs those back. The logs and the edge's CORS configuration are in `/app/data`, and `/app/data/README.md` describes the files and the browsers.

For every request in `/app/data/api_access.jsonl`, work out whether the browser sent a CORS preflight for it, that is, an OPTIONS request made for that request just before it was sent. Write `/app/output/preflights.json`, a regular file of at most 64 MiB holding a JSON object whose `preflighted` key maps each request's `rid` to `true` when a preflight was sent for it and `false` when none was:

```json
{"preflighted": {"q00001": false, "q00002": true, "q00003": true}}
```

The values in that example are made up. Every `rid` in the log must appear under `preflighted`, and each value must be a JSON boolean. Other keys, at either level, are ignored, and so are key order and formatting. Your file is compared with the edge's own record of the OPTIONS requests it answered during the shift, and every value must match it.

You have 9000 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
