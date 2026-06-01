/**
 * GoodMarket — LI.FI / Jumper widget mount
 * ---------------------------------------------------------------------------
 * Renders the @lifi/widget React component into #lifiWidgetRoot on the
 * /swap "Buy Crypto" tab.  LI.FI's widget handles its own wallet connection
 * (injected EIP-1193 wallets + WalletConnect via wagmi), so users can
 * connect from inside the widget regardless of how they signed in to
 * GoodMarket itself.  The widget supports cross-chain swaps between many
 * chains; defaults target Celo → native ETH on Base but the user can
 * change source/destination from inside the widget UI.
 *
 * The widget is loaded from a single locally-vendored ESM bundle at
 * /static/js/vendor/lifi-widget.bundle.js (see tools/lifi-bundler/) so
 * the user only ever waits on ONE HTTP request to get the entire widget
 * runtime instead of waterfalling ~1,200 separate ES modules through
 * esm.sh, which previously caused multi-second cold loads + mid-load
 * failures bubbling up as "failed bridging/swapping".
 *
 * Exposes window.GMLifiReactWidget = { refresh() } so the host page can
 * re-render the widget after layout changes (e.g. tab switching).
 */
// IMPORTANT: We deliberately load LI.FI / Jumper from a single locally-
// vendored ESM bundle instead of esm.sh.  esm.sh waterfalls @lifi/widget
// into ~1,200 separate module requests (~4.5MB uncompressed) which made
// the Buy Crypto pane take 20-30s+ to load on slower connections AND
// caused mid-load failures that bubbled up to users as "bridging/
// swapping failed".  The vendored bundle ships React + ReactDOM + the
// widget in one file, so the browser only makes ONE HTTP request to get
// the entire widget runtime.  Build it with `npm --prefix
// tools/lifi-bundler run build` whenever the widget version is bumped.
import { LiFiWidget, React, ReactDOM } from "/static/js/vendor/lifi-widget.bundle.js";
const { useMemo, useState, useEffect } = React;
const { createRoot } = ReactDOM;

// Minimum bridge amount LI.FI's underlying providers typically accept.
// Below this, the API either returns no routes or returns ones whose fees
// exceed the output, and wallets reject the tx as "will likely fail".
// $1 covers Allbridge, Glacis, Eco, Across, Stargate minimums.
const MIN_BRIDGE_USD = 1;
// Recommended on-chain gas reserve for Celo bridge txs.  Even with low
// 0.001–0.005 CELO base fees, two sequential txs (approve + bridge) plus
// L1 calldata can spike to ~0.03 CELO during congestion.
const CELO_GAS_RESERVE_WEI = 50000000000000000n;  // 0.05 CELO
// Same for Base ETH — a destination swap typically costs $0.10–$0.30 in ETH,
// so any nonzero balance ≥ 0.0002 ETH (~$0.50) is comfortable.
const BASE_ETH_GAS_RESERVE_WEI = 200000000000000n;  // 0.0002 ETH

// LI.FI uses the zero address as the native-token sentinel on every
// supported EVM chain EXCEPT Celo, where the native CELO is itself an
// ERC-20 deployed at 0x471EcE...A438.  Using the zero address there
// trips LI.FI's API into returning `Token 42220-0x0000… is invalid or
// in deny list.` which kills the first gas/quote call and breaks the
// widget on load — the failure mode users reported as "failed
// bridging/swapping".  We pick per-chain defaults so the widget always
// boots with a valid sentinel even when the bootstrap config is
// missing or older.
const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000";
const CELO_CHAIN_ID = 42220;
const CELO_NATIVE_TOKEN = "0x471EcE3750Da237f93B8E339c536989b8978a438";
function nativeTokenForChain(chainId) {
    return Number(chainId) === CELO_CHAIN_ID ? CELO_NATIVE_TOKEN : ZERO_ADDRESS;
}
const DEFAULT_STABILITY = Object.freeze({
    routePriority: "FASTEST",
    // Bumped from 0.01 (1%) — Celo bridges (Allbridge, Glacis, Eco) move
    // price 1–1.5% between quote and execution, which used to trip wallet
    // simulators with "Transaction will likely fail" / "unknown RPC error"
    // right at signing.
    slippage: 0.02,
    useRecommendedRoute: true,
    // LI.FI's default `RouteOptions.allowSwitchChain` is false, which hides
    // every Celo→Base bridge whose dest is a stable still needing an
    // on-Base swap (Allbridge, Glacis, Eco, Across via USDC …).  Without
    // those, the widget falls back to fragile single-tx routes that wallets
    // routinely reject.  Enable explicitly.
    allowSwitchChain: true,
    allowDestinationCall: true,
    // Permit2 (`callDiamondWithPermit2` at 0x89c6340B…) is LI.FI's default
    // signing path, but on Celo the native asset IS the CELO ERC-20 at
    // 0x471EcE…A438 — so the same token is moved twice on a single tx
    // (msg.value + Permit2 pull) and the wallet's pre-flight simulator
    // reverts.  Disabling message signing forces a standard `approve()`
    // flow that wallets simulate cleanly.
    disableMessageSigning: true,
});

function readBootstrap() {
    const node = document.getElementById("lifiWidgetBootstrap");
    if (!node) return {};
    try { return JSON.parse(node.textContent || "{}"); }
    catch (err) {
        console.error("[GoodMarket LI.FI] Invalid widget bootstrap JSON", err);
        return {};
    }
}

function isPresentWallet(address) {
    return Boolean(address && address !== "None" && /^0x[0-9a-fA-F]{40}$/.test(address));
}

function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#39;",
    }[ch]));
}

function renderFallbackMessage(message) {
    const rootEl = document.getElementById("lifiWidgetRoot");
    if (!rootEl) return;
    rootEl.innerHTML = "";
    const box = document.createElement("div");
    box.className = "lifi-react-status lifi-react-status--stack";
    box.setAttribute("data-connected", "false");
    box.style.marginBottom = "0.75rem";
    box.innerHTML = `
        <strong>⚠️ Buy Crypto widget unavailable</strong>
        <span>${escapeHtml(message)}</span>
        <button type="button" class="lifi-retry-btn" id="lifiRetryMountBtn">Reload LI.FI widget</button>`;
    rootEl.appendChild(box);
    const retry = document.getElementById("lifiRetryMountBtn");
    if (retry) retry.addEventListener("click", () => mount(true));
}

class WidgetErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false };
    }
    static getDerivedStateFromError() {
        return { hasError: true };
    }
    componentDidCatch(error) {
        console.error("[GoodMarket LI.FI] React widget render failed", error);
    }
    render() {
        if (this.state.hasError) {
            return React.createElement("div", { className: "lifi-react-status", "data-connected": "false" },
                React.createElement("strong", null, "⚠️ Buy Crypto widget failed to render"),
                React.createElement("span", null, "Please refresh the page. If this continues, reconnect your wallet and try again.")
            );
        }
        return this.props.children;
    }
}

function clampSlippage(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_STABILITY.slippage;
    return Math.min(Math.max(parsed, 0.001), 0.03);
}

function normalizeRoutePriority(value) {
    const normalized = String(value || DEFAULT_STABILITY.routePriority).toUpperCase();
    return normalized === "CHEAPEST" ? "CHEAPEST" : "FASTEST";
}

function normalizeBoolean(value, fallback) {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
        if (["1", "true", "yes", "on"].includes(value.toLowerCase())) return true;
        if (["0", "false", "no", "off"].includes(value.toLowerCase())) return false;
    }
    return fallback;
}

function readRpcUrls(bootstrap) {
    const rpcUrls = bootstrap.rpcUrls && typeof bootstrap.rpcUrls === "object" ? bootstrap.rpcUrls : {};
    return Object.entries(rpcUrls).reduce((acc, [chainId, urls]) => {
        const cleaned = Array.isArray(urls)
            ? urls.map((url) => String(url || "").trim()).filter(Boolean)
            : [String(urls || "").trim()].filter(Boolean);
        if (cleaned.length) acc[Number(chainId)] = cleaned;
        return acc;
    }, {});
}

function firstRpcUrl(rpcUrls, chainId, fallback) {
    const entry = rpcUrls && rpcUrls[chainId];
    if (Array.isArray(entry) && entry.length && entry[0]) return entry[0];
    return fallback;
}

async function fetchNativeBalance(rpcUrl, address) {
    if (!rpcUrl || !address) return null;
    try {
        const res = await fetch(rpcUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                id: 1,
                method: "eth_getBalance",
                params: [address, "latest"],
            }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error.message || "RPC error");
        const hex = String(data.result || "0x0");
        if (!/^0x[0-9a-fA-F]*$/.test(hex)) throw new Error(`bad balance hex: ${hex}`);
        return BigInt(hex);
    } catch (err) {
        console.warn("[GoodMarket LI.FI] balance fetch failed for", rpcUrl, err);
        return null;
    }
}

function formatNativeBalance(wei, symbol, decimalsToShow = 4) {
    if (wei === null || wei === undefined) return null;
    const s = wei.toString().padStart(19, "0");
    const whole = s.slice(0, -18) || "0";
    const frac = s.slice(-18).slice(0, decimalsToShow);
    return `${whole}.${frac} ${symbol}`;
}

function makeConfig(bootstrap) {
    const integrator = bootstrap.integrator || "goodmarket-community";
    const fromChain = Number(bootstrap.fromChainId || 42220);
    const toChain = Number(bootstrap.toChainId || 8453);
    const fromToken = bootstrap.fromToken || nativeTokenForChain(fromChain);
    const toToken = bootstrap.toToken || nativeTokenForChain(toChain);
    const routePriority = normalizeRoutePriority(bootstrap.routePriority);
    const slippage = clampSlippage(bootstrap.slippage);
    const useRecommendedRoute = normalizeBoolean(bootstrap.useRecommendedRoute, DEFAULT_STABILITY.useRecommendedRoute);
    const allowSwitchChain = normalizeBoolean(bootstrap.allowSwitchChain, DEFAULT_STABILITY.allowSwitchChain);
    const allowDestinationCall = normalizeBoolean(bootstrap.allowDestinationCall, DEFAULT_STABILITY.allowDestinationCall);
    const disableMessageSigning = normalizeBoolean(bootstrap.disableMessageSigning, DEFAULT_STABILITY.disableMessageSigning);
    const rpcUrls = readRpcUrls(bootstrap);
    const walletConnectProjectId = typeof bootstrap.walletConnectProjectId === "string"
        ? bootstrap.walletConnectProjectId.trim()
        : "";

    const config = {
        integrator,
        variant: "compact",
        appearance: "dark",
        fromChain,
        toChain,
        fromToken,
        toToken,
        routePriority,
        slippage,
        useRecommendedRoute,
        buildUrl: true,
        // Unlocks multi-step Celo→Base routes whose 2nd step needs an
        // on-destination swap (Allbridge/Glacis/Eco …).  Without these,
        // LI.FI filters those bridges out and only fragile single-tx
        // routes are offered — the routes wallets reject as
        // "Transaction will likely fail (execution reverted)".
        routeOptions: {
            allowSwitchChain,
            allowDestinationCall,
        },
        // Bypass Permit2 signing so native CELO transfers don't reach the
        // `callDiamondWithPermit2` proxy at 0x89c6340B... which reverts in
        // wallet simulators because CELO's native + ERC-20 duality means
        // the same token is moved twice in one tx.
        executionOptions: {
            disableMessageSigning,
        },
        theme: {
            palette: {
                primary: { main: "#7c3aed" },
                secondary: { main: "#38bdf8" },
            },
            shape: {
                borderRadius: 14,
                borderRadiusSecondary: 10,
            },
            container: {
                boxShadow: "none",
                borderRadius: "16px",
            },
        },
    };

    const sdkConfig = {};
    if (bootstrap.apiUrl) sdkConfig.apiUrl = bootstrap.apiUrl;
    if (Object.keys(rpcUrls).length) sdkConfig.rpcUrls = rpcUrls;
    if (Object.keys(sdkConfig).length) config.sdkConfig = sdkConfig;

    // Forward our own WalletConnect projectId so LI.FI's internal wagmi WC
    // connector uses the same project (and shares one rate-limit /
    // metadata) instead of LI.FI's public default — the default
    // periodically fails `wallet_switchEthereumChain` with "An error
    // occurred when attempting to switch chain".
    if (walletConnectProjectId) {
        config.walletConfig = {
            walletConnect: {
                projectId: walletConnectProjectId,
                metadata: {
                    name: "GoodMarket",
                    description: "GoodMarket Community swap / bridge",
                    url: window.location?.origin || "https://goodmarket.live",
                    icons: ["https://goodmarket.live/static/images/favicon.png"],
                },
            },
        };
    }

    if (isPresentWallet(bootstrap.walletAddress)) {
        config.toAddress = {
            address: bootstrap.walletAddress,
            chainType: "EVM",
        };
    }

    return config;
}

function PreflightPanel({ bootstrap, config, refreshKey }) {
    const wallet = bootstrap.walletAddress;
    const connected = isPresentWallet(wallet);
    const toChain = Number(config.toChain || bootstrap.toChainId || 8453);
    const fromChain = Number(config.fromChain || bootstrap.fromChainId || CELO_CHAIN_ID);
    const [balances, setBalances] = useState({ celo: null, base: null, loaded: false, error: false });

    useEffect(() => {
        if (!connected) {
            setBalances({ celo: null, base: null, loaded: true, error: false });
            return undefined;
        }
        let cancelled = false;
        setBalances((prev) => ({ ...prev, loaded: false, error: false }));
        const celoRpc = firstRpcUrl(bootstrap.rpcUrls, CELO_CHAIN_ID, "https://forno.celo.org");
        const baseRpc = firstRpcUrl(bootstrap.rpcUrls, 8453, "https://mainnet.base.org");
        Promise.all([
            fetchNativeBalance(celoRpc, wallet),
            fetchNativeBalance(baseRpc, wallet),
        ]).then(([celo, base]) => {
            if (cancelled) return;
            setBalances({
                celo,
                base,
                loaded: true,
                error: celo === null && base === null,
            });
        });
        return () => { cancelled = true; };
    }, [wallet, connected, refreshKey]);

    const rows = [];

    // Always-on educational row about bridge minimums.
    rows.push({
        kind: "info",
        key: "min-amount",
        text: `Bridges (Allbridge, Glacis, Across, Stargate) usually need ≥ $${MIN_BRIDGE_USD} USD per transfer. Smaller amounts may quote zero routes or be eaten by fees.`,
    });

    if (!connected) {
        rows.push({
            kind: "info",
            key: "connect",
            text: "Connect a wallet inside the widget to see balance-aware checks (gas reserve on Celo, ETH on destination chain).",
        });
    } else if (!balances.loaded) {
        rows.push({
            kind: "info",
            key: "loading",
            text: "Checking your balances on Celo and the destination chain…",
        });
    } else {
        if (balances.celo !== null) {
            const formatted = formatNativeBalance(balances.celo, "CELO");
            if (balances.celo === 0n) {
                rows.push({
                    kind: "warn",
                    key: "celo-zero",
                    text: `Celo balance is 0 CELO. You can't pay gas or fund the bridge yet — top up your wallet first.`,
                });
            } else if (balances.celo < CELO_GAS_RESERVE_WEI) {
                rows.push({
                    kind: "warn",
                    key: "celo-low",
                    text: `Low Celo balance (${formatted}). Bridge txs need ~0.05 CELO of headroom for gas — sending more than ${formatNativeBalance(balances.celo > CELO_GAS_RESERVE_WEI ? balances.celo - CELO_GAS_RESERVE_WEI : 0n, "CELO")} will likely fail.`,
                });
            } else {
                rows.push({
                    kind: "info",
                    key: "celo-ok",
                    text: `Celo balance: ${formatted}. When using the widget's "Max" button, manually reduce by ~0.05 CELO so there's headroom for gas — LI.FI does NOT auto-reserve on Celo because CELO is an ERC-20.`,
                });
            }
        }

        if (toChain === 8453 && balances.base !== null && fromChain !== 8453) {
            const formatted = formatNativeBalance(balances.base, "ETH");
            if (balances.base === 0n) {
                rows.push({
                    kind: "warn",
                    key: "base-zero",
                    text: `0 ETH on Base. The most reliable Celo→Base routes are 2-step (bridge to USDC, then swap to ETH on Base); the second step needs Base ETH for gas. Either bridge ≥ $${MIN_BRIDGE_USD * 5} so a single-tx route is picked, OR pre-fund your Base wallet with a few cents of ETH first.`,
                });
            } else if (balances.base < BASE_ETH_GAS_RESERVE_WEI) {
                rows.push({
                    kind: "warn",
                    key: "base-low",
                    text: `Low Base ETH balance (${formatted}). The 2-step Celo→Base→ETH route needs ~0.0002 ETH on Base for the destination swap — top up a bit more before bridging.`,
                });
            }
        }

        if (balances.error) {
            rows.push({
                kind: "info",
                key: "rpc-fail",
                text: "Couldn't read your balances on Celo / Base (public RPC rate-limit). Refresh the widget to retry.",
            });
        }
    }

    return React.createElement("div",
        { className: "lifi-react-status lifi-react-status--stack", "data-connected": connected ? "true" : "false" },
        React.createElement("strong", null, "🛡️ LI.FI stability mode"),
        React.createElement("span", null, `Using ${config.routePriority.toLowerCase()}${config.useRecommendedRoute ? " recommended" : ""} routes with ${(config.slippage * 100).toFixed(1)}% slippage, multi-step bridges enabled, and Permit2 signing bypassed for Celo.`),
        ...rows.map((row) => React.createElement(
            "span",
            { key: row.key, className: `lifi-preflight-row lifi-preflight-row--${row.kind}` },
            row.kind === "warn" ? "⚠️ " : "ℹ️ ",
            row.text,
        )),
        React.createElement("button",
            { type: "button", className: "lifi-retry-btn", onClick: () => mount(true) },
            "Refresh quote widget & balances")
    );
}

function GoodMarketLifiWidget({ bootstrap, refreshKey }) {
    const config = useMemo(() => makeConfig(bootstrap), [bootstrap, refreshKey]);
    return React.createElement(React.Fragment, null,
        React.createElement(PreflightPanel, { bootstrap, config, refreshKey }),
        React.createElement(LiFiWidget, {
            integrator: config.integrator,
            config,
        })
    );
}

let _root = null;
let _refreshKey = 0;

function mount(forceReset = false) {
    const rootEl = document.getElementById("lifiWidgetRoot");
    if (!rootEl) return;
    const bootstrap = readBootstrap();
    try {
        if (forceReset && _root) {
            _root.unmount();
            _root = null;
        }
        if (forceReset) _refreshKey += 1;
        if (!_root) _root = createRoot(rootEl);
        _root.render(
            React.createElement(WidgetErrorBoundary, { key: _refreshKey },
                React.createElement(GoodMarketLifiWidget, { bootstrap, refreshKey: _refreshKey })
            )
        );
        window.GMLifiReactWidget = {
            refresh: () => {
                try { mount(true); } catch (err) {
                    console.warn("[GoodMarket LI.FI] refresh failed", err);
                }
            },
        };
    } catch (err) {
        console.error("[GoodMarket LI.FI] Widget mount failed", err);
        renderFallbackMessage("Could not initialize the LI.FI widget. Please hard refresh and try again.");
    }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
else mount();
