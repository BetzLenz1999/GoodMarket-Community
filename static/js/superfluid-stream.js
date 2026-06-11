/**
 * Superfluid G$ Streaming Library
 * 
 * Provides functions for creating, monitoring, and stopping G$ streams on Celo
 * using the Superfluid protocol via ethers.js.
 * 
 * Features:
 * - Create/update/delete streams
 * - Transaction history tracking
 * - Multiple stream support with individual stop buttons
 * - Explorer links for transactions
 */

// ethers.js CDN URL
const ETHERS_JS_URL = 'https://cdn.jsdelivr.net/npm/ethers@5.7.2/dist/ethers.umd.min.js';

// Get Superfluid configuration from backend (injected by Jinja template)
// Falls back to hardcoded defaults for Celo Mainnet (chainId: 42220)
const _backendConfig = window.SUPERFLUID_CONFIG || {};
const SUPERFLUID_CONFIG = {
    chainId: 42220,
    hostAddress: _backendConfig.host_address || '0xEB796bdb90fFA0da2d5c532F2bA53Fb15E59344b',
    cfaV1Address: _backendConfig.cfa_v1_address || '0x254A4D3b2a5D9B8C7D6E5F4A3B2C1D0E9F8A7B6C',
    resolverAddress: _backendConfig.resolver_address || '0x85998f8F8B0C69CBE8F31F56C7A5C79E16a7dF59',
};

// G$ Token address on Celo (Super Token wrapper)
const G_DOLLAR_SUPER_TOKEN = _backendConfig.super_token_address || '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A';

// CFAv1 ABI - minimal functions needed for flow operations
const CFAV1_ABI = [
    "function createFlow(address superToken, address sender, address receiver, int96 flowRate, bytes calldata userData) external returns (bool)",
    "function updateFlow(address superToken, address sender, address receiver, int96 flowRate, bytes calldata userData) external returns (bool)",
    "function deleteFlow(address superToken, address sender, address receiver, address userData) external returns (bool)",
    "function getFlow(address superToken, address sender, address receiver) external view returns (uint256,uint256,uint256,uint256)",
    "function getAccountFlowInfo(address superToken, address account) external view returns (int96,uint256,uint256)",
    "function getFlowRate(address superToken, address sender, address receiver) external view returns (int96)"
];

// Global state
let _ethers = null;
let _provider = null;
let _signer = null;
let _cfaContract = null;
let _isInitialized = false;
let _userAddress = null;

/**
 * Load ethers.js from CDN
 */
async function loadEthersJs() {
    return new Promise((resolve, reject) => {
        if (typeof window.ethers !== 'undefined') {
            _ethers = window.ethers;
            resolve();
            return;
        }

        const script = document.createElement('script');
        script.src = ETHERS_JS_URL;
        script.onload = () => {
            _ethers = window.ethers;
            resolve();
        };
        script.onerror = () => reject(new Error('Failed to load ethers.js'));
        document.head.appendChild(script);
    });
}

/**
 * Initialize Superfluid with wallet provider
 */
async function initSuperfluid(ethereumProvider, userAddress) {
    if (!ethereumProvider) {
        throw new Error('No Ethereum provider available');
    }

    try {
        await loadEthersJs();

        _provider = new _ethers.providers.Web3Provider(ethereumProvider);
        _signer = _provider.getSigner();
        _userAddress = await _signer.getAddress();

        _cfaContract = new _ethers.Contract(
            SUPERFLUID_CONFIG.cfaV1Address,
            CFAV1_ABI,
            _signer
        );

        _isInitialized = true;
        console.log('[Superfluid] Initialized for', _userAddress);

        return true;
    } catch (err) {
        console.error('[Superfluid] Init failed:', err);
        _isInitialized = false;
        throw err;
    }
}

/**
 * Check if Superfluid is ready
 */
function isSuperfluidReady() {
    return _isInitialized && _cfaContract !== null;
}

/**
 * Convert G$/second to wei/second
 */
function gToWei(gPerSecond) {
    const g$Decimals = 18;
    return _ethers.utils.parseUnits(gPerSecond.toFixed(18), g$Decimals);
}

/**
 * Create a new G$ stream
 */
async function createStream(recipientAddress, flowRate) {
    if (!_isInitialized || !_cfaContract) {
        throw new Error('Superfluid not initialized');
    }

    const recipientChecksum = _ethers.utils.getAddress(recipientAddress);
    const flowRateWei = gToWei(flowRate);

    try {
        console.log('[Superfluid] Creating stream:', {
            to: recipientChecksum,
            rate: flowRate
        });

        const tx = await _cfaContract.createFlow(
            G_DOLLAR_SUPER_TOKEN,
            _userAddress,
            recipientChecksum,
            flowRateWei,
            '0x'
        );

        console.log('[Superfluid] Tx submitted:', tx.hash);

        const receipt = await tx.wait();

        console.log('[Superfluid] Stream created:', {
            recipient: recipientChecksum,
            flowRate: flowRate,
            txHash: receipt.transactionHash
        });

        // Add to transaction history
        addStreamTransaction({
            type: 'create',
            recipient: recipientChecksum,
            flowRate: flowRate,
            txHash: receipt.transactionHash,
            status: 'confirmed',
            blockNumber: receipt.blockNumber,
        });

        // Store stream locally
        storeStream(recipientChecksum, flowRate, receipt.transactionHash);

        return {
            success: true,
            txHash: receipt.transactionHash,
            recipient: recipientChecksum,
            flowRate: flowRate,
        };
    } catch (err) {
        console.error('[Superfluid] Failed to create stream:', err);
        
        addStreamTransaction({
            type: 'create',
            recipient: recipientChecksum,
            flowRate: flowRate,
            txHash: null,
            status: 'failed',
            error: err.message || 'Unknown error',
        });

        const errorMsg = err.message || '';
        if (errorMsg.includes('user rejected') || errorMsg.includes('User denied')) {
            throw new Error('Transaction cancelled');
        }
        if (errorMsg.includes('insufficient funds')) {
            throw new Error('Insufficient balance for stream');
        }
        
        throw new Error('Failed to create stream: ' + (err.reason || err.message || 'Unknown error'));
    }
}

/**
 * Delete/stop a G$ stream
 */
async function deleteStream(recipientAddress) {
    if (!_isInitialized || !_cfaContract) {
        throw new Error('Superfluid not initialized');
    }

    const recipientChecksum = _ethers.utils.getAddress(recipientAddress);

    try {
        const tx = await _cfaContract.deleteFlow(
            G_DOLLAR_SUPER_TOKEN,
            _userAddress,
            recipientChecksum,
            '0x'
        );

        const receipt = await tx.wait();

        console.log('[Superfluid] Stream deleted:', {
            recipient: recipientChecksum,
            txHash: receipt.transactionHash
        });

        addStreamTransaction({
            type: 'delete',
            recipient: recipientChecksum,
            flowRate: 0,
            txHash: receipt.transactionHash,
            status: 'confirmed',
            blockNumber: receipt.blockNumber,
        });

        return {
            success: true,
            txHash: receipt.transactionHash,
            recipient: recipientChecksum,
        };
    } catch (err) {
        console.error('[Superfluid] Failed to delete stream:', err);
        
        addStreamTransaction({
            type: 'delete',
            recipient: recipientChecksum,
            flowRate: 0,
            txHash: null,
            status: 'failed',
            error: err.message || 'Unknown error',
        });
        
        throw new Error('Failed to delete stream: ' + (err.reason || err.message || 'Unknown error'));
    }
}

/**
 * Get flow information for a stream
 */
async function getFlowInfo(sender, receiver) {
    if (!_isInitialized || !_cfaContract) {
        throw new Error('Superfluid not initialized');
    }

    try {
        const readOnlyCfa = _cfaContract.connect(_provider);
        const flowInfo = await readOnlyCfa.getFlow(
            G_DOLLAR_SUPER_TOKEN,
            sender,
            receiver
        );

        return {
            exists: flowInfo.deposit > 0 || flowInfo.flowRate > 0,
            flowRate: parseFloat(_ethers.utils.formatUnits(flowInfo.flowRate, 'ether')),
            deposit: _ethers.utils.formatUnits(flowInfo.deposit, 'ether'),
            owed: _ethers.utils.formatUnits(flowInfo.owed, 'ether'),
        };
    } catch (err) {
        console.error('[Superfluid] Failed to get flow info:', err);
        return { exists: false, flowRate: 0, deposit: 0, owed: 0 };
    }
}

/**
 * Get all streams where user is sender (outgoing)
 */
async function getMyOutgoingStreams() {
    if (!_isInitialized || !_userAddress) {
        return [];
    }

    try {
        const streams = [];
        const storedStreams = getStoredStreams();

        for (const recipient of Object.keys(storedStreams)) {
            try {
                const flowInfo = await getFlowInfo(_userAddress, recipient);
                const txHistory = getStreamHistoryForRecipient(recipient);
                const createTx = txHistory.find(tx => tx.type === 'create' && tx.status === 'confirmed');

                if (flowInfo.exists && flowInfo.flowRate > 0) {
                    streams.push({
                        recipient: recipient,
                        flowRate: flowInfo.flowRate,
                        startTime: storedStreams[recipient].startTime || (createTx ? createTx.timestamp : null),
                        startTxHash: storedStreams[recipient].startTxHash || (createTx ? createTx.txHash : null),
                        txHistory: txHistory,
                        canStop: true,
                    });
                }
            } catch (e) {
                console.warn('[Superfluid] Could not get flow info for', recipient, e);
            }
        }

        return streams;
    } catch (err) {
        console.error('[Superfluid] Failed to get outgoing streams:', err);
        return [];
    }
}

/**
 * Get all streams where user is receiver (incoming)
 */
async function getMyIncomingStreams() {
    if (!_isInitialized || !_userAddress) {
        return [];
    }

    try {
        const readOnlyCfa = _cfaContract.connect(_provider);
        const accountFlowInfo = await readOnlyCfa.getAccountFlowInfo(
            G_DOLLAR_SUPER_TOKEN,
            _userAddress
        );

        const netFlowRate = parseFloat(_ethers.utils.formatUnits(accountFlowInfo.flowRate, 'ether'));
        console.log('[Superfluid] Net flow rate for', _userAddress, ':', netFlowRate);
        
        return netFlowRate > 0 ? [{
            netFlowRate: netFlowRate,
            note: 'Net flow rate (individual streams require subgraph)'
        }] : [];
    } catch (err) {
        console.error('[Superfluid] Failed to get incoming streams:', err);
        return [];
    }
}

// ============ TRANSACTION HISTORY ============

const STREAM_HISTORY_KEY = 'sf_stream_history';
const STREAM_HISTORY_MAX = 100;

/**
 * Add a stream transaction to history
 */
function addStreamTransaction(txData) {
    const history = getStreamHistory();
    
    const txRecord = {
        id: 'sf_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9),
        type: txData.type,
        recipient: _ethers ? _ethers.utils.getAddress(txData.recipient) : txData.recipient,
        flowRate: txData.flowRate,
        txHash: txData.txHash,
        timestamp: Date.now(),
        status: txData.status || 'confirmed',
        blockNumber: txData.blockNumber,
        error: txData.error || null,
    };
    
    history.unshift(txRecord);
    
    if (history.length > STREAM_HISTORY_MAX) {
        history.pop();
    }
    
    localStorage.setItem(STREAM_HISTORY_KEY, JSON.stringify(history));
    return txRecord;
}

/**
 * Get complete stream transaction history
 */
function getStreamHistory() {
    try {
        const stored = localStorage.getItem(STREAM_HISTORY_KEY);
        return stored ? JSON.parse(stored) : [];
    } catch (err) {
        return [];
    }
}

/**
 * Get transaction history for a specific recipient
 */
function getStreamHistoryForRecipient(recipient) {
    const history = getStreamHistory();
    const checksumAddr = _ethers ? _ethers.utils.getAddress(recipient) : recipient;
    return history.filter(tx => tx.recipient.toLowerCase() === checksumAddr.toLowerCase());
}

/**
 * Get transaction by hash
 */
function getStreamTxByHash(txHash) {
    const history = getStreamHistory();
    return history.find(tx => tx.txHash && tx.txHash.toLowerCase() === txHash.toLowerCase());
}

/**
 * Clear stream history
 */
function clearStreamHistory() {
    localStorage.removeItem(STREAM_HISTORY_KEY);
}

/**
 * Get enriched stream history with explorer URLs
 */
async function getStreamHistoryWithTxData() {
    const history = getStreamHistory();
    const enrichedHistory = [];
    
    for (const tx of history) {
        try {
            let flowInfo = null;
            if (tx.status === 'confirmed') {
                flowInfo = await getFlowInfo(_userAddress, tx.recipient);
            }
            
            enrichedHistory.push({
                ...tx,
                isActive: flowInfo ? flowInfo.exists && flowInfo.flowRate > 0 : (tx.type !== 'delete'),
                currentFlowRate: flowInfo ? flowInfo.flowRate : tx.flowRate,
                explorerUrl: tx.txHash ? 'https://explorer.celo.org/tx/' + tx.txHash : null,
                formattedDate: new Date(tx.timestamp).toLocaleString(),
                shortRecipient: tx.recipient.substring(0, 6) + '...' + tx.recipient.substring(38),
            });
        } catch (e) {
            enrichedHistory.push({
                ...tx,
                isActive: false,
                currentFlowRate: 0,
                explorerUrl: tx.txHash ? 'https://explorer.celo.org/tx/' + tx.txHash : null,
                formattedDate: new Date(tx.timestamp).toLocaleString(),
                shortRecipient: tx.recipient.substring(0, 6) + '...' + tx.recipient.substring(38),
            });
        }
    }
    
    return enrichedHistory;
}

// ============ LOCAL STORAGE ============

const STREAM_STORAGE_KEY = 'sf_streams';

/**
 * Store stream info locally
 */
function storeStream(recipientAddress, flowRate, txHash) {
    const streams = getStoredStreams();
    const checksumAddr = _ethers ? _ethers.utils.getAddress(recipientAddress) : recipientAddress;
    streams[checksumAddr] = {
        flowRate: flowRate,
        startTime: Date.now(),
        startTxHash: txHash,
    };
    localStorage.setItem(STREAM_STORAGE_KEY, JSON.stringify(streams));
}

/**
 * Get all stored streams
 */
function getStoredStreams() {
    try {
        const stored = localStorage.getItem(STREAM_STORAGE_KEY);
        return stored ? JSON.parse(stored) : {};
    } catch (err) {
        return {};
    }
}

/**
 * Remove stream from local storage
 */
function removeStoredStream(recipientAddress) {
    const streams = getStoredStreams();
    const checksumAddr = _ethers ? _ethers.utils.getAddress(recipientAddress) : recipientAddress;
    delete streams[checksumAddr];
    localStorage.setItem(STREAM_STORAGE_KEY, JSON.stringify(streams));
}

// ============ HELPERS ============

/**
 * Format flow rate for display
 */
function formatFlowRate(flowRate) {
    if (flowRate >= 1) {
        return flowRate.toFixed(2) + ' G$/sec';
    } else if (flowRate >= 0.001) {
        return (flowRate * 1000).toFixed(2) + ' mG$/sec';
    } else {
        return (flowRate * 1000000).toFixed(2) + ' uG$/sec';
    }
}

/**
 * Convert flow rate to human readable
 */
function flowRateToHumanReadable(flowRate) {
    return formatFlowRate(flowRate);
}

/**
 * Convert UI selector (amount + unit) to flow rate
 */
function selectorToFlowRate(unit, amount) {
    const rates = {
        'per-second': 1,
        'per-minute': 60,
        'per-hour': 3600,
        'per-day': 86400,
    };
    return amount * (rates[unit] || 1);
}

/**
 * Estimate total G$ for a stream
 */
function estimateStreamTotal(flowRate, seconds) {
    return flowRate * seconds;
}

// ============ EXPORTS ============

window.SuperfluidStream = {
    init: initSuperfluid,
    isReady: isSuperfluidReady,
    createStream: createStream,
    deleteStream: deleteStream,
    getFlowInfo: getFlowInfo,
    getMyOutgoingStreams: getMyOutgoingStreams,
    getMyIncomingStreams: getMyIncomingStreams,
    storeStream: storeStream,
    removeStoredStream: removeStoredStream,
    getStoredStreams: getStoredStreams,
    getStreamHistory: getStreamHistory,
    getStreamHistoryForRecipient: getStreamHistoryForRecipient,
    getStreamTxByHash: getStreamTxByHash,
    getStreamHistoryWithTxData: getStreamHistoryWithTxData,
    clearStreamHistory: clearStreamHistory,
    formatFlowRate: formatFlowRate,
    flowRateToHumanReadable: flowRateToHumanReadable,
    selectorToFlowRate: selectorToFlowRate,
    estimateStreamTotal: estimateStreamTotal,
};

console.log('[Superfluid] SuperfluidStream library loaded');