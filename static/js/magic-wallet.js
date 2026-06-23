/**
 * Magic.link Embedded Wallet Integration
 * Simple Email OTP Mode - no custom auth provider needed
 * Supports Celo network
 */

let magic = null;
let magicWalletAddress = null;
let pendingEmail = null;
let magicLoadAttempts = 0;
const MAX_LOAD_ATTEMPTS = 10;

/**
 * Initialize and show the Magic wallet creation form
 */
function showPrivyForm() {
    document.getElementById('walletOptions').style.display = 'none';
    document.getElementById('privyFormContainer').classList.add('visible');
    document.getElementById('privySuccessContainer').style.display = 'none';
    document.getElementById('privy-embed-container').style.display = 'block';
    magicLoadAttempts = 0;
    initMagic();
}

/**
 * Initialize Magic SDK
 */
async function initMagic() {
    const container = document.getElementById('privy-embed-container');
    if (!container) {
        console.error('Magic container not found');
        return;
    }

    // Get API Key from template variable
    const MAGIC_API_KEY = typeof MAGIC_API_KEY_VAR !== 'undefined' ? MAGIC_API_KEY_VAR : '';

    console.log('Magic init called, API KEY present:', !!MAGIC_API_KEY, 'Value:', MAGIC_API_KEY);

    if (!MAGIC_API_KEY) {
        container.innerHTML = `
            <div style="padding: 2rem; text-align: center; color: #6b7280;">
                <p style="margin-bottom: 1rem;">⚠️ Magic.link API Key not configured</p>
                <p style="font-size: 0.85rem;">Please set the MAGIC_API_KEY environment variable.</p>
                <p style="font-size: 0.75rem; margin-top: 1rem;">Get your API Key at <a href="https://magic.link" target="_blank" style="color: #7c3aed;">magic.link</a></p>
            </div>
        `;
        return;
    }

    try {
        // Check if Magic SDK is loaded
        if (typeof Magic === 'undefined') {
            magicLoadAttempts++;
            console.log('Magic SDK not loaded yet, attempt:', magicLoadAttempts);
            
            if (magicLoadAttempts >= MAX_LOAD_ATTEMPTS) {
                container.innerHTML = `
                    <div style="padding: 2rem; text-align: center; color: #ef4444;">
                        <p style="margin-bottom: 1rem;">❌ Failed to load Magic SDK</p>
                        <p style="font-size: 0.85rem; color: #6b7280;">
                            The Magic SDK could not be loaded. Please check your internet connection<br>
                            or try refreshing the page.
                        </p>
                        <p style="font-size: 0.75rem; color: #9ca3af; margin-top: 1rem;">
                            Troubleshooting: Make sure the CDN URL is accessible
                        </p>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = `
                <div style="padding: 2rem; text-align: center; color: #6b7280;">
                    <div class="spinner" style="width: 24px; height: 24px; border: 3px solid #e5e7eb; border-top: 3px solid #35d07f; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 1rem;"></div>
                    <p>Loading Magic SDK... (${magicLoadAttempts}/${MAX_LOAD_ATTEMPTS})</p>
                </div>
                <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
            `;
            setTimeout(() => initMagic(), 500);
            return;
        }

        console.log('Magic SDK loaded, initializing with API key...');

        // Initialize Magic with Celo support
        magic = new Magic(MAGIC_API_KEY, {
            network: 'celo',  // Magic supports Celo natively
        });

        console.log('Magic instance created, checking login status...');

        // Check if user is already logged in
        const isLoggedIn = await magic.user.isLoggedIn();
        console.log('User logged in:', isLoggedIn);
        
        if (isLoggedIn) {
            // Get existing wallet address
            const info = await magic.user.getInfo();
            console.log('User info:', info);
            if (info && info.publicAddress) {
                magicWalletAddress = info.publicAddress;
                showMagicSuccess(info.publicAddress);
                return;
            }
        }

        // Show login form
        console.log('Showing login form...');
        showMagicLoginForm();

    } catch (error) {
        console.error('❌ Magic init error:', error);
        container.innerHTML = `
            <div style="padding: 2rem; text-align: center; color: #ef4444;">
                <p>Failed to initialize wallet creator.</p>
                <p style="font-size: 0.85rem; color: #6b7280; margin-top: 0.5rem;">${error.message || 'Please try again.'}</p>
            </div>
        `;
    }
}

/**
 * Show Magic login/email form
 */
function showMagicLoginForm() {
    const container = document.getElementById('privy-embed-container');
    container.innerHTML = `
        <div style="padding: 1rem;">
            <div style="text-align: center; margin-bottom: 1.5rem;">
                <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🌟</div>
                <h3 style="color: #1f2937; margin-bottom: 0.5rem;">Create Your Celo Wallet</h3>
                <p style="color: #6b7280; font-size: 0.85rem;">Enter your email to get started - it's free!</p>
            </div>
            
            <form id="magicEmailForm" style="display: flex; flex-direction: column; gap: 1rem;">
                <div>
                    <label style="display: block; font-size: 0.85rem; color: #374151; margin-bottom: 0.5rem;">Email Address</label>
                    <input 
                        type="email" 
                        id="magicEmailInput" 
                        placeholder="you@example.com"
                        required
                        style="width: 100%; padding: 0.75rem; border: 1px solid #d1d5db; border-radius: 8px; font-size: 1rem; box-sizing: border-box;"
                    >
                </div>
                <button 
                    type="submit" 
                    id="magicLoginBtn"
                    style="background: linear-gradient(135deg, #35d07f, #1a9f5a); color: white; border: none; padding: 0.875rem; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 1rem; transition: opacity 0.2s;"
                >
                    Get My Free Wallet
                </button>
            </form>
            
            <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;">
                <p style="font-size: 0.75rem; color: #9ca3af; text-align: center;">
                    🔒 Your email is only used for wallet recovery
                </p>
            </div>
        </div>
    `;

    document.getElementById('magicEmailForm').addEventListener('submit', handleMagicLogin);
}

/**
 * Handle Magic login with email OTP
 */
async function handleMagicLogin(e) {
    e.preventDefault();
    
    const email = document.getElementById('magicEmailInput').value.trim();
    const btn = document.getElementById('magicLoginBtn');
    
    if (!email) {
        alert('Please enter your email address');
        return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        alert('Please enter a valid email address');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending link...';
    btn.style.opacity = '0.7';

    try {
        // Request magic link for email verification
        await magic.auth.loginWithEmailOTP({ email });
        
        pendingEmail = email;
        
        // Show verification message
        const container = document.getElementById('privy-embed-container');
        container.innerHTML = `
            <div style="padding: 2rem; text-align: center;">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📧</div>
                <h3 style="color: #1f2937; margin-bottom: 0.5rem;">Check Your Email!</h3>
                <p style="color: #6b7280; font-size: 0.9rem; margin-bottom: 1rem;">
                    We sent a verification link to<br>
                    <strong style="color: #1f2937;">${email}</strong>
                </p>
                <p style="color: #9ca3af; font-size: 0.8rem; margin-bottom: 1.5rem;">
                    Click the link in your email to continue.<br>
                    The link expires in 5 minutes.
                </p>
                <button 
                    onclick="checkMagicLogin()"
                    style="background: linear-gradient(135deg, #35d07f, #1a9f5a); color: white; border: none; padding: 0.875rem 2rem; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 1rem;"
                >
                    I Verified - Continue
                </button>
                <p style="color: #9ca3af; font-size: 0.75rem; margin-top: 1rem;">
                    Didn't receive it? Check your spam folder.
                </p>
            </div>
        `;

    } catch (error) {
        console.error('Magic login error:', error);
        btn.disabled = false;
        btn.textContent = 'Get My Free Wallet';
        btn.style.opacity = '1';
        alert('Login failed: ' + (error.message || 'Please try again'));
    }
}

/**
 * Check if user completed Magic login
 */
async function checkMagicLogin() {
    try {
        const isLoggedIn = await magic.user.isLoggedIn();
        
        if (isLoggedIn) {
            const info = await magic.user.getInfo();
            if (info && info.publicAddress) {
                showMagicSuccess(info.publicAddress);
                return;
            }
        }
        
        alert('Please verify your email first by clicking the link we sent.');
        
    } catch (error) {
        console.error('Check login error:', error);
        alert('Something went wrong. Please try again.');
    }
}

/**
 * Show success screen with wallet address
 */
function showMagicSuccess(walletAddress) {
    const container = document.getElementById('privy-embed-container');
    const successContainer = document.getElementById('privySuccessContainer');
    const addressEl = document.getElementById('magicWalletAddress');
    
    if (container) container.style.display = 'none';
    
    if (successContainer && addressEl) {
        // Shorten address for display
        const shortAddress = walletAddress.slice(0, 6) + '...' + walletAddress.slice(-4);
        addressEl.textContent = shortAddress;
        addressEl.title = walletAddress;  // Show full address on hover
        successContainer.style.display = 'block';
        
        // Store wallet info for session
        sessionStorage.setItem('magic_wallet_address', walletAddress);
        sessionStorage.setItem('magic_wallet_created', 'true');
    }
}

/**
 * Continue to claim page after wallet creation
 */
function continueToClaim() {
    const walletAddress = sessionStorage.getItem('magic_wallet_address');
    if (walletAddress) {
        window.location.href = '/claim?wallet=' + walletAddress + '&method=magic';
    } else {
        window.location.href = '/wallet';
    }
}

/**
 * Get Magic provider for web3 operations
 */
function getMagicProvider() {
    if (magic) {
        return magic.rpcProvider;
    }
    return null;
}

/**
 * Check if user has a Magic wallet in session
 */
function hasMagicWallet() {
    return sessionStorage.getItem('magic_wallet_created') === 'true';
}

/**
 * Logout user
 */
async function magicLogout() {
    if (magic) {
        await magic.user.logout();
        sessionStorage.removeItem('magic_wallet_address');
        sessionStorage.removeItem('magic_wallet_created');
    }
}
