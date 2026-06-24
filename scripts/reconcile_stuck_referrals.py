#!/usr/bin/env python3
"""
Standalone script to reconcile stuck referrals.

Usage:
    python scripts/reconcile_stuck_referrals.py
    
    # With custom hours threshold:
    python scripts/reconcile_stuck_referrals.py --hours 24

Cron job setup (run every hour):
    0 * * * * cd /path/to/project && python scripts/reconcile_stuck_referrals.py >> /var/log/referral_reconcile.log 2>&1
"""

import os
import sys
import argparse
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Reconcile stuck referral disbursements')
    parser.add_argument('--hours', type=int, default=1, 
                        help='Only process referrals stuck for more than X hours (default: 1)')
    args = parser.parse_args()

    logger.info(f"🔄 Starting referral reconciliation (threshold: {args.hours} hours)")
    
    try:
        from referral_program.referral_service import referral_service
        
        result = referral_service.reconcile_stuck_referrals(older_than_hours=args.hours)
        
        logger.info(f"📊 Reconciliation complete:")
        logger.info(f"   - Total checked: {result.get('total_checked', 0)}")
        logger.info(f"   - Fixed: {result.get('fixed', 0)}")
        logger.info(f"   - Still stuck: {result.get('still_stuck', 0)}")
        logger.info(f"   - Errors: {result.get('errors', 0)}")
        
        if result.get('fixed', 0) > 0:
            logger.info(f"✅ Successfully fixed {result.get('fixed')} stuck referrals!")
        if result.get('still_stuck', 0) > 0:
            logger.warning(f"⚠️ {result.get('still_stuck')} referrals still stuck - may need manual intervention")
            
    except Exception as e:
        logger.error(f"❌ Reconciliation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
