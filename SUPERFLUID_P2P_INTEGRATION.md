# Superfluid P2P g$ Streaming Integration Guide

## ✅ COMPLETED INTEGRATION

All backend requirements are now configured and ready for frontend integration.

---

## 📋 Environment Variables Required

Add these to your `.env` file or deployment environment:

```env
# === Superfluid P2P Streaming ===
SUPERFLUID_CFAV1_FORWARDER=0xcfA132E353cB4E398080B9700609bb008eceB125
GOODDOLLAR_CONTRACT_ADDRESS=0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A
SUPERFLUID_DEV_G_DOLLAR_ADDRESS=0xFa51eFDc0910CCdA91732e6806912Fa12e2FD475
USE_DEV_G_DOLLAR=false

# === Celo Network ===
CHAIN_ID=42220
CELO_RPC_URL=https://forno.celo.org
```

---

## 🔧 Integration Constants (from GoodDollar Docs)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **CFAv1Forwarder** | `0xcfA132E353cB4E398080B9700609bb008eceB125` | Universal address on all chains |
| **G$ SuperToken (Production)** | `0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A` | Pure SuperToken on Celo |
| **G$ SuperToken (Dev)** | `0xFa51eFDc0910CCdA91732e6806912Fa12e2FD475` | For testing |
| **Chain ID** | `42220` | Celo Mainnet |
| **RPC URL** | `https://forno.celo.org` | No API key needed |
| **Flow Rate Divisor** | `2592000` | Seconds in 30 days |

---

## 📡 API Endpoints

### 1. Get Streaming Constants
```
GET /api/p2p/stream/constants
```
Returns CFAv1Forwarder address, chain info, G$ addresses.

### 2. Prepare Stream Creation
```
POST /api/p2p/stream/create/prepare
Body: { "receiver": "0x...", "flow_rate_per_month": 100 }
```
Returns transaction data for signing.

### 3. Prepare Stream Update
```
POST /api/p2p/stream/update/prepare
Body: { "receiver": "0x...", "new_flow_rate_per_month": 200 }
```
Returns transaction data for signing.

### 4. Prepare Stream Deletion
```
POST /api/p2p/stream/delete/prepare
Body: { "receiver": "0x..." }
```
Returns transaction data for signing.

### 5. Get Stream Info
```
GET /api/p2p/stream/info?sender=0x...&receiver=0x...
```
Returns current stream status between sender and receiver.

### 6. Get User Stream Summary
```
GET /api/p2p/stream/summary?wallet=0x...
```
Returns aggregate stream info (incoming + outgoing).

### 7. Calculate Required Buffer
```
GET /api/p2p/buffer/calculate?flow_rate_per_month=100
```
Returns required buffer amount for a flow rate.

---

## 🔢 Flow Rate Calculation

```javascript
// Formula: flowRate = amount_per_month * 10^18 / 2592000
flowRate = (G$ per month) * 1e18 / 2592000

// Example: 100 G$/month
flowRate = 100 * 1e18 / 2592000
// = 3858024691358024 (int96)
```

---

## 💰 Buffer Requirements

When creating a stream, the sender must have:
1. **Flow Rate Amount** - G$ to stream per month
2. **Security Buffer** - Extra G$ locked during stream duration

Use `getBufferAmountByFlowRate()` to calculate buffer:
```
Buffer = f(flow_rate, chain_parameters)
```

---

## 🎯 Frontend Integration Flow

```javascript
// 1. Get constants
const { data } = await fetch('/api/p2p/stream/constants').then(r => r.json());
// data.cfav1_forwarder = "0xcfA132E353cB4E398080B9700609bb008eceB125"
// data.production_g_dollar = "0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A"

// 2. Prepare transaction
const txData = await fetch('/api/p2p/stream/create/prepare', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    receiver: '0xReceiverAddress',
    flow_rate_per_month: 100
  })
}).then(r => r.json());

// 3. Sign with wallet
const provider = new ethers.providers.Web3Provider(window.ethereum);
const signer = provider.getSigner();
const tx = await signer.sendTransaction({
  to: txData.data.to,
  data: txData.data.data,
  chainId: 42220
});
```

---

## 📚 Reference Documentation

- **GoodDollar Streaming Guide**: https://docs.gooddollar.org/for-developers/developer-guides/use-gusd-streaming
- **Superfluid CFAv1Forwarder**: https://docs.superfluid.org/docs/technical-reference/CFAv1Forwarder
- **Superfluid SDK**: https://docs.superfluid.org/docs/sdk/quickstart

---

## 🧪 Testing

For testing, use the Dev G$ token:
```env
USE_DEV_G_DOLLAR=true
SUPERFLUID_DEV_G_DOLLAR_ADDRESS=0xFa51eFDc0910CCdA91732e6806912Fa12e2FD475
```

Claim free Dev G$ at: https://goodwallet.dev

---

## ⚠️ Important Notes

1. **Pure SuperToken** - G$ is already a SuperToken, no wrapping needed
2. **Only on Celo** - Streaming is live only on Celo (chain 42220)
3. **Buffer Required** - Sender needs G$ balance + security buffer
4. **Gas Fees** - User pays CELO for gas (not G$)
5. **Real-time** - Streams flow every second automatically

---

## 🎨 UI/UX Recommendations

### Stream Creation Form
1. Input: Recipient wallet address
2. Input: Amount (G$/month or G$/second)
3. Display: Required buffer amount
4. Display: Estimated total G$ needed (amount + buffer)
5. Button: "Start Streaming"

### Stream Management
1. Display: Current stream rate
2. Display: Stream status (active/inactive)
3. Display: Total streamed to date
4. Buttons: Update Rate, Stop Stream

---

## ✅ Status: READY FOR FRONTEND CODING

All backend components are configured:
- ✅ Superfluid P2P streaming functions added to `blockchain.py`
- ✅ P2P streaming routes added to `routes.py`
- ✅ Configuration constants added to `config.py`
- ✅ All environment variables documented

**Next Step**: Build the frontend P2P streaming UI component!