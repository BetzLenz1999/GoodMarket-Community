# Deploying `GoodMarketMiniPayCUSDFaucet` in Remix

## What this contract does
- Holds cUSD inside the contract.
- Allows one fixed disburser wallet (set at deploy) to disburse cUSD to users.
- Emits custom event `GoodMarketTopWallet` on every disbursement.
- **Gas is still paid in CELO by the caller wallet** (your backend signer / `TOPWALLET_KEY`).

## 1) Open Remix and compile
1. Go to https://remix.ethereum.org
2. Create/import file: `GoodMarketMiniPayCUSDFaucet.sol`
3. Solidity compiler version: **0.8.20**
4. Compile contract.

> ⚠️ **Common mistake:** `deploy_minipay_cusd_faucet.py` is a Python file.  
> Do not paste it into a `.sol` file in Remix, or it will show red syntax errors.

## 2) Deploy constructor params
Constructor:
- `cUSDToken`: `0x765DE816845861e75A25fCA122bb6898B8B1282a` (Celo mainnet cUSD)
- `fixedDisburser`: backend wallet address that will call `disburseCUSD` (usually `TOPWALLET_KEY` public address)
- `fixedCooldownSeconds`: per-wallet on-chain cooldown (recommended: `172800` for 48h)

Network:
- Celo Mainnet (chainId `42220`)

## 3) Fund the contract
After deploy, transfer cUSD into contract address (this is the faucet pool).

## 4) Disburse call format
Function:
- `disburseCUSD(recipient, amount, correlationId, sourceTag)`

Example:
- `recipient`: `0xabc...`
- `amount`: `10000000000000000` for `0.01 cUSD` (18 decimals)
- `correlationId`: bytes32 like `0x6661756365742d31323300000000000000000000000000000000000000000000`
- `sourceTag`: `minipay_cusd_faucet`

## 5) Event logging
Every successful disbursement emits:
- `GoodMarketTopWallet(recipient, operator, amount, correlationId, sourceTag, timestamp)`

This gives you custom on-chain analytics/audit naming.


## 6) Backend env vars after you deploy in Remix
Once you have the deployed contract address, set these in your GoodMarket app env:

- `GOODMARKETFAUCETMODE=CONTRACT` to use contract-based disbursement
- `GOODMARKET_CUSD_FAUCET_CONTRACT_ADDRESS=<your deployed contract address>`
- `TOPWALLET_KEY=<same backend private key>`
- `CUSD_CONTRACT=0x765DE816845861e75A25fCA122bb6898B8B1282a` (Celo mainnet)

Fallback / legacy mode:

- `GOODMARKETFAUCETMODE=PRIVATEKEY`
- In this mode, backend sends `cUSD.transfer(...)` directly from `TOPWALLET_KEY`.

### Mode behavior summary
- `CONTRACT`: backend uses `TOPWALLET_KEY` to call `disburseCUSD(...)` on your faucet contract.
- `PRIVATEKEY`: backend uses `TOPWALLET_KEY` to call cUSD token `transfer(...)` directly.
- In both modes, **gas fee is paid in CELO by the TOPWALLET_KEY signer**.


## 7) Deposit behavior (requested)
- Anyone can deposit cUSD into the faucet pool.
- Recommended: call `approve(faucetAddress, amount)` on cUSD, then call `depositCUSD(amount)` on faucet contract.
- You can still send cUSD directly via `cUSD.transfer(faucetAddress, amount)` as normal ERC-20 transfer.
- There is no withdraw/emergency-withdraw/admin function in the faucet contract.
- Cooldown is also enforced on-chain via `disburseCUSD` and `cooldownRemaining(recipient)`.

## 8) If Remix shows red error / Gas estimation failed

> The contract itself compiles cleanly and a valid deployment estimates at
> roughly **560k gas**. If Remix says *"gas estimation failed"*, it is almost
> always one of the constructor `require(...)` checks reverting, **not** a bug
> in the `.sol` source.

### Step 1 — confirm you're compiling the Solidity file, not the Python one
- The opened file must be `GoodMarketMiniPayCUSDFaucet.sol`.
- `deploy_minipay_cusd_faucet.py` is a Python deploy script and will look like
  pure red errors if pasted into Remix's Solidity editor.
- Solidity compiler version: **0.8.20**.

### Step 2 — check the 3 constructor `require()`s
The constructor has exactly three guard clauses. Remix's "gas estimation failed"
message corresponds 1:1 to whichever one trips:

| Revert reason          | What it means in Remix                                   | Fix |
|------------------------|----------------------------------------------------------|-----|
| `zero_cusd`            | `cUSDToken` field is `0x0000...0000` or left blank       | Use `0x765DE816845861e75A25fCA122bb6898B8B1282a` (Celo mainnet cUSD) |
| `zero_disburser`       | `fixedDisburser` field is `0x0000...0000` or left blank  | Paste the public address of the wallet your backend will use as `TOPWALLET_KEY` |
| `zero_cooldown`        | `fixedCooldownSeconds` field is `0`                      | Use `172800` for 48h (or any positive integer in seconds) |

Tip: Remix sometimes auto-fills constructor inputs from a previously deployed
contract's ABI. Click the dropdown next to **Deploy** and re-enter the values
to make sure nothing is silently `0x0` / `0`.

### Step 3 — check the deployer wallet
- Wallet must hold **CELO** (not just cUSD) — gas for deployment is paid in
  CELO. Roughly **0.005 CELO** is enough at ~5 gwei.
- MetaMask network must be **Celo Mainnet (chainId 42220)** — not Alfajores,
  not Ethereum.
- Deploy **Value** field must be `0` (the constructor is non-payable).
- "Estimated gas" Remix shows is around `560000`; manually overriding to
  something low (e.g. `21000`) will also surface as "gas estimation failed".

### Step 4 — verify locally before re-trying in Remix
If you have the repo cloned, you can sanity-check the exact constructor args
against a real Celo RPC. `py-solc-x`, `web3`, and `eth-account` are already in
`pyproject.toml`, so `uv run` is enough:

```bash
export CELO_RPC=https://forno.celo.org
export TOPWALLET_KEY=0x...                # CELO-funded deployer
uv run python contracts/deploy_minipay_cusd_faucet.py \
    --cusd 0x765DE816845861e75A25fCA122bb6898B8B1282a \
    --disburser 0xYOUR_BACKEND_PUBLIC_ADDRESS \
    --cooldown-seconds 172800
```

If `estimate_gas` succeeds (~560k), Remix is also fine — the failure is on
the Remix/MetaMask side (network selection, gas price, or a stale constructor
input).

### Step 5 — last-resort fallback
If Remix keeps failing despite the checks above, deploy via the Python script
(`contracts/deploy_minipay_cusd_faucet.py`). It is fully equivalent to the
Remix flow and uses the same compiler version + bytecode.
