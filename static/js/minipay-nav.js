// MiniPay nav helper: hides Savings/Uniswap entry points for users in the
// MiniPay dapp browser. GoodReserve remains accessible. Detection is best-effort
// (provider flag + UA), and is mirrored server-side in select Flask routes.
(function () {
    function isMiniPay() {
        try {
            if (typeof window === 'undefined') return false;
            var eth = window.ethereum;
            if (eth && eth.isMiniPay) return true;
            if (eth && Array.isArray(eth.providers)
                && eth.providers.some(function (p) { return p && p.isMiniPay; })) return true;
            if (typeof navigator !== 'undefined'
                && /minipay/i.test(navigator.userAgent || '')) return true;
        } catch (_) { /* no-op */ }
        return false;
    }

    function hideSavingsLinks() {
        var sel = 'a[href="/savings"], a[href^="/savings?"], a[href^="/savings#"]';
        document.querySelectorAll(sel).forEach(function (el) {
            el.style.display = 'none';
        });
    }

    function apply() {
        if (!isMiniPay()) return;
        hideSavingsLinks();
        // Note: Uniswap V3 swap is now MiniPay-compatible via CIP-64 fee
        // abstraction in the tx helpers. The DEX pane is no longer hidden for
        // MiniPay users — both Uniswap and GoodReserve tabs are available.
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', apply, { once: true });
    } else {
        apply();
    }
})();
