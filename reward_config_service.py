
import logging
from typing import Dict, Any, Optional
from supabase_client import get_supabase_client, safe_supabase_operation
from datetime import datetime

logger = logging.getLogger(__name__)

class RewardConfigService:
    """Service for managing reward configuration"""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        self._cache = {}
        self._cache_time = {}
        self.cache_duration = 60  # Cache for 60 seconds
        
        logger.info("💰 Reward Configuration Service initialized")
    
    def get_reward_amount(self, task_type: str) -> float:
        """Get reward amount for a specific task type with caching"""
        try:
            # Check cache first
            import time
            cache_key = f"reward_{task_type}"
            if cache_key in self._cache:
                if time.time() - self._cache_time.get(cache_key, 0) < self.cache_duration:
                    return self._cache[cache_key]
            
            if not self.supabase:
                logger.warning(f"⚠️ Supabase not available, using default 100.0 G$ for {task_type}")
                return 100.0
            
            result = safe_supabase_operation(
                lambda: self.supabase.table('reward_configuration')
                    .select('reward_amount')
                    .eq('task_type', task_type)
                    .single()
                    .execute(),
                fallback_result=None,
                operation_name=f"get reward for {task_type}"
            )
            
            if result and result.data:
                reward = float(result.data.get('reward_amount', 100.0))
                
                # Update cache
                self._cache[cache_key] = reward
                self._cache_time[cache_key] = time.time()
                
                return reward
            else:
                logger.warning(f"⚠️ No reward config found for {task_type}, using default 100.0 G$")
                return 100.0
                
        except Exception as e:
            logger.error(f"❌ Error getting reward amount for {task_type}: {e}")
            return 100.0
    
    def update_reward_amount(self, task_type: str, new_amount: float, admin_wallet: str) -> Dict[str, Any]:
        """Update reward amount for a task type"""
        try:
            if not self.supabase:
                return {"success": False, "error": "Database not available"}
            
            if new_amount < 10 or new_amount > 10000:
                return {"success": False, "error": "Reward amount must be between 10 and 10,000 G$"}
            
            # Update database
            result = safe_supabase_operation(
                lambda: self.supabase.table('reward_configuration')
                    .update({
                        'reward_amount': new_amount,
                        'last_updated_by': admin_wallet,
                        'last_updated_at': datetime.utcnow().isoformat()
                    })
                    .eq('task_type', task_type)
                    .execute(),
                fallback_result=None,
                operation_name=f"update reward for {task_type}"
            )
            
            if result and result.data:
                # Clear cache
                cache_key = f"reward_{task_type}"
                if cache_key in self._cache:
                    del self._cache[cache_key]
                if cache_key in self._cache_time:
                    del self._cache_time[cache_key]
                
                logger.info(f"✅ Updated {task_type} reward to {new_amount} G$ by admin {admin_wallet[:8]}...")
                
                return {
                    "success": True,
                    "task_type": task_type,
                    "new_amount": new_amount,
                    "message": f"Reward updated to {new_amount} G$"
                }
            else:
                return {"success": False, "error": "Failed to update reward configuration"}
                
        except Exception as e:
            logger.error(f"❌ Error updating reward amount: {e}")
            return {"success": False, "error": str(e)}
    
    def get_all_rewards(self) -> Dict[str, Any]:
        """Get all reward configurations"""
        try:
            if not self.supabase:
                return {
                    "success": True,
                    "rewards": {
                        "telegram_task": 100.0,
                        "twitter_task": 100.0,
                        "facebook_task": 100.0
                    }
                }
            
            result = safe_supabase_operation(
                lambda: self.supabase.table('reward_configuration')
                    .select('*')
                    .execute(),
                fallback_result=None,
                operation_name="get all rewards"
            )
            
            if result and result.data:
                rewards = {}
                for config in result.data:
                    rewards[config['task_type']] = {
                        'amount': float(config['reward_amount']),
                        'last_updated_by': config.get('last_updated_by'),
                        'last_updated_at': config.get('last_updated_at')
                    }
                
                return {"success": True, "rewards": rewards}
            else:
                return {"success": False, "error": "No reward configurations found"}
                
        except Exception as e:
            logger.error(f"❌ Error getting all rewards: {e}")
            return {"success": False, "error": str(e)}

# Global instance
reward_config_service = RewardConfigService()
