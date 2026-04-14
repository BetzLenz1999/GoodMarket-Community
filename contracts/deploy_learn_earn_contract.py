"""
Learn & Earn Rewards Contract Deployment Script for Celo Network

This script deploys the LearnAndEarnRewards contract to Celo mainnet
using LEARN_WALLET_PRIVATE_KEY as the contract owner.
"""

import os
import json
import logging
from web3 import Web3
from eth_account import Account
from solcx import compile_standard, install_solc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CELO_RPC_URL = os.getenv('CELO_RPC_URL', 'https://forno.celo.org')
CHAIN_ID = int(os.getenv('CHAIN_ID', 42220))
GOODDOLLAR_CONTRACT = os.getenv('GOODDOLLAR_CONTRACT', '0x62B8B11039FcfE5aB0C56E502b1C372A3d2a9c7A')

MAX_DISBURSEMENT = 1000 * 10**18
MIN_DISBURSEMENT = 1 * 10**18

FLATTENED_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

interface IERC20 {
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

library Address {
    function isContract(address account) internal view returns (bool) {
        return account.code.length > 0;
    }
    
    function functionCall(address target, bytes memory data) internal returns (bytes memory) {
        return functionCall(target, data, "Address: low-level call failed");
    }
    
    function functionCall(address target, bytes memory data, string memory errorMessage) internal returns (bytes memory) {
        require(isContract(target), "Address: call to non-contract");
        (bool success, bytes memory returndata) = target.call(data);
        if (success) {
            return returndata;
        } else {
            if (returndata.length > 0) {
                assembly {
                    let returndata_size := mload(returndata)
                    revert(add(32, returndata), returndata_size)
                }
            } else {
                revert(errorMessage);
            }
        }
    }
}

library SafeERC20 {
    using Address for address;
    
    function safeTransfer(IERC20 token, address to, uint256 value) internal {
        _callOptionalReturn(token, abi.encodeWithSelector(token.transfer.selector, to, value));
    }
    
    function safeTransferFrom(IERC20 token, address from, address to, uint256 value) internal {
        _callOptionalReturn(token, abi.encodeWithSelector(token.transferFrom.selector, from, to, value));
    }
    
    function safeApprove(IERC20 token, address spender, uint256 value) internal {
        require((value == 0) || (token.allowance(address(this), spender) == 0), "SafeERC20: approve from non-zero to non-zero allowance");
        _callOptionalReturn(token, abi.encodeWithSelector(token.approve.selector, spender, value));
    }
    
    function _callOptionalReturn(IERC20 token, bytes memory data) private {
        bytes memory returndata = address(token).functionCall(data, "SafeERC20: low-level call failed");
        if (returndata.length > 0) {
            require(abi.decode(returndata, (bool)), "SafeERC20: ERC20 operation did not succeed");
        }
    }
}

abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }
    function _msgData() internal view virtual returns (bytes calldata) {
        return msg.data;
    }
}

abstract contract Ownable is Context {
    address private _owner;
    
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    
    constructor(address initialOwner) {
        _transferOwnership(initialOwner);
    }
    
    modifier onlyOwner() {
        _checkOwner();
        _;
    }
    
    function owner() public view virtual returns (address) {
        return _owner;
    }
    
    function _checkOwner() internal view virtual {
        require(owner() == _msgSender(), "Ownable: caller is not the owner");
    }
    
    function renounceOwnership() public virtual onlyOwner {
        _transferOwnership(address(0));
    }
    
    function transferOwnership(address newOwner) public virtual onlyOwner {
        require(newOwner != address(0), "Ownable: new owner is the zero address");
        _transferOwnership(newOwner);
    }
    
    function _transferOwnership(address newOwner) internal virtual {
        address oldOwner = _owner;
        _owner = newOwner;
        emit OwnershipTransferred(oldOwner, newOwner);
    }
}

abstract contract ReentrancyGuard {
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;
    uint256 private _status;
    
    constructor() {
        _status = _NOT_ENTERED;
    }
    
    modifier nonReentrant() {
        require(_status != _ENTERED, "ReentrancyGuard: reentrant call");
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }
}

abstract contract Pausable is Context {
    event Paused(address account);
    event Unpaused(address account);
    
    bool private _paused;
    
    constructor() {
        _paused = false;
    }
    
    modifier whenNotPaused() {
        _requireNotPaused();
        _;
    }
    
    modifier whenPaused() {
        _requirePaused();
        _;
    }
    
    function paused() public view virtual returns (bool) {
        return _paused;
    }
    
    function _requireNotPaused() internal view virtual {
        require(!paused(), "Pausable: paused");
    }
    
    function _requirePaused() internal view virtual {
        require(paused(), "Pausable: not paused");
    }
    
    function _pause() internal virtual whenNotPaused {
        _paused = true;
        emit Paused(_msgSender());
    }
    
    function _unpause() internal virtual whenPaused {
        _paused = false;
        emit Unpaused(_msgSender());
    }
}

contract LearnAndEarnRewards is Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    IERC20 public immutable goodDollarToken;
    
    uint256 public totalDeposited;
    uint256 public totalDisbursed;
    uint256 public totalWithdrawn;
    
    uint256 public maxDisbursementAmount;
    uint256 public minDisbursementAmount;
    
    mapping(address => uint256) public userTotalRewards;
    mapping(address => uint256) public userRewardCount;
    mapping(bytes32 => bool) public processedRewards;
    
    event Deposited(address indexed from, uint256 amount, uint256 timestamp);
    event RewardDisbursed(address indexed recipient, uint256 amount, string quizId, bytes32 rewardId, uint256 timestamp);
    event Withdrawn(address indexed to, uint256 amount, uint256 timestamp);
    event MaxDisbursementUpdated(uint256 oldAmount, uint256 newAmount);
    event MinDisbursementUpdated(uint256 oldAmount, uint256 newAmount);
    event EmergencyWithdraw(address indexed to, uint256 amount, uint256 timestamp);

    constructor(
        address _goodDollarToken,
        uint256 _maxDisbursementAmount,
        uint256 _minDisbursementAmount
    ) Ownable(msg.sender) {
        require(_goodDollarToken != address(0), "Invalid token address");
        require(_maxDisbursementAmount > _minDisbursementAmount, "Max must be > min");
        
        goodDollarToken = IERC20(_goodDollarToken);
        maxDisbursementAmount = _maxDisbursementAmount;
        minDisbursementAmount = _minDisbursementAmount;
    }

    function deposit(uint256 amount) external nonReentrant whenNotPaused {
        require(amount > 0, "Amount must be > 0");
        
        goodDollarToken.safeTransferFrom(msg.sender, address(this), amount);
        totalDeposited += amount;
        
        emit Deposited(msg.sender, amount, block.timestamp);
    }

    function depositFrom(address from, uint256 amount) external onlyOwner nonReentrant whenNotPaused {
        require(amount > 0, "Amount must be > 0");
        require(from != address(0), "Invalid from address");
        
        goodDollarToken.safeTransferFrom(from, address(this), amount);
        totalDeposited += amount;
        
        emit Deposited(from, amount, block.timestamp);
    }

    function disburseReward(
        address recipient,
        uint256 amount,
        string calldata quizId
    ) external onlyOwner nonReentrant whenNotPaused returns (bytes32) {
        require(recipient != address(0), "Invalid recipient");
        require(amount >= minDisbursementAmount, "Amount below minimum");
        require(amount <= maxDisbursementAmount, "Amount exceeds maximum");
        
        bytes32 rewardId = keccak256(abi.encodePacked(recipient, quizId));
        require(!processedRewards[rewardId], "Reward already processed for this quiz");
        
        uint256 balance = goodDollarToken.balanceOf(address(this));
        require(balance >= amount, "Insufficient contract balance");
        
        processedRewards[rewardId] = true;
        userTotalRewards[recipient] += amount;
        userRewardCount[recipient] += 1;
        totalDisbursed += amount;
        
        goodDollarToken.safeTransfer(recipient, amount);
        
        emit RewardDisbursed(recipient, amount, quizId, rewardId, block.timestamp);
        
        return rewardId;
    }

    function batchDisburseRewards(
        address[] calldata recipients,
        uint256[] calldata amounts,
        string[] calldata quizIds
    ) external onlyOwner nonReentrant whenNotPaused returns (bytes32[] memory) {
        require(recipients.length == amounts.length, "Arrays length mismatch");
        require(recipients.length == quizIds.length, "Arrays length mismatch");
        require(recipients.length <= 50, "Batch too large");
        
        uint256 totalAmount = 0;
        for (uint256 i = 0; i < amounts.length; i++) {
            totalAmount += amounts[i];
        }
        
        uint256 balance = goodDollarToken.balanceOf(address(this));
        require(balance >= totalAmount, "Insufficient contract balance");
        
        bytes32[] memory rewardIds = new bytes32[](recipients.length);
        
        for (uint256 i = 0; i < recipients.length; i++) {
            require(recipients[i] != address(0), "Invalid recipient");
            require(amounts[i] >= minDisbursementAmount, "Amount below minimum");
            require(amounts[i] <= maxDisbursementAmount, "Amount exceeds maximum");
            
            bytes32 rewardId = keccak256(abi.encodePacked(recipients[i], quizIds[i]));
            require(!processedRewards[rewardId], "Reward already processed for this quiz");
            
            processedRewards[rewardId] = true;
            userTotalRewards[recipients[i]] += amounts[i];
            userRewardCount[recipients[i]] += 1;
            totalDisbursed += amounts[i];
            
            goodDollarToken.safeTransfer(recipients[i], amounts[i]);
            
            rewardIds[i] = rewardId;
            
            emit RewardDisbursed(recipients[i], amounts[i], quizIds[i], rewardId, block.timestamp);
        }
        
        return rewardIds;
    }

    function withdraw(uint256 amount) external onlyOwner nonReentrant {
        require(amount > 0, "Amount must be > 0");
        
        uint256 balance = goodDollarToken.balanceOf(address(this));
        require(balance >= amount, "Insufficient balance");
        
        totalWithdrawn += amount;
        goodDollarToken.safeTransfer(owner(), amount);
        
        emit Withdrawn(owner(), amount, block.timestamp);
    }

    function withdrawAll() external onlyOwner nonReentrant {
        uint256 balance = goodDollarToken.balanceOf(address(this));
        require(balance > 0, "No balance to withdraw");
        
        totalWithdrawn += balance;
        goodDollarToken.safeTransfer(owner(), balance);
        
        emit Withdrawn(owner(), balance, block.timestamp);
    }

    function emergencyWithdraw(address token) external onlyOwner nonReentrant {
        IERC20 tokenContract = IERC20(token);
        uint256 balance = tokenContract.balanceOf(address(this));
        require(balance > 0, "No balance");
        
        tokenContract.safeTransfer(owner(), balance);
        
        emit EmergencyWithdraw(owner(), balance, block.timestamp);
    }

    function setMaxDisbursementAmount(uint256 newMax) external onlyOwner {
        require(newMax > minDisbursementAmount, "Max must be > min");
        
        uint256 oldMax = maxDisbursementAmount;
        maxDisbursementAmount = newMax;
        
        emit MaxDisbursementUpdated(oldMax, newMax);
    }

    function setMinDisbursementAmount(uint256 newMin) external onlyOwner {
        require(newMin < maxDisbursementAmount, "Min must be < max");
        
        uint256 oldMin = minDisbursementAmount;
        minDisbursementAmount = newMin;
        
        emit MinDisbursementUpdated(oldMin, newMin);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function getContractBalance() external view returns (uint256) {
        return goodDollarToken.balanceOf(address(this));
    }

    function getUserStats(address user) external view returns (
        uint256 totalRewards,
        uint256 rewardCount
    ) {
        return (userTotalRewards[user], userRewardCount[user]);
    }

    function getContractStats() external view returns (
        uint256 balance,
        uint256 deposited,
        uint256 disbursed,
        uint256 withdrawn
    ) {
        return (
            goodDollarToken.balanceOf(address(this)),
            totalDeposited,
            totalDisbursed,
            totalWithdrawn
        );
    }

    function isRewardProcessed(bytes32 rewardId) external view returns (bool) {
        return processedRewards[rewardId];
    }

    function isQuizRewardClaimed(address recipient, string calldata quizId) external view returns (bool) {
        bytes32 rewardId = keccak256(abi.encodePacked(recipient, quizId));
        return processedRewards[rewardId];
    }

    function getRewardId(address recipient, string calldata quizId) external pure returns (bytes32) {
        return keccak256(abi.encodePacked(recipient, quizId));
    }
}"""


def compile_contract():
    """Compile the Solidity contract"""
    logger.info("Installing Solidity compiler v0.8.21...")
    install_solc('0.8.21')
    
    logger.info("Compiling LearnAndEarnRewards contract...")
    
    compiled = compile_standard({
        "language": "Solidity",
        "sources": {
            "LearnAndEarnRewards.sol": {"content": FLATTENED_SOURCE}
        },
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {
                "*": {
                    "*": ["abi", "metadata", "evm.bytecode", "evm.deployedBytecode"]
                }
            }
        }
    }, solc_version='0.8.21')
    
    contract_data = compiled["contracts"]["LearnAndEarnRewards.sol"]["LearnAndEarnRewards"]
    
    return {
        "abi": contract_data["abi"],
        "bytecode": contract_data["evm"]["bytecode"]["object"]
    }


def deploy_contract():
    """Deploy the contract to Celo network"""
    learn_wallet_key = os.getenv('LEARN_WALLET_PRIVATE_KEY')
    
    if not learn_wallet_key:
        logger.error("LEARN_WALLET_PRIVATE_KEY not set!")
        return None
    
    w3 = Web3(Web3.HTTPProvider(CELO_RPC_URL))
    
    if not w3.is_connected():
        logger.error("Failed to connect to Celo network")
        return None
    
    logger.info(f"Connected to Celo network (Chain ID: {CHAIN_ID})")
    
    if learn_wallet_key.startswith('0x'):
        account = Account.from_key(learn_wallet_key)
    else:
        account = Account.from_key('0x' + learn_wallet_key)
    
    logger.info(f"Deploying from: {account.address}")
    
    celo_balance = w3.eth.get_balance(account.address)
    logger.info(f"CELO balance: {w3.from_wei(celo_balance, 'ether')} CELO")
    
    if celo_balance < w3.to_wei(0.1, 'ether'):
        logger.error("Insufficient CELO for gas fees")
        return None
    
    compiled = compile_contract()
    
    contract = w3.eth.contract(
        abi=compiled["abi"],
        bytecode=compiled["bytecode"]
    )
    
    logger.info("Building deployment transaction...")
    
    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = int(w3.eth.gas_price * 1.2)
    
    constructor_txn = contract.constructor(
        Web3.to_checksum_address(GOODDOLLAR_CONTRACT),
        MAX_DISBURSEMENT,
        MIN_DISBURSEMENT
    ).build_transaction({
        'chainId': CHAIN_ID,
        'gas': 3000000,
        'gasPrice': gas_price,
        'nonce': nonce,
    })
    
    logger.info("Signing transaction...")
    signed_txn = w3.eth.account.sign_transaction(constructor_txn, learn_wallet_key)
    
    logger.info("Sending deployment transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    tx_hash_hex = tx_hash.hex()
    
    if not tx_hash_hex.startswith('0x'):
        tx_hash_hex = '0x' + tx_hash_hex
    
    logger.info(f"Transaction hash: {tx_hash_hex}")
    logger.info(f"Explorer: https://celoscan.io/tx/{tx_hash_hex}")
    
    logger.info("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    
    if receipt.status == 1:
        contract_address = receipt.contractAddress
        logger.info(f"Contract deployed successfully!")
        logger.info(f"Contract address: {contract_address}")
        logger.info(f"Explorer: https://celoscan.io/address/{contract_address}")
        logger.info(f"Gas used: {receipt.gasUsed}")
        logger.info(f"Block: {receipt.blockNumber}")
        
        deployment_info = {
            "contract_address": contract_address,
            "tx_hash": tx_hash_hex,
            "owner": account.address,
            "gooddollar_token": GOODDOLLAR_CONTRACT,
            "max_disbursement": str(MAX_DISBURSEMENT),
            "min_disbursement": str(MIN_DISBURSEMENT),
            "chain_id": CHAIN_ID,
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "compiler_version": "v0.8.21+commit.d9974bed",
            "optimization": True,
            "optimization_runs": 200,
            "source_code": FLATTENED_SOURCE,
            "abi": compiled["abi"]
        }
        
        output_path = os.path.join(os.path.dirname(__file__), 'deployment_info.json')
        with open(output_path, 'w') as f:
            json.dump(deployment_info, f, indent=2)
        
        logger.info(f"Deployment info saved to: {output_path}")
        
        return deployment_info
    else:
        logger.error(f"Deployment failed!")
        logger.error(f"Transaction: https://celoscan.io/tx/{tx_hash_hex}")
        logger.error(f"Gas used: {receipt.gasUsed}")
        return None


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Learn & Earn Rewards Contract Deployment")
    logger.info("=" * 60)
    logger.info(f"Network: Celo Mainnet (Chain ID: {CHAIN_ID})")
    logger.info(f"GoodDollar Token: {GOODDOLLAR_CONTRACT}")
    logger.info(f"Max Disbursement: {MAX_DISBURSEMENT / 10**18} G$")
    logger.info(f"Min Disbursement: {MIN_DISBURSEMENT / 10**18} G$")
    logger.info("Compiler: v0.8.21, Optimization: Yes, Runs: 200")
    logger.info("=" * 60)
    
    result = deploy_contract()
    
    if result:
        logger.info("\n" + "=" * 60)
        logger.info("DEPLOYMENT SUCCESSFUL!")
        logger.info("=" * 60)
        logger.info(f"\nContract Address: {result['contract_address']}")
        logger.info(f"\nSet environment variable:")
        logger.info(f"LEARN_EARN_CONTRACT_ADDRESS={result['contract_address']}")
        logger.info("\nVerification Settings:")
        logger.info("- Compiler: v0.8.19+commit.7dd6d404")
        logger.info("- Optimization: Yes")
        logger.info("- Runs: 200")
        logger.info("- License: MIT")
    else:
        logger.error("\nDeployment failed.")
