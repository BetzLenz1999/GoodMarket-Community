// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

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
}
