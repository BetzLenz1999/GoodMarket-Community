// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/**
 * @title EscrowMarketplace
 * @notice Handles listing, buying, and cancellation of GoodMarket NFTs in one contract.
 *         The app operator wallet manages all state on behalf of users (gasless UX).
 *
 *  On-chain listing state:
 *    - listNFT(tokenId, seller, priceG)   — app wallet registers a seller's listing
 *    - cancelListing(tokenId)             — app wallet removes a listing (delist)
 *    - completeSwap(tokenId, buyer)       — app wallet atomically:
 *         1. transferFrom(buyer, seller, priceG)        — G$ payment
 *         2. transferByOperator(seller, buyer, tokenId) — NFT transfer
 *
 *  Atomicity guarantee:
 *    completeSwap is a single transaction.  Either both G$ payment and NFT transfer
 *    succeed, or the entire transaction reverts — no partial state is ever possible.
 *
 *  Setup (one-time after deployment):
 *    1. AchievementNFT.setMarketplaceOperator(escrowContractAddress)
 *    2. Set ESCROW_MARKETPLACE_ADDRESS env var to the deployed address
 *
 *  User flows:
 *    List  : user clicks List → app calls listNFT()  (app pays gas)
 *    Delist: user clicks Delist → app calls cancelListing() (app pays gas)
 *    Buy   : user signs approve(escrow, price) tx → app calls completeSwap() (app pays gas)
 */

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

interface IAchievementNFT {
    function transferByOperator(address from, address to, uint256 tokenId) external;
    function ownerOf(uint256 tokenId) external view returns (address);
}

contract EscrowMarketplace {
    address public owner;
    address public nftContract;
    address public gdToken;

    struct Listing {
        address seller;
        uint256 priceG;
        bool    active;
    }

    mapping(uint256 => Listing) public listings;

    event NFTListed(
        uint256 indexed tokenId,
        address indexed seller,
        uint256 priceG
    );

    event ListingCancelled(
        uint256 indexed tokenId,
        address indexed seller
    );

    event SwapCompleted(
        uint256 indexed tokenId,
        address indexed buyer,
        address indexed seller,
        uint256 priceG
    );

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        require(msg.sender == owner, "EscrowMarketplace: caller is not owner");
        _;
    }

    /**
     * @param _nftContract  Address of the deployed AchievementNFT contract
     * @param _gdToken      Address of the G$ ERC-20 token on Celo
     */
    constructor(address _nftContract, address _gdToken) {
        require(_nftContract != address(0), "NFT contract cannot be zero address");
        require(_gdToken != address(0), "G$ contract cannot be zero address");
        owner = msg.sender;
        nftContract = _nftContract;
        gdToken = _gdToken;
    }

    /**
     * @notice Register an NFT listing on-chain.
     *         Called by the app operator after the seller confirms via the UI.
     *         App pays all gas — seller pays nothing.
     *
     * @param tokenId   NFT token ID being listed
     * @param seller    Address of the current NFT owner (seller)
     * @param priceG    Listing price in G$ base units (wei, 18 decimals)
     */
    function listNFT(
        uint256 tokenId,
        address seller,
        uint256 priceG
    ) external onlyOwner {
        require(seller != address(0), "Invalid seller address");
        require(priceG > 0, "Price must be positive");

        address currentOwner = IAchievementNFT(nftContract).ownerOf(tokenId);
        require(currentOwner == seller, "Seller does not own this NFT");

        listings[tokenId] = Listing({seller: seller, priceG: priceG, active: true});

        emit NFTListed(tokenId, seller, priceG);
    }

    /**
     * @notice Cancel (delist) an active NFT listing.
     *         Called by the app operator when the seller requests delisting.
     *         App pays all gas — seller pays nothing.
     *
     * @param tokenId   NFT token ID to delist
     */
    function cancelListing(uint256 tokenId) external onlyOwner {
        Listing storage listing = listings[tokenId];
        require(listing.active, "No active listing for this token");

        address seller = listing.seller;
        listing.active = false;

        emit ListingCancelled(tokenId, seller);
    }

    /**
     * @notice Atomically swap an NFT for G$.
     *         Reads price and seller from the on-chain listing.
     *
     *   Prerequisites:
     *     - Caller is the owner (app wallet)
     *     - An active listing exists for tokenId
     *     - seller still owns the NFT on-chain
     *     - buyer has approved this contract for >= listing.priceG
     *
     * @param tokenId   NFT token ID being purchased
     * @param buyer     Address purchasing the NFT
     */
    function completeSwap(
        uint256 tokenId,
        address buyer
    ) external onlyOwner {
        Listing storage listing = listings[tokenId];
        require(listing.active, "No active listing for this token");
        require(buyer != address(0), "Invalid buyer address");
        require(buyer != listing.seller, "Buyer and seller must be different");

        address seller = listing.seller;
        uint256 priceG = listing.priceG;

        // Verify seller still owns the NFT (guards against off-chain state mismatch)
        address currentOwner = IAchievementNFT(nftContract).ownerOf(tokenId);
        require(currentOwner == seller, "Seller no longer owns NFT");

        // Verify buyer has sufficient G$ allowance for this contract
        uint256 allowance = IERC20(gdToken).allowance(buyer, address(this));
        require(allowance >= priceG, "Insufficient G$ allowance — buyer must approve first");

        // Mark listing inactive before external calls (re-entrancy guard)
        listing.active = false;

        // ── Atomic execution ─────────────────────────────────────────────────
        // Step 1: Transfer G$ from buyer → seller
        bool ok = IERC20(gdToken).transferFrom(buyer, seller, priceG);
        require(ok, "G$ transferFrom failed");

        // Step 2: Transfer NFT from seller → buyer
        IAchievementNFT(nftContract).transferByOperator(seller, buyer, tokenId);
        // ── If either step reverts, the whole transaction reverts ────────────

        emit SwapCompleted(tokenId, buyer, seller, priceG);
    }

    /**
     * @notice Get the active listing for a token ID.
     * @return seller   Seller address (zero if no listing)
     * @return priceG   Price in G$ wei (0 if no listing)
     * @return active   Whether the listing is active
     */
    function getListing(uint256 tokenId) external view returns (
        address seller,
        uint256 priceG,
        bool    active
    ) {
        Listing storage l = listings[tokenId];
        return (l.seller, l.priceG, l.active);
    }

    /**
     * @notice Read the current G$ allowance granted to this escrow contract by a buyer.
     */
    function getAllowance(address buyer) external view returns (uint256) {
        return IERC20(gdToken).allowance(buyer, address(this));
    }

    /**
     * @notice Transfer contract ownership to a new operator wallet.
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "New owner cannot be zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    /**
     * @notice Update NFT or G$ contract addresses (for future migrations).
     */
    function updateContracts(address _nftContract, address _gdToken) external onlyOwner {
        require(_nftContract != address(0) && _gdToken != address(0), "Cannot be zero address");
        nftContract = _nftContract;
        gdToken = _gdToken;
    }
}
