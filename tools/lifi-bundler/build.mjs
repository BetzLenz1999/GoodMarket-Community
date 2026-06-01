// Self-host the LI.FI / Jumper widget as a single minified ESM bundle.
//
// Why: esm.sh serves @lifi/widget@3 as ~1,200 separate ES modules
// totaling ~4.5MB.  Even with HTTP/2 multiplexing, the resulting
// waterfall is multi-second on broadband and 30s+ on mobile, and a
// single dropped chunk silently breaks the widget mid-load — which is
// what users were reporting as "sobrang bagal mag-load" and "failed
// bridging/swapping".  This script produces ONE file that we serve out
// of /static/js/vendor/, eliminating the waterfall.
//
// Run with `npm run build` from this directory.
import { build } from "esbuild";
import { dirname, join } from "node:path";
import { mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "..", "static", "js", "vendor");
mkdirSync(outDir, { recursive: true });

const pkg = JSON.parse(
    readFileSync(join(__dirname, "node_modules", "@lifi", "widget", "package.json"), "utf8"),
);

const result = await build({
    entryPoints: [join(__dirname, "entry.js")],
    bundle: true,
    format: "esm",
    target: "es2022",
    platform: "browser",
    outfile: join(outDir, "lifi-widget.bundle.js"),
    minify: true,
    sourcemap: false,
    // No externals: bundle React, ReactDOM, MUI, viem, wagmi, and the
    // entire LI.FI dependency graph into one file so we can load the
    // widget with a single HTTP request.
    external: [],
    define: {
        "process.env.NODE_ENV": "\"production\"",
        "process.env.NEXT_PUBLIC_LIFI_WIDGET_VERSION": JSON.stringify(pkg.version),
    },
    legalComments: "none",
    treeShaking: true,
    metafile: true,
    logLevel: "info",
});

const total = Object.values(result.metafile.outputs).reduce((acc, o) => acc + o.bytes, 0);
console.log(
    `\nBuilt @lifi/widget@${pkg.version} → static/js/vendor/lifi-widget.bundle.js ` +
    `(${(total / 1024).toFixed(0)} KB)`,
);
