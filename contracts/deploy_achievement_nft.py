"""
Achievement NFT Contract Deployment Script for Celo Network

Deploys ERC-721 Achievement NFT with marketplace operator support.
Owner: LEARN_EARN_CONTRACT_ADDRESS wallet (LEARN_WALLET_PRIVATE_KEY)
App pays all gas - users never need CELO for gas fees.
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

NFT_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

contract AchievementNFT {
    string public name = "GoodMarket Achievement";
    string public symbol = "GMA";

    address public owner;
    address public marketplaceOperator;
    uint256 public totalSupply;

    struct TokenData {
        address tokenOwner;
        string quizId;
        uint8 score;
        uint8 total;
        string quizName;
        uint256 mintedAt;
        string tokenURI;
    }

    mapping(uint256 => TokenData) private _tokens;
    mapping(address => uint256[]) private _ownerTokens;
    mapping(uint256 => uint256) private _ownerTokenIndex;
    mapping(uint256 => address) private _tokenApprovals;
    mapping(address => mapping(address => bool)) private _operatorApprovals;

    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed tokenOwner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed tokenOwner, address indexed operator, bool approved);
    event NFTMinted(address indexed to, uint256 indexed tokenId, string quizId, uint8 score, uint8 total, string quizName);
    event NFTTransferred(address indexed from, address indexed to, uint256 indexed tokenId);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyMinter() {
        require(msg.sender == owner || msg.sender == marketplaceOperator, "Not authorized");
        _;
    }

    constructor(address _marketplaceOperator) {
        owner = msg.sender;
        marketplaceOperator = _marketplaceOperator;
    }

    function supportsInterface(bytes4 interfaceId) public pure returns (bool) {
        return interfaceId == 0x80ac58cd ||
               interfaceId == 0x5b5e139f ||
               interfaceId == 0x01ffc9a7;
    }

    function balanceOf(address _owner) public view returns (uint256) {
        require(_owner != address(0), "Zero address");
        return _ownerTokens[_owner].length;
    }

    function ownerOf(uint256 tokenId) public view returns (address) {
        address tokenOwner = _tokens[tokenId].tokenOwner;
        require(tokenOwner != address(0), "Token does not exist");
        return tokenOwner;
    }

    function tokenURI(uint256 tokenId) public view returns (string memory) {
        require(_tokens[tokenId].tokenOwner != address(0), "Token does not exist");
        return _tokens[tokenId].tokenURI;
    }

    function isApprovedForAll(address _owner, address operator) public view returns (bool) {
        if (operator == marketplaceOperator) return true;
        if (operator == owner) return true;
        return _operatorApprovals[_owner][operator];
    }

    function getApproved(uint256 tokenId) public view returns (address) {
        require(_tokens[tokenId].tokenOwner != address(0), "Token does not exist");
        return _tokenApprovals[tokenId];
    }

    function approve(address to, uint256 tokenId) public {
        address tokenOwner = ownerOf(tokenId);
        require(msg.sender == tokenOwner || isApprovedForAll(tokenOwner, msg.sender), "Not authorized");
        _tokenApprovals[tokenId] = to;
        emit Approval(tokenOwner, to, tokenId);
    }

    function setApprovalForAll(address operator, bool approved) public {
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function _isApprovedOrOwner(address spender, uint256 tokenId) internal view returns (bool) {
        address tokenOwner = ownerOf(tokenId);
        return (spender == tokenOwner ||
                getApproved(tokenId) == spender ||
                isApprovedForAll(tokenOwner, spender));
    }

    function _transfer(address from, address to, uint256 tokenId) internal {
        require(_tokens[tokenId].tokenOwner == from, "Owner mismatch");
        require(to != address(0), "Cannot transfer to zero address");

        delete _tokenApprovals[tokenId];

        uint256[] storage fromTokens = _ownerTokens[from];
        uint256 idx = _ownerTokenIndex[tokenId];
        uint256 lastIdx = fromTokens.length - 1;
        if (idx != lastIdx) {
            uint256 lastTokenId = fromTokens[lastIdx];
            fromTokens[idx] = lastTokenId;
            _ownerTokenIndex[lastTokenId] = idx;
        }
        fromTokens.pop();

        _ownerTokenIndex[tokenId] = _ownerTokens[to].length;
        _ownerTokens[to].push(tokenId);
        _tokens[tokenId].tokenOwner = to;

        emit Transfer(from, to, tokenId);
        emit NFTTransferred(from, to, tokenId);
    }

    function transferFrom(address from, address to, uint256 tokenId) public {
        require(_isApprovedOrOwner(msg.sender, tokenId), "Not authorized");
        _transfer(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId) public {
        transferFrom(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId, bytes memory) public {
        transferFrom(from, to, tokenId);
    }

    function mint(
        address to,
        string memory quizId,
        uint8 score,
        uint8 total,
        string memory quizName,
        string memory _tokenURI
    ) public onlyMinter returns (uint256) {
        require(to != address(0), "Cannot mint to zero address");

        totalSupply++;
        uint256 tokenId = totalSupply;

        _tokens[tokenId] = TokenData({
            tokenOwner: to,
            quizId: quizId,
            score: score,
            total: total,
            quizName: quizName,
            mintedAt: block.timestamp,
            tokenURI: _tokenURI
        });

        _ownerTokenIndex[tokenId] = _ownerTokens[to].length;
        _ownerTokens[to].push(tokenId);

        emit Transfer(address(0), to, tokenId);
        emit NFTMinted(to, tokenId, quizId, score, total, quizName);

        return tokenId;
    }

    function transferByOperator(address from, address to, uint256 tokenId) public {
        require(msg.sender == marketplaceOperator || msg.sender == owner, "Not operator");
        require(to != address(0), "Cannot transfer to zero address");
        _transfer(from, to, tokenId);
    }

    function getTokenData(uint256 tokenId) public view returns (
        address tokenOwner,
        string memory quizId,
        uint8 score,
        uint8 total,
        string memory quizName,
        uint256 mintedAt,
        string memory uri
    ) {
        TokenData memory t = _tokens[tokenId];
        require(t.tokenOwner != address(0), "Token does not exist");
        return (t.tokenOwner, t.quizId, t.score, t.total, t.quizName, t.mintedAt, t.tokenURI);
    }

    function getOwnerTokens(address _owner) public view returns (uint256[] memory) {
        return _ownerTokens[_owner];
    }

    function setMarketplaceOperator(address newOperator) public onlyOwner {
        marketplaceOperator = newOperator;
    }

    function setTokenURI(uint256 tokenId, string memory _tokenURI) public onlyOwner {
        require(_tokens[tokenId].tokenOwner != address(0), "Token does not exist");
        _tokens[tokenId].tokenURI = _tokenURI;
    }
}
"""


def compile_contract():
    logger.info("Installing Solidity compiler v0.8.21...")
    install_solc('0.8.21')

    logger.info("Compiling AchievementNFT contract...")

    compiled = compile_standard({
        "language": "Solidity",
        "sources": {
            "AchievementNFT.sol": {"content": NFT_SOURCE}
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

    contract_data = compiled["contracts"]["AchievementNFT.sol"]["AchievementNFT"]

    return {
        "abi": contract_data["abi"],
        "bytecode": contract_data["evm"]["bytecode"]["object"]
    }


def deploy_contract():
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

    if celo_balance < w3.to_wei(0.01, 'ether'):
        logger.error("Insufficient CELO for gas fees (need at least 0.01 CELO)")
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
        account.address
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
            "contract_name": "AchievementNFT",
            "contract_address": contract_address,
            "tx_hash": tx_hash_hex,
            "owner": account.address,
            "marketplace_operator": account.address,
            "chain_id": CHAIN_ID,
            "network": "Celo Mainnet",
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "compiler_version": "v0.8.21+commit.d9974bed",
            "optimization": True,
            "optimization_runs": 200,
            "source_code": NFT_SOURCE,
            "abi": compiled["abi"]
        }

        output_path = os.path.join(os.path.dirname(__file__), 'achievement_nft_deployment.json')
        with open(output_path, 'w') as f:
            json.dump(deployment_info, f, indent=2)

        logger.info(f"Deployment info saved to: {output_path}")

        return deployment_info
    else:
        logger.error("Deployment failed!")
        logger.error(f"Transaction: https://celoscan.io/tx/{tx_hash_hex}")
        return None


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Achievement NFT Contract Deployment")
    logger.info("=" * 60)
    logger.info(f"Network: Celo Mainnet (Chain ID: {CHAIN_ID})")
    logger.info("Contract: AchievementNFT (ERC-721)")
    logger.info("=" * 60)

    result = deploy_contract()

    if result:
        logger.info("\n" + "=" * 60)
        logger.info("DEPLOYMENT SUCCESSFUL!")
        logger.info("=" * 60)
        logger.info(f"\nContract Address: {result['contract_address']}")
        logger.info(f"\nSet this environment variable/secret:")
        logger.info(f"ACHIEVEMENT_NFT_CONTRACT_ADDRESS={result['contract_address']}")
    else:
        logger.error("\nDeployment failed.")
