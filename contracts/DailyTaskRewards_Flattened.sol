// SPDX-License-Identifier: MIT
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
