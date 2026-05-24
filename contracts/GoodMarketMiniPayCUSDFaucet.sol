// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/**
 * @title GoodMarketMiniPayCUSDFaucet
 * @notice Controlled cUSD faucet router for MiniPay users.
 *
 * Gas fee is always paid by the transaction sender (operator wallet),
 * e.g. TOPWALLET_KEY via backend relayer.
 */
contract GoodMarketMiniPayCUSDFaucet {
    IERC20 public immutable cUSD;
    address public owner;

    mapping(address => bool) public operators;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event OperatorUpdated(address indexed operator, bool allowed);
    event GoodMarketTopWallet(
        address indexed recipient,
        address indexed operator,
        uint256 amount,
        bytes32 indexed correlationId,
        string sourceTag,
        uint256 timestamp
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "not_owner");
        _;
    }

    modifier onlyOperator() {
        require(operators[msg.sender], "not_operator");
        _;
    }

    constructor(address cUSDToken, address initialOperator) {
        require(cUSDToken != address(0), "zero_cusd");
        require(initialOperator != address(0), "zero_operator");

        cUSD = IERC20(cUSDToken);
        owner = msg.sender;
        operators[initialOperator] = true;

        emit OwnershipTransferred(address(0), msg.sender);
        emit OperatorUpdated(initialOperator, true);
    }

    function setOperator(address operator, bool allowed) external onlyOwner {
        require(operator != address(0), "zero_operator");
        operators[operator] = allowed;
        emit OperatorUpdated(operator, allowed);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "zero_owner");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function disburseCUSD(
        address recipient,
        uint256 amount,
        bytes32 correlationId,
        string calldata sourceTag
    ) external onlyOperator returns (bool) {
        require(recipient != address(0), "zero_recipient");
        require(amount > 0, "zero_amount");

        bool ok = cUSD.transfer(recipient, amount);
        require(ok, "cusd_transfer_failed");

        emit GoodMarketTopWallet(
            recipient,
            msg.sender,
            amount,
            correlationId,
            sourceTag,
            block.timestamp
        );
        return true;
    }

    function faucetBalance() external view returns (uint256) {
        return cUSD.balanceOf(address(this));
    }
}
