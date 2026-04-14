// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

// OpenZeppelin Contracts (last updated v4.9.0) (utils/Context.sol)
abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }

    function _msgData() internal view virtual returns (bytes calldata) {
        return msg.data;
    }
}

// OpenZeppelin Contracts (last updated v4.9.0) (access/Ownable.sol)
abstract contract Ownable is Context {
    address private _owner;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    constructor(address initialOwner) {
        require(initialOwner != address(0), "Ownable: new owner is the zero address");
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

// OpenZeppelin Contracts (last updated v4.9.0) (security/ReentrancyGuard.sol)
abstract contract ReentrancyGuard {
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;
    uint256 private _status;

    constructor() {
        _status = _NOT_ENTERED;
    }

    modifier nonReentrant() {
        _nonReentrantBefore();
        _;
        _nonReentrantAfter();
    }

    function _nonReentrantBefore() private {
        require(_status != _ENTERED, "ReentrancyGuard: reentrant call");
        _status = _ENTERED;
    }

    function _nonReentrantAfter() private {
        _status = _NOT_ENTERED;
    }
}

// OpenZeppelin Contracts (last updated v4.9.0) (security/Pausable.sol)
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

// OpenZeppelin Contracts (last updated v4.9.0) (token/ERC20/IERC20.sol)
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

// OpenZeppelin Contracts (last updated v4.9.0) (token/ERC20/extensions/IERC20Permit.sol)
interface IERC20Permit {
    function permit(
        address owner,
        address spender,
        uint256 value,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;
    function nonces(address owner) external view returns (uint256);
    function DOMAIN_SEPARATOR() external view returns (bytes32);
}

// OpenZeppelin Contracts (last updated v4.9.0) (utils/Address.sol)
library Address {
    function isContract(address account) internal view returns (bool) {
        return account.code.length > 0;
    }

    function sendValue(address payable recipient, uint256 amount) internal {
        require(address(this).balance >= amount, "Address: insufficient balance");
        (bool success, ) = recipient.call{value: amount}("");
        require(success, "Address: unable to send value, recipient may have reverted");
    }

    function functionCall(address target, bytes memory data) internal returns (bytes memory) {
        return functionCallWithValue(target, data, 0, "Address: low-level call failed");
    }

    function functionCall(
        address target,
        bytes memory data,
        string memory errorMessage
    ) internal returns (bytes memory) {
        return functionCallWithValue(target, data, 0, errorMessage);
    }

    function functionCallWithValue(address target, bytes memory data, uint256 value) internal returns (bytes memory) {
        return functionCallWithValue(target, data, value, "Address: low-level call with value failed");
    }

    function functionCallWithValue(
        address target,
        bytes memory data,
        uint256 value,
        string memory errorMessage
    ) internal returns (bytes memory) {
        require(address(this).balance >= value, "Address: insufficient balance for call");
        (bool success, bytes memory returndata) = target.call{value: value}(data);
        return verifyCallResultFromTarget(target, success, returndata, errorMessage);
    }

    function functionStaticCall(address target, bytes memory data) internal view returns (bytes memory) {
        return functionStaticCall(target, data, "Address: low-level static call failed");
    }

    function functionStaticCall(
        address target,
        bytes memory data,
        string memory errorMessage
    ) internal view returns (bytes memory) {
        (bool success, bytes memory returndata) = target.staticcall(data);
        return verifyCallResultFromTarget(target, success, returndata, errorMessage);
    }

    function functionDelegateCall(address target, bytes memory data) internal returns (bytes memory) {
        return functionDelegateCall(target, data, "Address: low-level delegate call failed");
    }

    function functionDelegateCall(
        address target,
        bytes memory data,
        string memory errorMessage
    ) internal returns (bytes memory) {
        (bool success, bytes memory returndata) = target.delegatecall(data);
        return verifyCallResultFromTarget(target, success, returndata, errorMessage);
    }

    function verifyCallResultFromTarget(
        address target,
        bool success,
        bytes memory returndata,
        string memory errorMessage
    ) internal view returns (bytes memory) {
        if (success) {
            if (returndata.length == 0) {
                require(isContract(target), "Address: call to non-contract");
            }
            return returndata;
        } else {
            _revert(returndata, errorMessage);
        }
    }

    function verifyCallResult(
        bool success,
        bytes memory returndata,
        string memory errorMessage
    ) internal pure returns (bytes memory) {
        if (success) {
            return returndata;
        } else {
            _revert(returndata, errorMessage);
        }
    }

    function _revert(bytes memory returndata, string memory errorMessage) private pure {
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

// OpenZeppelin Contracts (last updated v4.9.0) (token/ERC20/utils/SafeERC20.sol)
library SafeERC20 {
    using Address for address;

    function safeTransfer(IERC20 token, address to, uint256 value) internal {
        _callOptionalReturn(token, abi.encodeWithSelector(token.transfer.selector, to, value));
    }

    function safeTransferFrom(IERC20 token, address from, address to, uint256 value) internal {
        _callOptionalReturn(token, abi.encodeWithSelector(token.transferFrom.selector, from, to, value));
    }

    function safeApprove(IERC20 token, address spender, uint256 value) internal {
        require(
            (value == 0) || (token.allowance(address(this), spender) == 0),
            "SafeERC20: approve from non-zero to non-zero allowance"
        );
        _callOptionalReturn(token, abi.encodeWithSelector(token.approve.selector, spender, value));
    }

    function safeIncreaseAllowance(IERC20 token, address spender, uint256 value) internal {
        uint256 oldAllowance = token.allowance(address(this), spender);
        _callOptionalReturn(token, abi.encodeWithSelector(token.approve.selector, spender, oldAllowance + value));
    }

    function safeDecreaseAllowance(IERC20 token, address spender, uint256 value) internal {
        unchecked {
            uint256 oldAllowance = token.allowance(address(this), spender);
            require(oldAllowance >= value, "SafeERC20: decreased allowance below zero");
            _callOptionalReturn(token, abi.encodeWithSelector(token.approve.selector, spender, oldAllowance - value));
        }
    }

    function forceApprove(IERC20 token, address spender, uint256 value) internal {
        bytes memory approvalCall = abi.encodeWithSelector(token.approve.selector, spender, value);
        if (!_callOptionalReturnBool(token, approvalCall)) {
            _callOptionalReturn(token, abi.encodeWithSelector(token.approve.selector, spender, 0));
            _callOptionalReturn(token, approvalCall);
        }
    }

    function safePermit(
        IERC20Permit token,
        address owner,
        address spender,
        uint256 value,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) internal {
        uint256 nonceBefore = token.nonces(owner);
        token.permit(owner, spender, value, deadline, v, r, s);
        uint256 nonceAfter = token.nonces(owner);
        require(nonceAfter == nonceBefore + 1, "SafeERC20: permit did not succeed");
    }

    function _callOptionalReturn(IERC20 token, bytes memory data) private {
        bytes memory returndata = address(token).functionCall(data, "SafeERC20: low-level call failed");
        require(returndata.length == 0 || abi.decode(returndata, (bool)), "SafeERC20: ERC20 operation did not succeed");
    }

    function _callOptionalReturnBool(IERC20 token, bytes memory data) private returns (bool) {
        (bool success, bytes memory returndata) = address(token).call(data);
        return
            success && (returndata.length == 0 || abi.decode(returndata, (bool))) && Address.isContract(address(token));
    }
}

// LearnAndEarnRewards Contract
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
