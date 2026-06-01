# lifi-bundler

Bundles `@lifi/widget` + React + ReactDOM into a single ESM file at
`/static/js/vendor/lifi-widget.bundle.js`.

## Why

`esm.sh` serves `@lifi/widget@3` as a waterfall of ~1,200 separate ES
modules totaling ~4.5 MB uncompressed.  Even with HTTP/2 multiplexing
the Buy Crypto pane takes 20–30s+ to first paint on slower connections,
and a single dropped chunk silently breaks the widget mid-load — the
exact failure mode users were reporting as "sobrang bagal mag-load" and
"failed bridging/swapping".

The vendored bundle reduces that to **one HTTP request** (~2 MB gzip)
that browsers can cache forever via `?v={{ ASSET_VERSION }}`.

## When to rebuild

Whenever you bump `@lifi/widget` in `package.json` (or the React peer
deps).  The output is checked into git so production deploys do not
have to run a JS build step.

## Rebuild

```bash
cd tools/lifi-bundler
npm install
npm run build
```

This writes `static/js/vendor/lifi-widget.bundle.js`.  Commit that file
together with the updated `package.json` / `package-lock.json`.
