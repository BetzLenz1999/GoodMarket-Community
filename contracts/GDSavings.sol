int256 public depositIdCounter;

    /**
     * @notice Total G$ held in the reward pool (funded by sponsors).
     * @dev    Tracked separately from user deposits. Cannot be withdrawn
     *         by anyone — used exclusively to pay user bonuses.
     */
    uint256 public rewardPool;

    struct Deposit {
        address owner;
        uint256 amount;
        uint256 lockDays;
        uint256 depositedAt;
        uint256 unlocksAt;
        bool    withdrawn;
        bool    bonusClaimed;
    }

    /// @notice depositId => Deposit data
    mapping(uint256 => Deposit) public deposits;
    /// @notice user address => list of their deposit IDs
    mapping(address => uint256[]) public userDepositIds;

    // ── Events ──────────────────────────────────────────────────────────────────
    event Saved(
        address indexed user,
        uint256 indexed depositId,
        uint256 amount,
        uint256 lockDays,
        uint256 unlocksAt
    );
    event Withdrawn(
        address indexed user,
        uint256 indexed depositId,
        uint256 amount,
        uint256 timestamp
    );
    event BonusPaid(
        address indexed user,
        uint256 indexed depositId,
        uint256 bonus,
        uint256 timestamp
    );
    event RewardPoolFunded(
        address indexed sponsor,
        uint256 amount,
        uint256 timestamp
    );

    // ── Constructor ─────────────────────────────────────────────────────────────
    /**
     * @param _gd Address of the G$ ERC-20 token on Celo.
     */
    constructor(address _gd) {
        require(_gd != address(0), "Invalid token address");
        gd = IERC20(_gd);
    }

    // ── Internal helpers ────────────────────────────────────────────────────────

    function _isValidDuration(uint256 days_) internal view returns (bool) {
        for (uint16 i = 0; i < 13; i++) {
            if (VALID_DURATIONS[i] == days_) return true;
        }
        return false;
    }

    /**
     * @dev Returns the bonus amount the deposit qualifies for (0 if none).
     *
     *      Short-term tier (1-day lock):
     *        Any deposit >= 1,000 G$ → 10 G$
     *
     *      Long-term tiers (lock >= 150 days, deposit >= 10,000 G$):
     *        Tier 1 — 10,000 G$  to  99,999 G$ → 1,000 G$
     *        Tier 2 — 100,000 G$ to 499,999 G$ → 2,500 G$
     *        Tier 3 — 500,000 G$ to 10,000,000 G$ → 10,000 G$
     *
     *      Note: Long-term tiers take priority when lockDays >= 150.
     */
    function _bonusForDeposit(uint256 amount, uint256 lockDays) internal pure returns (uint256) {
        // Long-term tiers (highest priority)
        if (lockDays >= BONUS_MIN_DAYS) {
            if (amount >= BONUS_TIER3_MIN) return BONUS_TIER3_AMOUNT;
            if (amount >= BONUS_TIER2_MIN) return BONUS_TIER2_AMOUNT;
            if (amount >= BONUS_TIER1_MIN) return BONUS_TIER1_AMOUNT;
        }
        // Short-term tier: exactly 1-day lock, any deposit >= MIN_DEPOSIT
        if (lockDays == BONUS_SHORT_DAYS && amount >= MIN_DEPOSIT) return BONUS_SHORT_AMOUNT;
        return 0;
    }

    // ── User: Deposit (Save) ────────────────────────────────────────────────────

    /**
     * @notice Lock G$ tokens for a chosen duration.
     * @dev    Caller must approve this contract to spend `amount` G$ first.
     * @param amount   Amount in wei (18 decimals). Must be 1,000 – 10,000,000 G$.
     * @param lockDays One of: 1, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 365
     */
    function depositSavings(uint256 amount, uint256 lockDays) external nonReentrant {
        require(amount >= MIN_DEPOSIT,  "Below minimum deposit (1,000 G$)");
        require(amount <= MAX_DEPOSIT,  "Above maximum deposit (10,000,000 G$)");
        require(_isValidDuration(lockDays), "Invalid lock duration");

        gd.safeTransferFrom(msg.sender, address(this), amount);

        uint256 id = ++depositIdCounter;
        uint256 unlocksAt = block.timestamp + (lockDays * 1 days);

        deposits[id] = Deposit({
            owner:        msg.sender,
            amount:       amount,
            lockDays:     lockDays,
            depositedAt:  block.timestamp,
            unlocksAt:    unlocksAt,
            withdrawn:    false,
            bonusClaimed: false
        });

        userDepositIds[msg.sender].push(id);

        emit Saved(msg.sender, id, amount, lockDays, unlocksAt);
    }

    // ── User: Withdraw ──────────────────────────────────────────────────────────

    /**
     * @notice Withdraw a matured deposit plus any eligible bonus.
     * @dev    Only the original depositor can call this.
     *         If eligible for a bonus AND the reward pool has sufficient funds,
     *         the bonus is automatically included in the payout. Otherwise only
     *         the principal is returned — no partial bonus is ever paid.
     * @param depositId The ID of the deposit to withdraw.
     */
    function withdraw(uint256 depositId) external nonReentrant {
        Deposit storage dep = deposits[depositId];

        require(dep.owner == msg.sender,       "Not your deposit");
        require(!dep.withdrawn,                "Already withdrawn");
        require(block.timestamp >= dep.unlocksAt, "Still locked");

        dep.withdrawn = true;

        uint256 payout = dep.amount;
        bool bonusPaid = false;

        if (!dep.bonusClaimed) {
            uint256 bonusAmount = _bonusForDeposit(dep.amount, dep.lockDays);
            if (bonusAmount > 0 && rewardPool >= bonusAmount) {
                dep.bonusClaimed = true;
                rewardPool -= bonusAmount;
                payout += bonusAmount;
                bonusPaid = true;
            }
        }

        gd.safeTransfer(msg.sender, payout);

        emit Withdrawn(msg.sender, depositId, dep.amount, block.timestamp);
        if (bonusPaid) {
            emit BonusPaid(msg.sender, depositId, payout - dep.amount, block.timestamp);
        }
    }

    // ── Sponsor: Fund Reward Pool ───────────────────────────────────────────────

    /**
     * @notice Fund the reward pool with G$ tokens.
     * @dev    Anyone — sponsors, the community, partners — can call this.
     *         Funds added here can ONLY be used to pay user bonuses.
     *         They can NEVER be withdrawn by any account (trustless).
     * @param amount Amount of G$ to add to the reward pool (in wei, 18 decimals).
     */
    function fundRewardPool(uint256 amount) external nonReentrant {
        require(amount > 0, "Amount must be > 0");
        gd.safeTransferFrom(msg.sender, address(this), amount);
        rewardPool += amount;
        emit RewardPoolFunded(msg.sender, amount, block.timestamp);
    }

    // ── View Functions ──────────────────────────────────────────────────────────

    /**
     * @notice Returns all deposit IDs belonging to `user`.
     */
    function getUserDepositIds(address user) external view returns (uint256[] memory) {
        return userDepositIds[user];
    }

    /**
     * @notice Returns full details of a deposit, plus computed status flags.
     * @return owner_        The address that created the deposit.
     * @return amount        Principal locked (in wei).
     * @return lockDays      Chosen lock duration in days.
     * @return depositedAt   Unix timestamp when deposited.
     * @return unlocksAt     Unix timestamp when withdrawal becomes available.
     * @return withdrawn     True if already withdrawn.
     * @return bonusClaimed  True if the bonus was already paid for this deposit.
     * @return isUnlocked    True if the lock period has expired.
     * @return bonusEligible True if this deposit qualifies for a bonus
     *                       (lockDays >= 150 and amount >= 10,000 G$)
     *                       and it has not been claimed yet.
     * @return pendingBonus  The bonus amount this deposit would receive
     *                       (0 if not eligible or already claimed).
     */
    function getDeposit(uint256 depositId) external view returns (
        address owner_,
        uint256 amount,
        uint256 lockDays,
        uint256 depositedAt,
        uint256 unlocksAt,
        bool    withdrawn,
        bool    bonusClaimed,
        bool    isUnlocked,
        bool    bonusEligible,
        uint256 pendingBonus
    ) {
        Deposit storage d = deposits[depositId];
        uint256 bonus = _bonusForDeposit(d.amount, d.lockDays);
        return (
            d.owner,
            d.amount,
            d.lockDays,
            d.depositedAt,
            d.unlocksAt,
            d.withdrawn,
            d.bonusClaimed,
            block.timestamp >= d.unlocksAt,
            bonus > 0 && !d.bonusClaimed,
            d.bonusClaimed ? 0 : bonus
        );
    }

    /**
     * @notice Returns high-level statistics about the contract.
     * @return totalLocked      Total G$ deposited by users (excluding reward pool).
     * @return rewardPoolBalance G$ available in the reward pool for bonuses.
     * @return contractBalance  Total G$ held by this contract.
     * @return totalDeposits    Number of deposits ever created.
     */
    function getContractStats() external view returns (
        uint256 totalLocked,
        uint256 rewardPoolBalance,
        uint256 contractBalance,
        uint256 totalDeposits
    ) {
        uint256 bal = gd.balanceOf(address(this));
        return (
            bal > rewardPool ? bal - rewardPool : 0,
            rewardPool,
            bal,
            depositIdCounter
        );
    }

    /**
     * @notice Returns the 13 valid lock durations (in days).
     */
    function getValidDurations() external view returns (uint16[13] memory) {
        return VALID_DURATIONS;
    }

    /**
     * @notice Returns the bonus a deposit of `amount` G$ locked for `lockDays`
     *         would earn. Returns 0 if not eligible.
     */
    function getBonusAmount(uint256 amount, uint256 lockDays) external pure returns (uint256) {
        return _bonusForDeposit(amount, lockDays);
    }
}
