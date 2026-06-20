/**
 * turnkey-google-login.js
 *
 * Handles the "Create new wallet" flow on the homepage:
 *   1. Email OTP via Turnkey Auth Proxy (direct fetch — no SDK needed)
 *   2. Google social login via Google Identity Services
 *   3. Finalizes the Flask session through the backend
 */
(function () {
  'use strict';

  var _gsiLoaded = false;
  var _gsiLoading = null;
  var _emailOtpId = '';
  var _emailContact = '';

  /* ── Helpers ── */

  function loadGsi() {
    if (_gsiLoaded && window.google && window.google.accounts) {
      return Promise.resolve();
    }
    if (_gsiLoading) return _gsiLoading;
    _gsiLoading = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = 'https://accounts.google.com/gsi/client';
      s.async = true;
      s.defer = true;
      s.onload = function () { _gsiLoaded = true; resolve(); };
      s.onerror = function () { reject(new Error('Failed to load Google Identity Services SDK')); };
      document.head.appendChild(s);
    });
    return _gsiLoading;
  }

  function statusEl(kind) {
    return document.getElementById(kind === 'email' ? 'turnkeyEmailStatus' : 'turnkeyGoogleStatus');
  }

  function showStatus(kind, msg, type) {
    var el = statusEl(kind);
    if (!el) return;
    el.className = 'status-message ' + (type || 'info');
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
  }

  function showOtpWrap(show) {
    var el = document.getElementById('turnkeyEmailOtpWrap');
    if (el) el.style.display = show ? 'block' : 'none';
  }

  function showVerifySection(show) {
    var el = document.getElementById('turnkeyVerifySection');
    if (el) el.style.display = show ? 'block' : 'none';
  }

  function getEmailValue() {
    var el = document.getElementById('turnkeyEmailAddress');
    return el ? el.value.trim() : '';
  }

  function getNameValue() {
    var el = document.getElementById('turnkeyNameInput');
    return el ? el.value.trim() : '';
  }

  function getReferralCode() {
    var el = document.getElementById('googleReferralCode');
    return el ? el.value.trim() : '';
  }

  /* ── Turnkey Auth Proxy: direct fetch (no SDK) ── */

  function _proxyPost(subpath, body) {
    return fetch('/api/turnkey/auth-proxy/' + subpath, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) {
          var msg = data.error || data.message || ('Request failed (' + resp.status + ')');
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  /* ── Session finalization ── */

  function finalizeSession(kind, sessionToken, loginMethod, email, name) {
    showStatus(kind, '⏳ Finalizing your wallet…', 'info');
    return fetch('/api/turnkey/auth-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_token: sessionToken,
        login_method: loginMethod,
        email: email || '',
        user_name: name || '',
        referral_code: getReferralCode(),
      }),
    }).then(function (resp) {
      return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    }).then(function (result) {
      if (!result.ok || !result.data.success) {
        throw new Error(result.data.error || 'Session finalization failed');
      }
      var warning = result.data.referral_warning;
      showStatus(kind,
        warning ? ('✅ Wallet ready! ⚠️ ' + warning + ' Redirecting…') : '✅ Wallet ready! Redirecting…',
        warning ? 'warning' : 'success'
      );
      setTimeout(function () { window.location.href = '/wallet'; }, warning ? 2400 : 900);
    }).catch(function (err) {
      showStatus(kind, '❌ ' + (err.message || 'Could not finalize wallet'), 'error');
    });
  }

  /* ── Email OTP flow ── */

  function sendEmailOtp() {
    var email = getEmailValue();
    if (!email) {
      showStatus('email', 'Please enter an email address first.', 'warning');
      return Promise.resolve(false);
    }

    var orgId = window.__TURNKEY_ORGANIZATION_ID || '';
    if (!orgId) {
      showStatus('email', '❌ Email login is not configured on this server. Please use Google login.', 'error');
      return Promise.resolve(false);
    }

    showStatus('email', '⏳ Sending a code to your email…', 'info');
    showVerifySection(false);

    return _proxyPost('api/v1/otp/init', {
      otpType: 'OTP_TYPE_EMAIL',
      contact: email,
      organizationId: orgId,
    }).then(function (data) {
      _emailOtpId = data.otpId || '';
      if (!_emailOtpId) throw new Error('No OTP ID returned from server');
      _emailContact = email;
      showOtpWrap(true);
      showVerifySection(true);
      showStatus('email', '✅ Code sent! Check your email (and spam folder).', 'success');
      var codeInput = document.getElementById('turnkeyEmailOtpCode');
      if (codeInput) codeInput.focus();
      return true;
    }).catch(function (err) {
      showOtpWrap(false);
      showVerifySection(false);
      var msg = err.message || 'Could not send code';
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
        msg = 'Network error. Please check your connection and try again.';
      }
      showStatus('email', '❌ ' + msg, 'error');
      return false;
    });
  }

  function completeEmailOtp() {
    var email = getEmailValue();
    var name = getNameValue();
    var codeInput = document.getElementById('turnkeyEmailOtpCode');
    var otpCode = codeInput ? codeInput.value.trim() : '';

    if (!_emailOtpId) {
      showStatus('email', 'Send the email code first.', 'warning');
      return Promise.resolve(false);
    }
    if (!_emailContact || _emailContact !== email) {
      showStatus('email', 'Use the same email address that received the code.', 'warning');
      return Promise.resolve(false);
    }
    if (!otpCode) {
      showStatus('email', 'Enter the code from your email.', 'warning');
      return Promise.resolve(false);
    }

    var orgId = window.__TURNKEY_ORGANIZATION_ID || '';
    showStatus('email', '⏳ Verifying your code…', 'info');

    return _proxyPost('api/v1/otp/complete', {
      otpId: _emailOtpId,
      otpCode: otpCode,
      otpType: 'OTP_TYPE_EMAIL',
      contact: email,
      organizationId: orgId,
      createSubOrgParams: {
        subOrgName: name ? ('GoodMarket \u2013 ' + name) : ('GoodMarket \u2013 ' + email),
        rootUsers: [{
          userName: name || email,
          userEmail: email,
          apiKeys: [],
          authenticators: [],
          oauthProviders: [],
        }],
        rootQuorumThreshold: 1,
        wallet: {
          walletName: 'Default Wallet',
          accounts: [{
            curve: 'CURVE_SECP256K1',
            pathFormat: 'PATH_FORMAT_BIP32',
            path: "m/44'/60'/0'/0/0",
            addressFormat: 'ADDRESS_FORMAT_ETHEREUM',
          }],
        },
      },
    }).then(function (data) {
      var sessionToken = data.session || data.sessionToken || data.token || '';
      if (!sessionToken) throw new Error('No session token in response');
      return finalizeSession('email', sessionToken, 'turnkey_email', email, name);
    }).catch(function (err) {
      showStatus('email', '❌ ' + (err.message || 'Could not verify code'), 'error');
      return false;
    });
  }

  /* ── Google login flow ── */

  function sendTokenToBackend(idToken, referralCode) {
    showStatus('google', '⏳ Creating your wallet…', 'info');
    return fetch('/api/turnkey/google-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: idToken, referral_code: referralCode || '' }),
    }).then(function (resp) {
      return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    }).then(function (result) {
      if (!result.ok || !result.data.success) {
        throw new Error(result.data.error || 'Login failed');
      }
      var warning = result.data.referral_warning;
      showStatus('google',
        warning ? ('✅ Wallet ready! ⚠️ ' + warning + ' Redirecting…') : '✅ Wallet ready! Redirecting…',
        warning ? 'warning' : 'success'
      );
      setTimeout(function () { window.location.href = '/wallet'; }, warning ? 2400 : 900);
    }).catch(function (err) {
      showStatus('google', '❌ ' + (err.message || 'Google login failed'), 'error');
    });
  }

  function handleGoogleCredentialResponse(response) {
    if (!response || !response.credential) {
      showStatus('google', '❌ Google sign-in was cancelled', 'warning');
      return;
    }
    sendTokenToBackend(response.credential, getReferralCode());
  }

  function initGoogleButton() {
    var clientId = window.__GOOGLE_CLIENT_ID;
    if (!clientId) {
      console.warn('[turnkey-google] No GOOGLE_CLIENT_ID configured');
      return;
    }
    loadGsi().then(function () {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: handleGoogleCredentialResponse,
        auto_select: false,
        cancel_on_tap_outside: true,
      });
      var btnWrap = document.getElementById('googleSignInBtnWrap');
      if (btnWrap) {
        window.google.accounts.id.renderButton(btnWrap, {
          type: 'standard',
          theme: 'filled_blue',
          size: 'large',
          text: 'signin_with',
          shape: 'pill',
          width: 300,
        });
      }
    }).catch(function (err) {
      console.error('[turnkey-google] GIS load error:', err);
      showStatus('google', '❌ Could not load Google Sign-In', 'error');
    });
  }

  /* ── Email input reset listener ── */

  function setupEmailChangeListener() {
    var emailInput = document.getElementById('turnkeyEmailAddress');
    if (emailInput && !emailInput.dataset.otpResetAttached) {
      emailInput.dataset.otpResetAttached = 'true';
      emailInput.addEventListener('input', function () {
        if (_emailContact && getEmailValue() !== _emailContact) {
          _emailOtpId = '';
          _emailContact = '';
          showOtpWrap(false);
          showVerifySection(false);
          showStatus('email', '', '');
        }
      });
    }
  }

  /* ── Public API ── */

  window.TurnkeyGoogleLogin = { init: initGoogleButton };

  window.TurnkeyAuthFlow = {
    prepare: function () {
      setupEmailChangeListener();
    },
    initGoogleButton: initGoogleButton,
    sendEmailOtp: sendEmailOtp,
    completeEmailOtp: completeEmailOtp,
  };
})();
