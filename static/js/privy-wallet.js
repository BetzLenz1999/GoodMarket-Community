/**
 * GoodMarket × Privy Embedded Wallet Integration
 * ================================================
 * Handles wallet creation (email/Google/social login) via Privy.
 * The user gets a server-controlled embedded wallet — no seed phrase.
 *
 * Usage:
 *   1. Set PRIVY_APP_ID in your environment variables.
 *   2. Click "Create Wallet" on the homepage modal.
 *   3. User signs in via Privy → wallet is created on-chain.
 *   4. User can then sign messages/transactions without MetaMask.
 */

(function () {
    'use strict';

    // ── Config ──────────────────────────────────────────────────────────────
    var PRIVY_APP_ID = (window.__GM_PRIVY_CONFIG__ && window.__GM_PRIVY_CONFIG__.appId) || '';
    var CELO_RPC    = (window.__GM_PRIVY_CONFIG__ && window.__GM_PRIVY_CONFIG__.rpcUrl) || 'https://forno.celo.org';
    var EXPLORER    = (window.__GM_PRIVY_CONFIG__ && window.__GM_PRIVY_CONFIG__.explorer) || 'https://celoscan.io';

    // Privy chain config — Celo Alfajores (44787) and Mainnet (42220)
    var PRIVY_CHAINS = {
        42220: { rpcUrl: CELO_RPC, chainId: 'celo' },
        44787: { rpcUrl: 'https://alfajores-forno.celo-testnet.org', chainId: 'celo-alfajores' }
    };

    // ── SDK singleton ───────────────────────────────────────────────────────
    var _sdk         = null;   // @privy-io/react-auth provider
    var _initialized = false;
    var _initPromise = null;
    var _user        = null;   // cached user object

    // ── Public API ──────────────────────────────────────────────────────────

    /**
     * Check if Privy is properly configured with an APP_ID.
     */
    function isConfigured() {
        return !!PRIVY_APP_ID;
    }

    /**
     * Lazily initialize the Privy SDK. Safe to call multiple times.
     */
    function _ensureInit() {
        if (_initialized) return Promise.resolve(_sdk);
        if (_initPromise) return _initPromise;

        _initPromise = new Promise(function (resolve, reject) {
            // Inject Privy script dynamically
            if (!document.getElementById('privy-sdk-script')) {
                var script = document.createElement('script');
                script.id  = 'privy-sdk-script';
                // Privy's CDN — always loads the latest stable @privy-io/react-auth
                script.src = 'https://unpkg.com/@privy-io/react-auth@1.72.2/dist/iframe/parent/privy-ui-kit.iife.js';
                script.onload = function () { initSdk(resolve, reject); };
                script.onerror = function () { reject(new Error('Failed to load Privy SDK from CDN.')); };
                document.head.appendChild(script);
            } else {
                initSdk(resolve, reject);
            }
        });
        return _initPromise;
    }

    function initSdk(resolve, reject) {
        try {
            // Use Privy's UI Kit IIFE entrypoint
            var PrivyUIKit = window.PrivyUIKit;
            if (!PrivyUIKit) {
                reject(new Error('Privy UI Kit not found after script load.'));
                return;
            }

            // Create embedded wallet config
            var embeddedWalletConfig = {
                createWallet: true,  // auto-create embedded wallet on login
                noPromptOnSignature: false,
                // For Celo, use the embedded-wallet module
                embeddedWalletChainType: {
                    chainType: 'CELO',
                    chainId: 42220
                }
            };

            _sdk = PrivyUIKit.init({
                appId: PRIVY_APP_ID,
                embeddedWalletConfig: embeddedWalletConfig,
                // Appearance customization (optional)
                appearance: {
                    theme: 'dark',
                    accentColor: '#7c3aed',
                    logo: 'https://goodmarket.live/static/icons/goodmarket-icon.png'
                },
                loginMethods: [
                    { method: 'email', name: 'Email' },
                    { method: 'google', name: 'Google' },
                    { method: 'twitter', name: 'X (Twitter)' },
                    { method: 'apple', name: 'Apple' },
                    { method: 'phone', name: 'Phone' }
                ],
                // Wallets we support
                supportedChains: [42220, 44787]
            });

            _initialized = true;
            resolve(_sdk);
        } catch (err) {
            reject(err);
        }
    }

    /**
     * Start the Privy login flow. Opens the Privy modal for email / Google / etc.
     * Resolves with { address } on success, rejects on cancellation or error.
     */
    function login() {
        return _ensureInit().then(function () {
            return new Promise(function (resolve, reject) {
                try {
                    if (!_sdk || !_sdk.login) {
                        reject(new Error('Privy SDK not ready.'));
                        return;
                    }

                    // login() returns a Promise that resolves with the user object
                    _sdk.login({
                        loginMethod: 'email',  // default, but user can choose others
                        embeddedWalletProvider: ' PRIVY_EMBEDDED_WALLET'
                    }).then(function (user) {
                        _user = user;
                        var wallet = _getEmbeddedWallet(user);
                        if (!wallet) {
                            reject(new Error('No embedded wallet found for this user.'));
                            return;
                        }
                        resolve({ address: wallet.address });
                    }).catch(function (err) {
                        reject(err);
                    });
                } catch (err) {
                    reject(err);
                }
            });
        });
    }

    /**
     * Sign a message using the user's embedded wallet.
     * @param {string} message - The EIP-191 message to sign.
     * @returns {Promise<string>} - The signature hex string.
     */
    function signMessage(message) {
        return _ensureInit().then(function () {
            return new Promise(function (resolve, reject) {
                if (!_sdk || !_sdk.signMessage) {
                    reject(new Error('Privy SDK signMessage not available.'));
                    return;
                }

                var wallet = _getEmbeddedWallet(_user);
                if (!wallet) {
                    reject(new Error('No embedded wallet connected.'));
                    return;
                }

                _sdk.signMessage({
                    message: message,
                    address: wallet.address
                }).then(function (result) {
                    resolve(result.signature);
                }).catch(function (err) {
                    reject(err);
                });
            });
        });
    }

    /**
     * Sign and send a transaction using the user's embedded wallet.
     * @param {object} txParams - { to, data, value, gasLimit, gasPrice }
     * @returns {Promise<object>} - { txHash } on success.
     */
    function signTransaction(txParams) {
        return _ensureInit().then(function () {
            return new Promise(function (resolve, reject) {
                if (!_sdk || !_sdk.sendTransaction) {
                    reject(new Error('Privy SDK sendTransaction not available.'));
                    return;
                }

                var wallet = _getEmbeddedWallet(_user);
                if (!wallet) {
                    reject(new Error('No embedded wallet connected.'));
                    return;
                }

                _sdk.sendTransaction({
                    to: txParams.to,
                    data: txParams.data || '0x',
                    value: txParams.value || '0x0',
                    gasLimit: txParams.gasLimit,
                    gasPrice: txParams.gasPrice,
                    address: wallet.address,
                    chainId: 42220
                }).then(function (result) {
                    resolve({ txHash: result.hash });
                }).catch(function (err) {
                    reject(err);
                });
            });
        });
    }

    /**
     * Get the current user object.
     * @returns {object|null}
     */
    function getUser() {
        return _user;
    }

    /**
     * Get the embedded wallet address from a Privy user object.
     * @param {object} user - Privy user object.
     * @returns {object|null} - Wallet object with .address, .chainType, etc.
     */
    function _getEmbeddedWallet(user) {
        if (!user) return null;
        try {
            var wallets = user.walletWallets || [];
            for (var i = 0; i < wallets.length; i++) {
                var w = wallets[i];
                if (w.connectorType === 'PRIVY_EMBEDDED_WALLET' || w.type === 'embedded') {
                    return w;
                }
            }
            // Fallback: first wallet
            return wallets[0] || null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Export the private key of the embedded wallet.
     * Requires user confirmation and OTP verification via email.
     * @returns {Promise<string>} - The decrypted private key hex.
     */
    function exportPrivateKey() {
        return _ensureInit().then(function () {
            return new Promise(function (resolve, reject) {
                if (!_sdk || !_sdk.exportWallet) {
                    reject(new Error('Export not available. Make sure PRIVY_APP_ID is set.'));
                    return;
                }

                var wallet = _getEmbeddedWallet(_user);
                if (!wallet) {
                    reject(new Error('No embedded wallet to export.'));
                    return;
                }

                _sdk.exportWallet({
                    address: wallet.address,
                    exportWalletType: 'embedded'
                }).then(function (result) {
                    resolve(result.privateKey);
                }).catch(function (err) {
                    reject(err);
                });
            });
        });
    }

    /**
     * Disconnect the current user session.
     */
    function logout() {
        if (_sdk && _sdk.logout) {
            _sdk.logout().then(function () {
                _user        = null;
                _initialized = false;
                _sdk         = null;
                _initPromise = null;
            });
        } else {
            _user        = null;
            _initialized = false;
            _sdk         = null;
            _initPromise = null;
        }
    }

    /**
     * Check if a user session is currently active.
     * @returns {boolean}
     */
    function isLoggedIn() {
        return !!_user;
    }

    // ── Expose on window ────────────────────────────────────────────────────
    window.GMPrivy = {
        isConfigured:      isConfigured,
        login:             login,
        signMessage:       signMessage,
        signTransaction:   signTransaction,
        exportPrivateKey:  exportPrivateKey,
        logout:            logout,
        getUser:           getUser,
        isLoggedIn:        isLoggedIn
    };

})();