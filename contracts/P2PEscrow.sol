// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/**
 * @title P2PEscrow
 * @notice Peer-to-peer G$ trading escrow for GoodMarket.
 *
 *  Roles:
 *    - Seller : locks G$ into a listing ("Available ad"), receives fiat/crypto OFF-CHAIN.
 *    - Buyer  : reserves part of a listing (an order), pays the seller off-chain,
 *               then receives the escrowed G$ when the seller (or owner) releases.
 *    - Owner  : the P2P_KEY wallet = deployer = arbiter. Only used for the
 *               admin-review path (seller rejected the proof) and dispute
 *               resolution. Never signs normal user actions.
 *
 *  All normal fund-moving actions are USER-SIGNED:
 *    Seller: createListing / topUpListing / releaseOrder (Approve) / cancelListing / withdrawAvailable
 *    Buyer : openOrder / markPaid / cancelOrder
 *
 *  Off-chain (Supabase): price, payment methods, chat, proof of payment, disputes.
 *  On-chain (this contract): custody of locked G$, listing/order accounting, events.
 *
 *  Invariant: listing.total == G$ held by this contract for the listing
 *             == listing.available + sum(amount of its non-terminal orders).
 *
 *  Lock range per listing: MIN_LOCK (1,000 G$) .. MAX_LOCK (1,000,000 G$).
 *  Per-order minimum is set by the seller (>= MIN_LOCK).
 */

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

contract P2PEscrow {
    // ── Roles ────────────────────────────────────────────────────────────────
    address public owner;       // P2P_KEY: deployer == arbiter
    IERC20  public gdToken;     // GoodDollar (G$) on Celo, 18 decimals

    // ── Limits ───────────────────────────────────────────────────────────────
    uint256 public constant MIN_LOCK = 1_000 * 1e18;
    uint256 public constant MAX_LOCK = 1_000_000 * 1e18;
    uint256 public paymentWindow;          // seconds a buyer has to pay (default 30 min)

    // ── State ────────────────────────────────────────────────────────────────
    enum Status { None, Open, Paid, Released, Cancelled, Disputed }

    struct Listing {
        address seller;
        uint256 total;        // G$ currently held for this listing
        uint256 available;    // G$ not reserved by any open order
        uint256 minOrder;     // seller-chosen per-order minimum (>= MIN_LOCK)
        bool    active;
    }

    struct Order {
        uint256 listingId;
        address buyer;
        uint256 amount;       // G$ reserved for this order
        uint64  createdAt;
        uint64  deadline;     // createdAt + paymentWindow
        Status  status;
    }

    mapping(uint256 => Listing) public listings;
    mapping(uint256 => Order)   public orders;
    uint256 public nextListingId = 1;
    uint256 public nextOrderId = 1;

    // ── Re-entrancy guard ──────────────────────────────────────────────────────
    uint256 private _locked = 1;
    modifier nonReentrant() {
        require(_locked == 1, "Reentrancy");
        _locked = 2;
        _;
        _locked = 1;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "P2PEscrow: not owner");
        _;
    }

    // ── Events ───────────────────────────────────────────────────────────────
    event ListingCreated(uint256 indexed listingId, address indexed seller, uint256 amount, uint256 minOrder);
    event ListingToppedUp(uint256 indexed listingId, address indexed seller, uint256 amount, uint256 newTotal);
    event ListingCancelled(uint256 indexed listingId, address indexed seller, uint256 refunded);
    event AvailableWithdrawn(uint256 indexed listingId, address indexed seller, uint256 amount);
    event MinOrderUpdated(uint256 indexed listingId, uint256 minOrder);

    event OrderOpened(uint256 indexed orderId, uint256 indexed listingId, address indexed buyer, uint256 amount, uint64 deadline);
    event OrderMarkedPaid(uint256 indexed orderId, address indexed buyer);
    event OrderReleased(uint256 indexed orderId, uint256 indexed listingId, address indexed buyer, uint256 amount, address releasedBy);
    event OrderCancelled(uint256 indexed orderId, uint256 indexed listingId, uint256 amount, address cancelledBy);
    event OrderDisputed(uint256 indexed orderId, address indexed raisedBy);
    event DisputeResolved(uint256 indexed orderId, bool releasedToBuyer, address resolvedBy);

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event PaymentWindowUpdated(uint256 paymentWindow);

    /**
     * @param _gdToken         G$ ERC-20 token address on Celo.
     * @param _paymentWindow   Seconds a buyer has to pay (0 => default 1800 = 30 min).
     */
    constructor(address _gdToken, uint256 _paymentWindow) {
        require(_gdToken != address(0), "G$ cannot be zero address");
        owner = msg.sender;
        gdToken = IERC20(_gdToken);
        paymentWindow = _paymentWindow == 0 ? 1800 : _paymentWindow;
    }

    // ───────────────────────────────────── Seller actions (user-signed) ────────

    /**
     * @notice Lock G$ into a new sell listing. Seller must approve() this
     *         contract for `amount` first.
     */
    function createListing(uint256 amount, uint256 minOrder) external nonReentrant returns (uint256 listingId) {
        require(amount >= MIN_LOCK && amount <= MAX_LOCK, "amount out of [MIN_LOCK, MAX_LOCK]");
        require(minOrder >= MIN_LOCK && minOrder <= amount, "minOrder must be >= MIN_LOCK and <= amount");

        listingId = nextListingId++;
        listings[listingId] = Listing({
            seller: msg.sender,
            total: amount,
            available: amount,
            minOrder: minOrder,
            active: true
        });

        bool ok = gdToken.transferFrom(msg.sender, address(this), amount);
        require(ok, "G$ transferFrom failed");

        emit ListingCreated(listingId, msg.sender, amount, minOrder);
    }

    /**
     * @notice Add more G$ to an existing active listing (respecting MAX_LOCK).
     */
    function topUpListing(uint256 listingId, uint256 amount) external nonReentrant {
        Listing storage l = listings[listingId];
        require(l.active, "listing not active");
        require(l.seller == msg.sender, "not seller");
        require(amount > 0, "amount must be positive");
        require(l.total + amount <= MAX_LOCK, "exceeds MAX_LOCK");

        l.total += amount;
        l.available += amount;

        bool ok = gdToken.transferFrom(msg.sender, address(this), amount);
        require(ok, "G$ transferFrom failed");

        emit ListingToppedUp(listingId, msg.sender, amount, l.total);
    }

    /**
     * @notice Update the per-order minimum (must stay >= MIN_LOCK).
     */
    function setMinOrder(uint256 listingId, uint256 minOrder) external {
        Listing storage l = listings[listingId];
        require(l.active, "listing not active");
        require(l.seller == msg.sender, "not seller");
        require(minOrder >= MIN_LOCK && minOrder <= l.total, "invalid minOrder");
        l.minOrder = minOrder;
        emit MinOrderUpdated(listingId, minOrder);
    }

    /**
     * @notice Withdraw part of the unreserved (available) G$ back to the seller.
     */
    function withdrawAvailable(uint256 listingId, uint256 amount) external nonReentrant {
        Listing storage l = listings[listingId];
        require(l.seller == msg.sender, "not seller");
        require(amount > 0 && amount <= l.available, "amount exceeds available");

        l.available -= amount;
        l.total -= amount;

        bool ok = gdToken.transfer(msg.sender, amount);
        require(ok, "G$ transfer failed");

        emit AvailableWithdrawn(listingId, msg.sender, amount);
    }

    /**
     * @notice Deactivate a listing and refund all unreserved G$ to the seller.
     *         G$ reserved by still-open orders stays escrowed until those
     *         orders are released or refunded.
     */
    function cancelListing(uint256 listingId) external nonReentrant {
        Listing storage l = listings[listingId];
        require(l.active, "listing not active");
        require(l.seller == msg.sender, "not seller");

        uint256 refund = l.available;
        l.available = 0;
        l.total -= refund;
        l.active = false;

        if (refund > 0) {
            bool ok = gdToken.transfer(msg.sender, refund);
            require(ok, "G$ transfer failed");
        }

        emit ListingCancelled(listingId, msg.sender, refund);
    }

    // ───────────────────────────────────── Buyer actions (user-signed) ─────────

    /**
     * @notice Reserve `amount` G$ from a listing for an order, starting the
     *         off-chain payment window.
     */
    function openOrder(uint256 listingId, uint256 amount) external nonReentrant returns (uint256 orderId) {
        Listing storage l = listings[listingId];
        require(l.active, "listing not active");
        require(msg.sender != l.seller, "buyer == seller");
        require(amount >= l.minOrder, "amount < minOrder");
        require(amount <= l.available, "amount > available");

        l.available -= amount;

        orderId = nextOrderId++;
        uint64 nowTs = uint64(block.timestamp);
        orders[orderId] = Order({
            listingId: listingId,
            buyer: msg.sender,
            amount: amount,
            createdAt: nowTs,
            deadline: nowTs + uint64(paymentWindow),
            status: Status.Open
        });

        emit OrderOpened(orderId, listingId, msg.sender, amount, nowTs + uint64(paymentWindow));
    }

    /**
     * @notice Buyer signals they have paid off-chain (proof lives in Supabase).
     */
    function markPaid(uint256 orderId) external {
        Order storage o = orders[orderId];
        require(o.buyer == msg.sender, "not buyer");
        require(o.status == Status.Open, "order not open");
        o.status = Status.Paid;
        emit OrderMarkedPaid(orderId, msg.sender);
    }

    /**
     * @notice Cancel an order and return the reserved G$ to the listing.
     *         - Buyer may cancel their own order while it is Open (not yet Paid).
     *         - Anyone may cancel an Open order once its deadline has passed
     *           (auto-expiry) — the buyer never paid.
     */
    function cancelOrder(uint256 orderId) external nonReentrant {
        Order storage o = orders[orderId];
        require(o.status == Status.Open, "order not cancellable");

        bool byBuyer = msg.sender == o.buyer;
        bool expired = block.timestamp > o.deadline;
        require(byBuyer || expired, "only buyer before deadline, or anyone after");

        o.status = Status.Cancelled;
        _returnToSeller(o.listingId, o.amount);

        emit OrderCancelled(orderId, o.listingId, o.amount, msg.sender);
    }

    // ───────────────────────────────────── Settlement ──────────────────────────

    /**
     * @notice Seller "Approve": release the escrowed G$ to the buyer.
     *         Allowed while the order is Open or Paid.
     */
    function releaseOrder(uint256 orderId) external nonReentrant {
        Order storage o = orders[orderId];
        Listing storage l = listings[o.listingId];
        require(msg.sender == l.seller, "not seller");
        _release(orderId, msg.sender);
    }

    /**
     * @notice Owner (P2P_KEY) admin-review release — used when the seller
     *         rejected the proof but the owner verified it is genuine.
     */
    function releaseOrderByOwner(uint256 orderId) external onlyOwner nonReentrant {
        _release(orderId, msg.sender);
    }

    /**
     * @notice Owner (P2P_KEY) admin-review refund — used when the proof is fake.
     *         Reserved G$ is returned to the seller.
     */
    function refundOrderByOwner(uint256 orderId) external onlyOwner nonReentrant {
        Order storage o = orders[orderId];
        require(
            o.status == Status.Open || o.status == Status.Paid || o.status == Status.Disputed,
            "order not refundable"
        );
        o.status = Status.Cancelled;
        _returnToSeller(o.listingId, o.amount);
        emit OrderCancelled(orderId, o.listingId, o.amount, msg.sender);
    }

    // ───────────────────────────────────── Disputes ────────────────────────────

    /**
     * @notice Buyer or seller flags an order for owner review (freezes auto-expiry).
     */
    function raiseDispute(uint256 orderId) external {
        Order storage o = orders[orderId];
        Listing storage l = listings[o.listingId];
        require(msg.sender == o.buyer || msg.sender == l.seller, "not a party");
        require(o.status == Status.Open || o.status == Status.Paid, "cannot dispute");
        o.status = Status.Disputed;
        emit OrderDisputed(orderId, msg.sender);
    }

    /**
     * @notice Owner (P2P_KEY) resolves a dispute after off-chain review.
     * @param releaseToBuyer true => release G$ to buyer; false => refund seller.
     */
    function resolveDispute(uint256 orderId, bool releaseToBuyer) external onlyOwner nonReentrant {
        Order storage o = orders[orderId];
        require(o.status == Status.Disputed, "order not disputed");

        if (releaseToBuyer) {
            o.status = Status.Released;
            Listing storage l = listings[o.listingId];
            l.total -= o.amount;
            bool ok = gdToken.transfer(o.buyer, o.amount);
            require(ok, "G$ transfer failed");
            emit OrderReleased(orderId, o.listingId, o.buyer, o.amount, msg.sender);
        } else {
            o.status = Status.Cancelled;
            _returnToSeller(o.listingId, o.amount);
            emit OrderCancelled(orderId, o.listingId, o.amount, msg.sender);
        }
        emit DisputeResolved(orderId, releaseToBuyer, msg.sender);
    }

    // ───────────────────────────────────── Internal ────────────────────────────

    function _release(uint256 orderId, address releasedBy) internal {
        Order storage o = orders[orderId];
        require(o.status == Status.Open || o.status == Status.Paid, "order not releasable");

        Listing storage l = listings[o.listingId];
        o.status = Status.Released;
        l.total -= o.amount;

        bool ok = gdToken.transfer(o.buyer, o.amount);
        require(ok, "G$ transfer failed");

        emit OrderReleased(orderId, o.listingId, o.buyer, o.amount, releasedBy);
    }

    /**
     * @dev Return `amount` G$ to the seller of `listingId`. If the listing is
     *      still active the G$ rejoins its available pool (stays in escrow,
     *      withdrawable any time); otherwise it is transferred out directly.
     */
    function _returnToSeller(uint256 listingId, uint256 amount) internal {
        Listing storage l = listings[listingId];
        if (l.active) {
            l.available += amount;
        } else {
            l.total -= amount;
            bool ok = gdToken.transfer(l.seller, amount);
            require(ok, "G$ transfer failed");
        }
    }

    // ───────────────────────────────────── Views ───────────────────────────────

    function getListing(uint256 listingId) external view returns (
        address seller, uint256 total, uint256 available, uint256 minOrder, bool active
    ) {
        Listing storage l = listings[listingId];
        return (l.seller, l.total, l.available, l.minOrder, l.active);
    }

    function getOrder(uint256 orderId) external view returns (
        uint256 listingId, address buyer, uint256 amount, uint64 createdAt, uint64 deadline, Status status
    ) {
        Order storage o = orders[orderId];
        return (o.listingId, o.buyer, o.amount, o.createdAt, o.deadline, o.status);
    }

    // ───────────────────────────────────── Owner admin ─────────────────────────

    function setPaymentWindow(uint256 _paymentWindow) external onlyOwner {
        require(_paymentWindow >= 300 && _paymentWindow <= 86400, "window out of [5min, 24h]");
        paymentWindow = _paymentWindow;
        emit PaymentWindowUpdated(_paymentWindow);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "new owner cannot be zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
