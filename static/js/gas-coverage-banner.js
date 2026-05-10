/*
 * gas-coverage-banner.js
 *
 * Shared, lightweight UI helper that surfaces a one-time banner after a
 * successful GoodDollar Celo gas faucet top-up (either the goodserver API
 * path or GoodMarket's TOPWALLET_KEY on-chain fallback). The backend
 * (`/api/faucet/gas`, `/api/faucet/onchain`) returns `show_gas_coverage_message: true`
 * and a `gas_coverage_message` string when the wallet has just been topped
 * up; the frontend simply hands that response to `MaybeShowGasCoverageBanner`
 * and the helper takes care of the rest.
 *
 * The banner explains that the refill is meant to cover ~3 days of claims
 * and that the user shouldn't transfer the CELO out — if they do, their
 * next claim will fail because the GoodMarket faucet is locked out for 48
 * hours. This is the user-facing companion to the persistent
 * `celo_gas_faucet_refills` cooldown enforced server-side.
 *
 * Wallet-agnostic by design: works for MetaMask / Trust Wallet / Coinbase
 * Wallet desktop or in-app browsers, MiniPay, and WalletConnect-bridged
 * wallets, since the only input is the JSON response shape.
 *
 * Public API (window.GMGasCoverageBanner):
 *   - maybeShow(faucetResponse, opts?)   -> bool (true if rendered)
 *   - dismiss()                          -> void
 */
(function (global) {
    'use strict';
    if (global.GMGasCoverageBanner) return;

    const STORAGE_KEY_PREFIX = 'gmGasCoverageBannerSeen:';
    const STORAGE_TTL_SECONDS = 60 * 60 * 24 * 2; // 2 days, matches default 48h cooldown
    const BANNER_ID = 'gm-gas-coverage-banner';

    function _hasStorage() {
        try {
            const k = '__gm_test__';
            global.localStorage.setItem(k, '1');
            global.localStorage.removeItem(k);
            return true;
        } catch (_) { return false; }
    }

    function _alreadySeen(walletKey, refillAt) {
        if (!walletKey || !refillAt || !_hasStorage()) return false;
        try {
            const raw = global.localStorage.getItem(STORAGE_KEY_PREFIX + walletKey);
            if (!raw) return false;
            const parsed = JSON.parse(raw);
            if (!parsed || parsed.refillAt !== refillAt) return false;
            const now = Math.floor(Date.now() / 1000);
            if (parsed.seenAt && now - parsed.seenAt > STORAGE_TTL_SECONDS) return false;
            return true;
        } catch (_) { return false; }
    }

    function _markSeen(walletKey, refillAt) {
        if (!walletKey || !refillAt || !_hasStorage()) return;
        try {
            global.localStorage.setItem(
                STORAGE_KEY_PREFIX + walletKey,
                JSON.stringify({ refillAt, seenAt: Math.floor(Date.now() / 1000) })
            );
        } catch (_) { /* ignore */ }
    }

    function _ensureStyle() {
        if (document.getElementById('gm-gas-coverage-style')) return;
        const style = document.createElement('style');
        style.id = 'gm-gas-coverage-style';
        style.textContent = [
            '#' + BANNER_ID + ' {',
            '    position: fixed;',
            '    left: 50%;',
            '    bottom: 24px;',
            '    transform: translateX(-50%);',
            '    z-index: 99999;',
            '    max-width: min(560px, calc(100vw - 32px));',
            '    width: 100%;',
            '    background: linear-gradient(135deg, #1f2937 0%, #0f172a 100%);',
            '    color: #f8fafc;',
            '    border: 1px solid rgba(96, 165, 250, 0.6);',
            '    border-radius: 14px;',
            '    box-shadow: 0 12px 32px rgba(15, 23, 42, 0.45);',
            '    padding: 16px 18px;',
            '    font-size: 0.95rem;',
            '    line-height: 1.45;',
            '    display: flex;',
            '    flex-direction: column;',
            '    gap: 10px;',
            '    animation: gmGasBannerIn 220ms ease-out;',
            '}',
            '@keyframes gmGasBannerIn {',
            '    from { opacity: 0; transform: translate(-50%, 12px); }',
            '    to { opacity: 1; transform: translate(-50%, 0); }',
            '}',
            '#' + BANNER_ID + ' .gm-gas-banner-title {',
            '    font-weight: 600;',
            '    color: #bae6fd;',
            '    display: flex;',
            '    align-items: center;',
            '    gap: 8px;',
            '}',
            '#' + BANNER_ID + ' .gm-gas-banner-body {',
            '    color: #e2e8f0;',
            '}',
            '#' + BANNER_ID + ' .gm-gas-banner-footer {',
            '    display: flex;',
            '    justify-content: flex-end;',
            '    gap: 8px;',
            '}',
            '#' + BANNER_ID + ' button {',
            '    background: rgba(59, 130, 246, 0.85);',
            '    color: #fff;',
            '    border: none;',
            '    border-radius: 8px;',
            '    padding: 7px 14px;',
            '    font-weight: 600;',
            '    cursor: pointer;',
            '    font-size: 0.9rem;',
            '}',
            '#' + BANNER_ID + ' button.gm-gas-banner-secondary {',
            '    background: transparent;',
            '    color: #cbd5e1;',
            '    border: 1px solid rgba(203, 213, 225, 0.35);',
            '}'
        ].join('\n');
        document.head.appendChild(style);
    }

    function _formatHours(seconds) {
        const s = Number(seconds || 0);
        if (!Number.isFinite(s) || s <= 0) return '48h';
        const h = Math.max(1, Math.round(s / 3600));
        return h + 'h';
    }

    function dismiss() {
        const el = document.getElementById(BANNER_ID);
        if (el && el.parentNode) {
            el.parentNode.removeChild(el);
        }
    }

    function maybeShow(faucetResponse, opts) {
        if (!faucetResponse || typeof faucetResponse !== 'object') return false;
        if (!faucetResponse.show_gas_coverage_message) return false;

        const walletKey = String(
            (opts && opts.wallet) || faucetResponse.wallet || ''
        ).toLowerCase();
        const refillAt = String(faucetResponse.gooddollar_last_refill_at || '');
        if (_alreadySeen(walletKey, refillAt)) return false;

        const message = String(
            faucetResponse.gas_coverage_message ||
            "You just received gas from the GoodDollar faucet. This refill covers " +
            "roughly 3 days of claims — please don't transfer this CELO out, " +
            "or your next claim will fail and we can't request more gas for 48h."
        );
        const cooldownLabel = _formatHours(
            faucetResponse.gooddollar_cooldown_remaining_seconds ||
            faucetResponse.gooddollar_cooldown_total_seconds
        );

        try {
            dismiss();
            _ensureStyle();
            const banner = document.createElement('div');
            banner.id = BANNER_ID;
            banner.setAttribute('role', 'status');
            banner.setAttribute('aria-live', 'polite');

            const title = document.createElement('div');
            title.className = 'gm-gas-banner-title';
            title.textContent = '⛽ Gas top-up received';
            banner.appendChild(title);

            const body = document.createElement('div');
            body.className = 'gm-gas-banner-body';
            body.textContent = message;
            banner.appendChild(body);

            const subtext = document.createElement('div');
            subtext.className = 'gm-gas-banner-body';
            subtext.style.fontSize = '0.82rem';
            subtext.style.color = '#94a3b8';
            subtext.textContent = 'Next GoodMarket gas request available in ~' + cooldownLabel + '.';
            banner.appendChild(subtext);

            const footer = document.createElement('div');
            footer.className = 'gm-gas-banner-footer';

            const okBtn = document.createElement('button');
            okBtn.type = 'button';
            okBtn.textContent = 'Got it';
            okBtn.addEventListener('click', () => {
                _markSeen(walletKey, refillAt);
                dismiss();
            });
            footer.appendChild(okBtn);
            banner.appendChild(footer);

            document.body.appendChild(banner);
            _markSeen(walletKey, refillAt);
            return true;
        } catch (_) {
            return false;
        }
    }

    global.GMGasCoverageBanner = { maybeShow, dismiss };
})(typeof window !== 'undefined' ? window : this);
