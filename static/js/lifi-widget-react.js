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
 * The widget is loaded via esm.sh on demand to keep the rest of /swap
 * snappy — it is only fetched/mounted when this script runs (and the
 * inline page script defers the script tag until the user opens the
 * Buy Crypto tab).
 *
 * Exposes window.GMLifiReactWidget = { refresh() } so the host page can
 * re-render the widget after layout changes (e.g. tab switching).
 */
import React, { useMemo } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { LiFiWidget } from "https://esm.sh/@lifi/widget@3?deps=react@18.3.1,react-dom@18.3.1";

const NATIVE_TOKEN = "0x0000000000000000000000000000000000000000";
const DEFAULT_STABILITY = Object.freeze({
    routePriority: "FASTEST",
    slippage: 0.01,
    useRecommendedRoute: true,
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

function makeConfig(bootstrap) {
    const integrator = bootstrap.integrator || "goodmarket-community";
    const fromChain = Number(bootstrap.fromChainId || 42220);
    const toChain = Number(bootstrap.toChainId || 8453);
    const fromToken = bootstrap.fromToken || NATIVE_TOKEN;
    const toToken = bootstrap.toToken || NATIVE_TOKEN;
    const routePriority = normalizeRoutePriority(bootstrap.routePriority);
    const slippage = clampSlippage(bootstrap.slippage);
    const useRecommendedRoute = normalizeBoolean(bootstrap.useRecommendedRoute, DEFAULT_STABILITY.useRecommendedRoute);
    const rpcUrls = readRpcUrls(bootstrap);

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

    if (isPresentWallet(bootstrap.walletAddress)) {
        config.toAddress = {
            address: bootstrap.walletAddress,
            chainType: "EVM",
        };
    }

    return config;
}

function GoodMarketLifiWidget({ bootstrap, refreshKey }) {
    const config = useMemo(() => makeConfig(bootstrap), [bootstrap, refreshKey]);
    return React.createElement(React.Fragment, null,
        React.createElement("div", { className: "lifi-react-status lifi-react-status--stack", "data-connected": isPresentWallet(bootstrap.walletAddress) ? "true" : "false" },
            React.createElement("strong", null, "🛡️ LI.FI stability mode"),
            React.createElement("span", null, `Using ${config.routePriority.toLowerCase()}${config.useRecommendedRoute ? " recommended" : ""} routes with ${(config.slippage * 100).toFixed(1)}% slippage tolerance. If a route fails, reload the widget to force a fresh LI.FI quote before signing again.`),
            React.createElement("button", { type: "button", className: "lifi-retry-btn", onClick: () => mount(true) }, "Refresh quote widget")
        ),
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
