// GoodMarket "Buy Crypto" (Celo -> Base ETH) integration.
//
// History: this used to mount the full @0xsquid/widget React SDK pulled at
// runtime from esm.sh. That approach loaded 600+ transitive modules (Cosmos,
// Solana, Bitcoin, WalletConnect, etc.) on every /swap load, which made the
// pane slow and — because a single failed module fetch rejects the whole
// dynamic import — frequently rendered a blank widget.
//
// We now embed Squid's official hosted iframe widget
// (https://studio.squidrouter.com/iframe?config=...). It is a single, cached
// page load: fast, reliable, and pre-configured to Celo -> Base ETH with the
// user's GoodMarket wallet as the default recipient. Injected wallets
// (MetaMask/Rabby/Trust) and MiniPay are auto-detected inside the iframe;
// WalletConnect users tap "Connect" once inside the widget.

const IFRAME_BASE = "https://studio.squidrouter.com/iframe";
const NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE";

function readBootstrap() {
    const node = document.getElementById("squidWidgetBootstrap");
    if (!node) return {};
    try { return JSON.parse(node.textContent || "{}"); }
    catch (err) {
        console.error("[GoodMarket Squid] Invalid widget bootstrap JSON", err);
        return {};
    }
}

function isPresentWallet(address) {
    return Boolean(address && address !== "None" && /^0x[0-9a-fA-F]{40}$/.test(address));
}

function normalizeToken(token) {
    return {
        symbol: token?.symbol || "CELO",
        address: token?.address || NATIVE_TOKEN,
    };
}

// Build the Squid Studio iframe config from the server-provided bootstrap and
// the currently selected Celo source token.
function buildConfig(bootstrap, sourceToken) {
    const baseConfig = bootstrap.widgetConfig || {};
    const sourceChainId = Number(bootstrap.fromChainId || 42220);
    const destinationChainId = Number(bootstrap.toChainId || 8453);
    const token = normalizeToken(sourceToken || bootstrap.sourceTokens?.[0]);
    const fromChainId = Number.isFinite(sourceChainId) ? sourceChainId : 42220;
    const toChainId = Number.isFinite(destinationChainId) ? destinationChainId : 8453;

    const config = {
        ...baseConfig,
        // Squid's API rejects an empty/unregistered integratorId (401), so we
        // always send one, defaulting to Squid's public widget id.
        integratorId: bootstrap.integratorId || baseConfig.integratorId || "squid-swap-widget",
        apiUrl: bootstrap.apiUrl || baseConfig.apiUrl || "https://v2.api.squidrouter.com",
        themeType: baseConfig.themeType || "dark",
        initialAssets: {
            ...(baseConfig.initialAssets || {}),
            // Studio iframe expects chainId as a string.
            from: { address: token.address, chainId: String(fromChainId) },
            to: { address: bootstrap.toToken || NATIVE_TOKEN, chainId: String(toChainId) },
        },
    };

    // Default the destination to the user's GoodMarket wallet so the widget
    // opens ready to deliver bought ETH straight to their wallet.
    if (isPresentWallet(bootstrap.walletAddress)) {
        config.initialRecipientAddress = bootstrap.walletAddress;
        config.toAddress = bootstrap.walletAddress;
    }
    return config;
}

function buildIframeSrc(bootstrap, sourceToken) {
    const config = buildConfig(bootstrap, sourceToken);
    return `${IFRAME_BASE}?config=${encodeURIComponent(JSON.stringify(config))}`;
}

function renderStatus(rootEl, message, connected) {
    const box = document.createElement("div");
    box.className = "squid-react-status";
    box.setAttribute("data-connected", connected ? "true" : "false");
    box.innerHTML = `<strong>${connected ? "✅" : "🔌"} Buy Crypto widget</strong><span>${message}</span>`;
    rootEl.appendChild(box);
}

function mount() {
    const rootEl = document.getElementById("squidReactWidgetRoot");
    if (!rootEl) return;

    const bootstrap = readBootstrap();
    let currentToken = normalizeToken(bootstrap.sourceTokens?.[0]);

    const build = () => {
        rootEl.innerHTML = "";
        renderStatus(rootEl, "Squid cross-chain widget — Celo → Base ETH.", true);

        const shell = document.createElement("div");
        shell.className = "squid-react-shell";

        const iframe = document.createElement("iframe");
        iframe.title = "squid_widget";
        iframe.src = buildIframeSrc(bootstrap, currentToken);
        iframe.loading = "eager";
        iframe.setAttribute("allow", "clipboard-write; clipboard-read; web-share");
        iframe.style.width = "100%";
        iframe.style.minHeight = "684px";
        iframe.style.height = "684px";
        iframe.style.border = "0";
        iframe.style.borderRadius = "16px";
        iframe.style.background = "transparent";
        iframe.onerror = () => {
            rootEl.innerHTML = "";
            const box = document.createElement("div");
            box.className = "squid-react-status";
            box.setAttribute("data-connected", "false");
            box.innerHTML = `<strong>⚠️ Buy Crypto widget unavailable</strong>` +
                `<span>Please refresh. You can also open the widget directly: ` +
                `<a href="${buildIframeSrc(bootstrap, currentToken)}" target="_blank" rel="noopener" style="color:#bae6fd;">open ↗</a>.</span>`;
            rootEl.appendChild(box);
        };

        shell.appendChild(iframe);
        rootEl.appendChild(shell);
    };

    // Public API used by swap.html. setSwapTab('buyeth') calls refresh() when
    // the user opens the Buy Crypto pane, and the source-token pills call
    // setSourceToken(). Both (re)build the iframe.
    window.GMSquidReactWidget = {
        setSourceToken: (symbol, address) => {
            currentToken = normalizeToken({ symbol, address });
            build();
        },
        refresh: () => build(),
    };

    // Build immediately only when the Buy Crypto pane is already on-screen
    // (e.g. landing on /swap?tab=buyeth). Otherwise stay lazy so a normal
    // /swap visit does not load the cross-origin iframe until it is opened.
    const pane = document.getElementById("swapPaneBuyEth");
    const paneVisible = pane &&
        !pane.classList.contains("hidden-tab") &&
        pane.style.display !== "none";
    if (paneVisible) build();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
else mount();
