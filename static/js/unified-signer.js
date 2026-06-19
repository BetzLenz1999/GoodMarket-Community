/**
 * GoodMarket unified signer/provider resolution.
 * ---------------------------------------------------------------------------
 * Shared helper that keeps the signer source aligned with the login method:
 * WalletConnect-backed logins use the WC bridge, while injected-wallet logins
 * use MiniPay / Trust Wallet / MetaMask / EIP-6963 providers.
 */
(function (global) {
    "use strict";

    if (global.GMUnifiedSigner) return;

    var _config = {
        loginMethod: "",
        walletAddress: ""
    };

    function _normLogin(loginMethod) {
        return String(loginMethod || "").trim().toLowerCase();
    }

    function _shouldPreferWalletConnect() {
        return ["walletconnect", "manual", "manual_address"].includes(_normLogin(_config.loginMethod));
    }

    function configure(opts) {
        if (!opts || typeof opts !== "object") return;
        if (Object.prototype.hasOwnProperty.call(opts, "loginMethod")) {
            _config.loginMethod = opts.loginMethod || "";
        }
        if (Object.prototype.hasOwnProperty.call(opts, "walletAddress")) {
            _config.walletAddress = opts.walletAddress || "";
        }
    }

    function _dispatchProviderRequest() {
        try {
            global.dispatchEvent(new Event("eip6963:requestProvider"));
        } catch (_) {}
    }

    function _coerceToRequestProvider(candidate) {
        if (!candidate) return null;
        if (typeof candidate.request === "function") return candidate;
        if (candidate.ethereum && typeof candidate.ethereum.request === "function") return candidate.ethereum;
        if (candidate.provider && typeof candidate.provider.request === "function") return candidate.provider;

        var sendAsync = typeof candidate.sendAsync === "function"
            ? candidate.sendAsync.bind(candidate)
            : (typeof candidate.send === "function" ? candidate.send.bind(candidate) : null);
        if (!sendAsync) return null;

        candidate.request = function (_ref) {
            var method = _ref.method;
            var params = _ref.params;
            return new Promise(function (resolve, reject) {
                sendAsync({
                    jsonrpc: "2.0",
                    id: Date.now(),
                    method: method,
                    params: Array.isArray(params) ? params : []
                }, function (err, res) {
                    if (err) return reject(err);
                    if (res && res.error) return reject(res.error);
                    resolve(res && Object.prototype.hasOwnProperty.call(res, "result") ? res.result : res);
                });
            });
        };
        return candidate;
    }

    function _eip6963Providers() {
        return Array.isArray(global.__announced6963Providers)
            ? global.__announced6963Providers.slice()
            : [];
    }

    function _collectInjectedProviders() {
        var out = [];
        function push(candidate) {
            var provider = _coerceToRequestProvider(candidate);
            if (provider && out.indexOf(provider) === -1) out.push(provider);
        }

        if (global.ethereum) {
            if (Array.isArray(global.ethereum.providers)) {
                global.ethereum.providers.forEach(push);
            }
            push(global.ethereum);
        }
        if (global.trustwallet) push(global.trustwallet);
        if (global.trustwallet && global.trustwallet.ethereum) push(global.trustwallet.ethereum);
        if (global.trustWallet) push(global.trustWallet);
        if (global.trustWallet && global.trustWallet.ethereum) push(global.trustWallet.ethereum);
        _eip6963Providers().forEach(function (detail) {
            if (detail && detail.provider) push(detail.provider);
        });
        return out;
    }

    function _pickInjectedProvider(candidates) {
        if (!candidates || !candidates.length) return null;

        var miniPay = candidates.find(function (p) { return p && p.isMiniPay; });
        if (miniPay) return miniPay;

        var trust = candidates.find(function (p) { return p && (p.isTrust || p.isTrustWallet); });
        if (trust) return trust;

        var trust6963 = _eip6963Providers().find(function (detail) {
            var info = detail && detail.info ? detail.info : {};
            var rdns = String(info.rdns || "").toLowerCase();
            var name = String(info.name || "").toLowerCase();
            return rdns.indexOf("trustwallet") >= 0 || name.indexOf("trust") >= 0;
        });
        if (trust6963 && trust6963.provider) {
            var coercedTrust = _coerceToRequestProvider(trust6963.provider);
            if (coercedTrust) return coercedTrust;
        }

        var metamask = candidates.find(function (p) { return p && p.isMetaMask && !p.isBraveWallet; });
        if (metamask) return metamask;

        if (global.ethereum && Array.isArray(global.ethereum.providers) && global.ethereum.providers.length) {
            return global.ethereum.providers[0];
        }
        if (global.ethereum) return global.ethereum;
        return candidates[0];
    }

    function getInjectedProvider() {
        _dispatchProviderRequest();
        return _pickInjectedProvider(_collectInjectedProviders());
    }

    async function awaitInjectedProvider(timeoutMs) {
        var budget = typeof timeoutMs === "number" ? timeoutMs : 900;
        var started = Date.now();
        var found = getInjectedProvider();
        if (found) return found;
        while (Date.now() - started < budget) {
            _dispatchProviderRequest();
            await new Promise(function (resolve) { setTimeout(resolve, 120); });
            found = getInjectedProvider();
            if (found) return found;
        }
        return null;
    }

    async function getWalletConnectProvider() {
        if (!global.GMWalletConnect || typeof global.GMWalletConnect.isPreferred !== "function") return null;
        if (!global.GMWalletConnect.isPreferred()) return null;
        try {
            return await global.GMWalletConnect.getProvider();
        } catch (_) {
            return null;
        }
    }

    async function getSigningProvider(timeoutMs) {
        if (_shouldPreferWalletConnect()) {
            return getWalletConnectProvider();
        }

        var injected = await awaitInjectedProvider(timeoutMs);
        if (injected) return injected;

        return getWalletConnectProvider();
    }

    global.GMUnifiedSigner = {
        configure: configure,
        getInjectedProvider: getInjectedProvider,
        awaitInjectedProvider: awaitInjectedProvider,
        getSigningProvider: getSigningProvider,
        getWalletConnectProvider: getWalletConnectProvider
    };
})(typeof window !== "undefined" ? window : this);
