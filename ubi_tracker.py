

#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime, timezone
from blockchain import has_recent_ubi_claim, GOODDOLLAR_CONTRACTS
from analytics_service import analytics


class UBITracker:
    """
    Comprehensive UBI tracking system for GoodDollar ecosystem
    """
    
    def __init__(self):
        self.contracts_checked = len(GOODDOLLAR_CONTRACTS)
        self.session_data = {}
        self.results_cache = {}
    
    def track_wallet(self, wallet_address: str, track_analytics: bool = True) -> dict:
        """
        Track UBI activity for a specific wallet address
        
        Args:
            wallet_address: Ethereum wallet address (0x...)
            track_analytics: Whether to track analytics data
            
        Returns:
            Dict containing comprehensive UBI tracking results
        """
        print(f"🔍 Starting comprehensive UBI tracking for: {wallet_address}")
        print(f"📊 Analyzing {self.contracts_checked} GoodDollar contracts")
        print("=" * 60)
        
        # Validate wallet format
        if not self._validate_wallet(wallet_address):
            return {
                "status": "error",
                "message": "❌ Invalid wallet address format",
                "wallet": wallet_address
            }
        
        # Track analytics if enabled
        if track_analytics:
            analytics.track_page_view(wallet_address, "ubi_tracking_started")
        
        # Perform comprehensive blockchain analysis
        result = has_recent_ubi_claim(wallet_address)
        
        # Process and enhance results
        enhanced_result = self._enhance_results(result, wallet_address)
        
        # Track final analytics
        if track_analytics:
            if enhanced_result["status"] == "success":
                analytics.track_verification_attempt(wallet_address, True)
                analytics.track_user_session(wallet_address)
            else:
                analytics.track_verification_attempt(wallet_address, False)
        
        # Cache results
        self.results_cache[wallet_address] = {
            "result": enhanced_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contracts_checked": self.contracts_checked
        }
        
        return enhanced_result
    
    def _validate_wallet(self, wallet: str) -> bool:
        """Validate Ethereum/Celo wallet address format"""
        is_valid_format = (
            isinstance(wallet, str) and 
            len(wallet) == 42 and 
            wallet.startswith("0x") and
            all(c in "0123456789abcdefABCDEF" for c in wallet[2:])
        )
        
        if is_valid_format:
            print(f"🔍 DEBUG: Wallet format valid - checking Celo network activity")
            print(f"🌐 Network: Celo Mainnet (Chain ID: 42220)")
            print(f"🔗 RPC: https://forno.celo.org")
            print(f"💡 Note: GoodDollar operates on Celo, not Ethereum mainnet")
        
        return is_valid_format
    
    def _enhance_results(self, result: dict, wallet: str) -> dict:
        """Enhance blockchain results with additional metadata"""
        enhanced = result.copy()
        
        enhanced["wallet_address"] = wallet
        enhanced["tracking_timestamp"] = datetime.now(timezone.utc).isoformat()
        enhanced["contracts_analyzed"] = list(GOODDOLLAR_CONTRACTS.keys())
        enhanced["ecosystem_coverage"] = f"{len(GOODDOLLAR_CONTRACTS)} contracts"
        
        if result["status"] == "success":
            # Add ecosystem insights
            activities = result.get("activities", [])
            summary = result.get("summary", {})
            
            enhanced["ecosystem_analysis"] = {
                "total_contracts_with_activity": len(set(a["contract_address"] for a in activities)),
                "activity_timespan": self._calculate_timespan(activities),
                "contract_diversity": self._analyze_contract_diversity(activities),
                "transaction_frequency": self._calculate_frequency(activities)
            }
            
            # Add verification badges
            enhanced["verification_badges"] = self._generate_badges(activities, summary)
        
        return enhanced
    
    def _calculate_timespan(self, activities: list) -> dict:
        """Calculate activity timespan"""
        if not activities:
            return {"days": 0, "description": "No activity"}
        
        blocks = [a["block"] for a in activities if "block" in a]
        if not blocks:
            return {"days": 0, "description": "No block data"}
        
        # Rough estimate: Celo ~5 second blocks = 17,280 blocks per day
        block_range = max(blocks) - min(blocks)
        days = max(1, block_range // 17280)
        
        return {
            "days": days,
            "block_range": block_range,
            "description": f"Activity over {days} days"
        }
    
    def _analyze_contract_diversity(self, activities: list) -> dict:
        """Analyze diversity of contracts involved"""
        contracts = set()
        contract_types = {
            "ubi": 0, "staking": 0, "governance": 0, 
            "bridge": 0, "token": 0, "other": 0
        }
        
        for activity in activities:
            contract_name = activity.get("contract", "").lower()
            contracts.add(activity.get("contract_address", ""))
            
            if "ubi" in contract_name:
                contract_types["ubi"] += 1
            elif "stak" in contract_name:
                contract_types["staking"] += 1
            elif "govern" in contract_name:
                contract_types["governance"] += 1
            elif "bridge" in contract_name:
                contract_types["bridge"] += 1
            elif "token" in contract_name:
                contract_types["token"] += 1
            else:
                contract_types["other"] += 1
        
        return {
            "unique_contracts": len(contracts),
            "activity_distribution": contract_types,
            "diversity_score": min(100, len(contracts) * 10)
        }
    
    def _calculate_frequency(self, activities: list) -> dict:
        """Calculate transaction frequency"""
        if len(activities) <= 1:
            return {"frequency": "single", "description": "One-time activity"}
        
        # Group by day (roughly)
        daily_activity = {}
        for activity in activities:
            block = activity.get("block", 0)
            day = block // 17280  # Rough day grouping
            daily_activity[day] = daily_activity.get(day, 0) + 1
        
        avg_per_day = len(activities) / max(1, len(daily_activity))
        
        if avg_per_day >= 3:
            freq_type = "high"
        elif avg_per_day >= 1:
            freq_type = "regular"
        else:
            freq_type = "occasional"
        
        return {
            "frequency": freq_type,
            "average_per_day": round(avg_per_day, 2),
            "active_days": len(daily_activity),
            "description": f"{freq_type} activity ({avg_per_day:.1f} tx/day)"
        }
    
    def _generate_badges(self, activities: list, summary: dict) -> list:
        """Generate verification badges based on activity"""
        badges = []
        
        # Basic verification
        badges.append({
            "name": "UBI Verified",
            "icon": "✅",
            "description": "Recent UBI activity confirmed"
        })
        
        # Activity volume badges
        if len(activities) >= 10:
            badges.append({
                "name": "Super Active",
                "icon": "🔥",
                "description": f"{len(activities)} activities found"
            })
        elif len(activities) >= 5:
            badges.append({
                "name": "Active User",
                "icon": "⚡",
                "description": f"{len(activities)} activities found"
            })
        
        # Contract diversity badge
        unique_contracts = len(set(a["contract_address"] for a in activities))
        if unique_contracts >= 5:
            badges.append({
                "name": "Ecosystem Explorer",
                "icon": "🌟",
                "description": f"Used {unique_contracts} different contracts"
            })
        
        # Recent activity badge
        latest = summary.get("latest_activity", {})
        if latest.get("block", 0) > 0:
            badges.append({
                "name": "Recently Active",
                "icon": "🕐",
                "description": "Recent blockchain activity"
            })
        
        return badges
    
    def generate_report(self, wallet_address: str) -> str:
        """Generate a comprehensive text report"""
        if wallet_address not in self.results_cache:
            result = self.track_wallet(wallet_address)
        else:
            result = self.results_cache[wallet_address]["result"]
        
        report = []
        report.append("=" * 60)
        report.append("🎯 GOODDOLLAR UBI TRACKING REPORT")
        report.append("=" * 60)
        report.append(f"📍 Wallet: {wallet_address}")
        report.append(f"🕐 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        report.append(f"🔍 Contracts Analyzed: {self.contracts_checked}")
        report.append("")
        
        if result["status"] == "success":
            report.append("✅ UBI VERIFICATION SUCCESSFUL!")
            report.append("")
            
            # Summary stats
            summary = result.get("summary", {})
            ecosystem = result.get("ecosystem_analysis", {})
            
            report.append("📊 ACTIVITY SUMMARY:")
            report.append(f"   • Total Activities: {summary.get('total_activities', 0)}")
            report.append(f"   • Transfers: {summary.get('transfers', 0)}")
            report.append(f"   • Events: {summary.get('events', 0)}")
            report.append(f"   • Contracts Involved: {ecosystem.get('total_contracts_with_activity', 0)}")
            report.append("")
            
            # Latest activity
            latest = summary.get("latest_activity", {})
            if latest:
                report.append("🕐 MOST RECENT ACTIVITY:")
                report.append(f"   • Contract: {latest.get('contract', 'Unknown')}")
                report.append(f"   • Amount: {latest.get('amount', 'N/A')}")
                report.append(f"   • Block: #{latest.get('block', 'N/A')}")
                report.append(f"   • Timestamp: {latest.get('timestamp', 'N/A')}")
                report.append("")
            
            # Badges
            badges = result.get("verification_badges", [])
            if badges:
                report.append("🏆 VERIFICATION BADGES:")
                for badge in badges:
                    report.append(f"   {badge['icon']} {badge['name']}: {badge['description']}")
                report.append("")
            
            # Contract breakdown
            activities = result.get("activities", [])
            if activities:
                report.append("📋 CONTRACT ACTIVITY BREAKDOWN:")
                contract_counts = {}
                for activity in activities:
                    contract = activity.get("contract", "Unknown")
                    contract_counts[contract] = contract_counts.get(contract, 0) + 1
                
                for contract, count in sorted(contract_counts.items(), key=lambda x: x[1], reverse=True):
                    report.append(f"   • {contract}: {count} activities")
                report.append("")
        
        else:
            report.append("❌ NO UBI ACTIVITY FOUND")
            report.append("")
            report.append("💡 RECOMMENDATIONS:")
            report.append("   1. Claim your daily UBI from GoodDollar app")
            report.append("   2. Participate in GoodDollar staking")
            report.append("   3. Use GoodMarket for transactions")
            report.append("   4. Try again after claiming UBI")
            report.append("")
        
        report.append("🔗 GOODDOLLAR ECOSYSTEM CONTRACTS CHECKED:")
        for i, (name, address) in enumerate(GOODDOLLAR_CONTRACTS.items(), 1):
            report.append(f"   {i:2d}. {name}: {address[:10]}...")
        
        report.append("")
        report.append("=" * 60)
        report.append("🌐 Powered by Celo blockchain & GoodDollar ecosystem")
        report.append("=" * 60)
        
        return "\n".join(report)
    
    def export_json(self, wallet_address: str, filename: str = None) -> str:
        """Export tracking results to JSON file"""
        if wallet_address not in self.results_cache:
            result = self.track_wallet(wallet_address)
        else:
            result = self.results_cache[wallet_address]["result"]
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ubi_tracking_{wallet_address[-8:]}_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        return filename


def main():
    """Command line interface for UBI tracking"""
    parser = argparse.ArgumentParser(
        description="GoodDollar UBI Tracking Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ubi_tracker.py --wallet 0x742d35Cc6634C0532925a3b8D7389Fa63B1F5a6f
  python ubi_tracker.py --wallet 0x742d35... --export --report
  python ubi_tracker.py --wallet 0x742d35... --no-analytics
        """
    )
    
    parser.add_argument(
        "--wallet", "-w",
        required=True,
        help="Ethereum wallet address to track (0x...)"
    )
    
    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="Generate detailed text report"
    )
    
    parser.add_argument(
        "--export", "-e",
        action="store_true",
        help="Export results to JSON file"
    )
    
    parser.add_argument(
        "--no-analytics",
        action="store_true",
        help="Disable analytics tracking"
    )
    
    parser.add_argument(
        "--output", "-o",
        help="Output filename for export"
    )
    
    args = parser.parse_args()
    
    # Initialize tracker
    tracker = UBITracker()
    
    # Track wallet
    track_analytics = not args.no_analytics
    result = tracker.track_wallet(args.wallet, track_analytics)
    
    # Display basic result
    print("\n" + "="*60)
    if result["status"] == "success":
        print("✅ UBI TRACKING SUCCESSFUL!")
        summary = result.get("summary", {})
        print(f"   📊 Activities found: {summary.get('total_activities', 0)}")
        print(f"   🏢 Contracts involved: {summary.get('contracts_involved', 0)}")
        
        latest = summary.get("latest_activity", {})
        if latest:
            print(f"   🕐 Latest: {latest.get('amount', 'N/A')} from {latest.get('contract', 'Unknown')}")
    else:
        print("❌ NO UBI ACTIVITY FOUND")
        print("   💡 Try claiming UBI first from GoodDollar app")
    
    # Generate report if requested
    if args.report:
        print("\n" + tracker.generate_report(args.wallet))
    
    # Export to JSON if requested
    if args.export:
        filename = tracker.export_json(args.wallet, args.output)
        print(f"\n📁 Results exported to: {filename}")
    
    print("="*60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
