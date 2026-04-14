// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract DailyTaskRewards is Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    IERC20 public immutable goodDollarToken;

    uint256 public rewardAmount;

    uint256 public totalDeposited;
    uint256 public totalDisbursed;
    uint256 public totalWithdrawn;

    mapping(address => uint256) public userTotalRewards;
    mapping(address => uint256) public userRewardCount;
    mapping(bytes32 => bool) public processedTasks;

    event Deposited(address indexed from, uint256 amount, uint256 timestamp);
    event RewardDisbursed(
        address indexed recipient,
        uint256 amount,
        string taskId,
        string platform,
        bytes32 taskHash,
        uint256 timestamp
    );
    event Withdrawn(address indexed to, uint256 amount, uint256 timestamp);
    event RewardAmountUpdated(uint256 oldAmount, uint256 newAmount);
    event EmergencyWithdraw(address indexed to, uint256 amount, uint256 timestamp);

    constructor(
        address _goodDollarToken,
        uint256 _rewardAmount
    ) Ownable(msg.sender) {
        require(_goodDollarToken != address(0), "Invalid token address");
        require(_rewardAmount > 0, "Reward amount must be > 0");

        goodDollarToken = IERC20(_goodDollarToken);
        rewardAmount = _rewardAmount;
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
        string calldata taskId,
        string calldata platform
    ) external onlyOwner nonReentrant whenNotPaused returns (bytes32) {
        require(recipient != address(0), "Invalid recipient");
        require(bytes(taskId).length > 0, "Invalid task ID");
        require(bytes(platform).length > 0, "Invalid platform");

        bytes32 taskHash = keccak256(abi.encodePacked(recipient, taskId, platform));
        require(!processedTasks[taskHash], "Task reward already disbursed");

        uint256 balance = goodDollarToken.balanceOf(address(this));
        require(balance >= rewardAmount, "Insufficient contract balance");

        processedTasks[taskHash] = true;
        userTotalRewards[recipient] += rewardAmount;
        userRewardCount[recipient] += 1;
        totalDisbursed += rewardAmount;

        goodDollarToken.safeTransfer(recipient, rewardAmount);

        emit RewardDisbursed(recipient, rewardAmount, taskId, platform, taskHash, block.timestamp);

        return taskHash;
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

    function setRewardAmount(uint256 newAmount) external onlyOwner {
        require(newAmount > 0, "Amount must be > 0");

        uint256 oldAmount = rewardAmount;
        rewardAmount = newAmount;

        emit RewardAmountUpdated(oldAmount, newAmount);
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

    function isTaskProcessed(bytes32 taskHash) external view returns (bool) {
        return processedTasks[taskHash];
    }

    function isTaskRewarded(address recipient, string calldata taskId, string calldata platform) external view returns (bool) {
        bytes32 taskHash = keccak256(abi.encodePacked(recipient, taskId, platform));
        return processedTasks[taskHash];
    }

    function getTaskHash(address recipient, string calldata taskId, string calldata platform) external pure returns (bytes32) {
        return keccak256(abi.encodePacked(recipient, taskId, platform));
    }
}
