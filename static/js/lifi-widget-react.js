/**
 * GoodMarket — LI.FI / Jumper widget mount
 * ---------------------------------------------------------------------------
 * Renders the @lifi/widget React component into #lifiWidgetRoot on the
 * /swap "Buy ETH" tab.  LI.FI's widget handles its own wallet connection
 * (injected EIP-1193 wallets + WalletConnect via wagmi), so users can
 * connect from inside the widget regardless of how they signed in to
 * GoodMarket itself.  The widget supports cross-chain swaps between many
 * chains; defaults target Celo → native ETH on Base but the user can
 * change source/destination from inside the widget UI.
 *
 * The widget is loaded via esm.sh on demand to keep the rest of /swap
 * snappy — it is only fetched/mounted when this script runs (and the
 * inline page script defers the script tag until the user opens the
 * Buy ETH tab).
 *
 * Exposes window.GMLifiReactWidget = { refresh() } so the host page can
 * re-render the widget after layout changes (e.g. tab switching).
 */
import React, { useMemo } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { LiFiWidget } from "https://esm.sh/@lifi/widget@3?deps=react@18.3.1,react-dom@18.3.1";

const NATIVE_TOKEN = "0x0000000000000000000000000000000000000000";

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

function renderFallbackMessage(message) {
    const rootEl = document.getElementById("lifiWidgetRoot");
    if (!rootEl) return;
    rootEl.innerHTML = "";
    const box = document.createElement("div");
    box.className = "lifi-react-status";
    box.setAttribute("data-connected", "false");
    box.style.marginBottom = "0.75rem";
    box.innerHTML = `<strong>⚠️ Buy ETH widget unavailable</strong><span>${message}</span>`;
    rootEl.appendChild(box);
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
                React.createElement("strong", null, "⚠️ Buy ETH widget failed to render"),
                React.createElement("span", null, "Please refresh the page. If this continues, reconnect your wallet and try again.")
            );
        }
        return this.props.children;
    }
}

function makeConfig(bootstrap) {
    const integrator = bootstrap.integrator || "goodmarket-community";
    const fromChain = Number(bootstrap.fromChainId || 42220);
    const toChain = Number(bootstrap.toChainId || 8453);
    const fromToken = bootstrap.fromToken || NATIVE_TOKEN;
    const toToken = bootstrap.toToken || NATIVE_TOKEN;

    const config = {
        integrator,
        variant: "compact",
        appearance: "dark",
        fromChain,
        toChain,
        fromToken,
        toToken,
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

    if (bootstrap.apiUrl) {
        config.sdkConfig = { apiUrl: bootstrap.apiUrl };
    }

    if (isPresentWallet(bootstrap.walletAddress)) {
        config.toAddress = {
            address: bootstrap.walletAddress,
            chainType: "EVM",
        };
    }

    return config;
}

function GoodMarketLifiWidget({ bootstrap }) {
    const config = useMemo(() => makeConfig(bootstrap), [bootstrap]);
    return React.createElement(LiFiWidget, {
        integrator: config.integrator,
        config,
    });
}

let _root = null;

function mount() {
    const rootEl = document.getElementById("lifiWidgetRoot");
    if (!rootEl) return;
    const bootstrap = readBootstrap();
    try {
        if (!_root) _root = createRoot(rootEl);
        _root.render(
            React.createElement(WidgetErrorBoundary, null,
                React.createElement(GoodMarketLifiWidget, { bootstrap })
            )
        );
        window.GMLifiReactWidget = {
            refresh: () => {
                try { mount(); } catch (err) {
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
