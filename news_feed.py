import os
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from flask import request, jsonify, session, redirect, render_template
from markupsafe import Markup

# Import real Supabase client
from supabase_client import get_supabase_client, supabase_enabled, safe_supabase_operation, supabase_logger
from analytics_service import analytics


logger = logging.getLogger(__name__)

def make_links_clickable(text):
    """Convert URLs in text to clickable HTML links"""
    if not text:
        return text

    # URL regex pattern
    url_pattern = r'(https?://[^\s<>"]+|www\.[^\s<>"]+)'

    def replace_url(match):
        url = match.group(0)
        # Add https:// to www links
        href = url if url.startswith('http') else f'https://{url}'
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer" style="color: #4facfe; text-decoration: underline; font-weight: 500;">{url}</a>'

    # Replace URLs with clickable links
    processed_text = re.sub(url_pattern, replace_url, text)

    # Convert line breaks to <br> tags
    processed_text = processed_text.replace('\n', '<br>')

    return Markup(processed_text)

class NewsFeedService:
    """
    News Feed Service for GoodDollar Analytics Platform

    Manages news articles, announcements, and community updates
    with Supabase integration for persistent storage.
    """

    def __init__(self):
        self.client = get_supabase_client()
        self.enabled = supabase_enabled and self.client is not None

        # Default news categories
        self.categories = {
            'announcement': '📢 Announcements',
            'update': '🔄 Platform Updates', 
            'community': '👥 Community',
            'blockchain': '⛓️ Blockchain',
            'reward': '💰 Rewards & Bonuses',
            'feature': '✨ New Features',
            'maintenance': '🔧 Maintenance',
            'partnership': '🤝 Partnerships'
        }

        # Initialize sample news if database is empty
        if self.enabled:
            self._initialize_sample_news()

    def _initialize_sample_news(self):
        """Initialize sample news articles if none exist"""
        try:
            # Check if news articles already exist
            existing_news = self.client.table("news_articles")\
                .select("*")\
                .limit(1)\
                .execute()

            if existing_news.data:
                logger.info("📰 News articles already exist in database")
                return

            # Create sample news articles
            sample_news = [
                {
                    "title": "Welcome to GoodDollar Analytics Platform!",
                    "content": "We're excited to launch the new GoodDollar Analytics Platform with enhanced features including Learn & Earn quizzes, mobile top-ups, mobile top-ups via Reloadly, and comprehensive blockchain analytics. Start exploring your UBI journey today!",
                    "category": "announcement",
                    "priority": "high",
                    "author": "GoodDollar Team",
                    "published": True,
                    "featured": True,
                    "image_url": None,
                    "created_at": datetime.now().isoformat()
                },
                {
                    "title": "New Learn & Earn System Now Live",
                    "content": "Take quizzes about GoodDollar and earn up to 2000 G$ per quiz! Each correct answer earns you 200 G$ with a 24-hour cooldown between quizzes. Test your knowledge and grow your G$ balance.",
                    "category": "feature",
                    "priority": "high", 
                    "author": "GIMT Team",
                    "published": True,
                    "featured": True,
                    "image_url": None,
                    "created_at": (datetime.now() - timedelta(hours=2)).isoformat()
                },
                {
                    "title": "12-Hour Bonus System Available",
                    "content": "Claim 50 G$ every 12 hours! The new bonus system rewards active community members with regular G$ distributions. Set a reminder and never miss your bonus claim.",
                    "category": "reward",
                    "priority": "medium",
                    "author": "GoodDollar Team", 
                    "published": True,
                    "featured": False,
                    "image_url": None,
                    "created_at": (datetime.now() - timedelta(hours=6)).isoformat()
                },
                {
                    "title": "Mobile Top-Up Feature Powered by Reloadly",
                    "content": "Use your G$ to top-up mobile credit worldwide! Our integration with Reloadly enables seamless mobile credit purchases using your GoodDollar balance. Available in 150+ countries. Visit: www.reloadly.com",
                    "category": "feature",
                    "priority": "medium",
                    "author": "Platform Development",
                    "published": True,
                    "featured": False,
                    "image_url": None,
                    "created_at": (datetime.now() - timedelta(hours=12)).isoformat()
                },
                {
                    "title": "Enhanced Security with Celo Blockchain",
                    "content": "All transactions are secured by the Celo blockchain network. Your G$ rewards, bonus claims, and mobile top-ups are processed through secure smart contracts with full transparency. Learn more at https://celo.org",
                    "category": "blockchain",
                    "priority": "low",
                    "author": "Security Team",
                    "published": True,
                    "featured": False,
                    "image_url": None,
                    "created_at": (datetime.now() - timedelta(days=1)).isoformat()
                },
                {
                    "title": "Community Milestone: 1000+ Verified Users",
                    "content": "We've reached an amazing milestone of over 1000 verified UBI recipients! Thank you to our growing community for making the GoodDollar ecosystem stronger every day.",
                    "category": "community",
                    "priority": "medium",
                    "author": "Community Team",
                    "published": True,
                    "featured": False,
                    "image_url": None,
                    "created_at": (datetime.now() - timedelta(days=2)).isoformat()
                }
            ]

            # Insert sample news
            result = self.client.table("news_articles").insert(sample_news).execute()
            logger.info(f"✅ Initialized {len(sample_news)} sample news articles")

        except Exception as e:
            logger.error(f"❌ Error initializing sample news: {e}")

    def get_news_feed(self, limit: int = 20, category: Optional[str] = None, 
                     featured_only: bool = False) -> List[Dict]:
        """Get news feed with optional filtering"""
        if not self.enabled:
            return self._get_fallback_news(limit)

        try:
            query = self.client.table("news_articles")\
                .select("*")\
                .eq("published", True)\
                .order("created_at", desc=True)

            if category:
                query = query.eq("category", category)

            if featured_only:
                query = query.eq("featured", True)

            query = query.limit(limit)
            result = query.execute()

            news_articles = result.data or []

            # Format articles for display
            formatted_articles = []
            for article in news_articles:
                image_url = article.get('image_url')
                # Clean up image_url - handle None, 'None' string, empty string, 'null' string
                if image_url and image_url not in ['None', 'null', ''] and image_url.lower() not in ['none', 'null']:
                    has_image = True
                    clean_image_url = image_url
                else:
                    has_image = False
                    clean_image_url = None

                # Get raw content
                raw_content = article.get('content', '')
                
                # Create excerpt (first 200 characters of plain text for better social media previews)
                import re
                # Remove HTML tags for excerpt
                plain_text = re.sub(r'<[^>]+>', '', raw_content).strip()
                # Get first 200 characters
                excerpt = plain_text[:200].strip()
                if len(plain_text) > 200:
                    # Find last complete word
                    last_space = excerpt.rfind(' ')
                    if last_space > 100:  # Only break at word if we have enough content
                        excerpt = excerpt[:last_space]
                    excerpt += '...'
                elif len(plain_text) > 0 and not excerpt.endswith('...'):
                    # Add ellipsis if content was cut
                    pass  # Don't add ellipsis if it's the full content
                
                # Format full content with better spacing (for article detail page)
                content = raw_content
                # Add paragraph breaks for double line breaks
                content = content.replace('\n\n', '</p><p style="margin-top: 1rem;">')
                # Single line breaks become <br> with spacing
                content = content.replace('\n', '<br style="margin-bottom: 0.5rem;">')
                # Wrap in paragraph tags if not already wrapped
                if not content.startswith('<p'):
                    content = f'<p>{content}</p>'

                formatted_article = {
                    **article,
                    'image_url': clean_image_url,  # Override with cleaned URL
                    'content': content,  # Full formatted content
                    'excerpt': excerpt,  # Short preview for feed
                    'category_display': self.categories.get(article.get('category', 'announcement'), '📰 News'),
                    'time_ago': self._format_time_ago(article.get('created_at')),
                    'priority_class': f"priority-{article.get('priority', 'medium')}",
                    'has_image': has_image,
                    'url': article.get('url', ''),  # Keep original URL field
                    'share_url': f"/news/article/{article['id']}" # Add shareable URL
                }
                formatted_articles.append(formatted_article)

                # Log image info for debugging
                if has_image:
                    logger.info(f"📰 Article '{article.get('title', 'Untitled')[:30]}...' has image: {clean_image_url[:50]}...")

            logger.info(f"📰 Retrieved {len(formatted_articles)} news articles ({sum(1 for a in formatted_articles if a['has_image'])} with images)")
            return formatted_articles

        except Exception as e:
            logger.error(f"❌ Error getting news feed: {e}")
            return self._get_fallback_news(limit)

    def get_featured_news(self, limit: int = 3) -> List[Dict]:
        """Get featured news articles"""
        if not self.enabled:
            return self._get_fallback_news(limit)

        try:
            query = self.client.table("news_articles")\
                .select("*")\
                .eq("published", True)\
                .eq("featured", True)\
                .order("created_at", desc=True)\
                .limit(limit)

            result = query.execute()
            news_articles = result.data or []

            featured_processed = []
            for article in news_articles:
                time_ago = self._format_time_ago(article.get('created_at'))
                
                # Create excerpt for featured news
                import re
                raw_content = article.get('content', '')
                plain_text = re.sub(r'<[^>]+>', '', raw_content)
                excerpt = plain_text[:150].strip()
                if len(plain_text) > 150:
                    last_space = excerpt.rfind(' ')
                    if last_space > 100:
                        excerpt = excerpt[:last_space]
                    excerpt += '...'

                featured_processed.append({
                    'id': article['id'],
                    'title': article['title'],
                    'content': article.get('content', ''),
                    'excerpt': excerpt,  # Add excerpt for preview
                    'category': article['category'],
                    'category_display': self.categories.get(article['category'], article['category'].title()),
                    'author': article.get('author', 'GoodDollar Team'),
                    'time_ago': time_ago,
                    'priority': article.get('priority', 'medium'),
                    'priority_class': f"priority-{article.get('priority', 'medium')}",
                    'url': article.get('url'),
                    'image_url': article.get('image_url'),
                    'has_image': bool(article.get('image_url')),
                    'share_url': f"/news/article/{article['id']}" # Add shareable URL
                })

            return featured_processed

        except Exception as e:
            logger.error(f"❌ Error getting featured news: {e}")
            return self._get_fallback_news(limit)

    def get_news_by_category(self, category: str, limit: int = 10) -> List[Dict]:
        """Get news articles by category"""
        return self.get_news_feed(limit=limit, category=category)

    def add_news_article(self, title: str, content: str, category: str = 'announcement',
                        priority: str = 'medium', author: str = 'Admin',
                        featured: bool = False, image_url: Optional[str] = None,
                        url: Optional[str] = None) -> Dict:
        """Add new news article"""
        if not self.enabled:
            logger.warning("⚠️ Supabase not enabled - cannot add news article")
            return {"success": False, "error": "Database not available"}

        try:
            article_data = {
                "title": title,
                "content": content,
                "category": category,
                "priority": priority,
                "author": author,
                "published": True,
                "featured": featured,
                "image_url": image_url,
                "url": url,
                "created_at": datetime.now().isoformat()
            }

            # Don't include 'id' - let the database auto-generate it
            result = safe_supabase_operation(
                lambda: self.client.table("news_articles").insert(article_data).execute(),
                fallback_result=type('obj', (object,), {'data': []})(),
                operation_name="insert news article"
            )

            if result.data:
                logger.info(f"✅ Added news article: {title}")
                return {"success": True, "article": result.data[0]}
            else:
                return {"success": False, "error": "Failed to insert article"}

        except Exception as e:
            logger.error(f"❌ Error adding news article: {e}")
            return {"success": False, "error": str(e)}

    def get_news_stats(self) -> Dict:
        """Get news feed statistics"""
        if not self.enabled or not self.client:
            return {
                "total_articles": 6,
                "featured_articles": 2,
                "categories_count": len(self.categories),
                "recent_articles": 3
            }

        try:
            # Total articles - use simple select and count in Python
            total_result = safe_supabase_operation(
                lambda: self.client.table("news_articles")
                    .select("id")
                    .eq("published", True)
                    .execute(),
                fallback_result=type('obj', (object,), {'data': []})(),
                operation_name="get total articles count"
            )

            # Featured articles
            featured_result = safe_supabase_operation(
                lambda: self.client.table("news_articles")
                    .select("id")
                    .eq("published", True)
                    .eq("featured", True)
                    .execute(),
                fallback_result=type('obj', (object,), {'data': []})(),
                operation_name="get featured articles count"
            )

            # Recent articles (last 24 hours)
            recent_cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
            recent_result = safe_supabase_operation(
                lambda: self.client.table("news_articles")
                    .select("id")
                    .eq("published", True)
                    .gte("created_at", recent_cutoff)
                    .execute(),
                fallback_result=type('obj', (object,), {'data': []})(),
                operation_name="get recent articles count"
            )

            return {
                "total_articles": len(total_result.data) if total_result.data else 0,
                "featured_articles": len(featured_result.data) if featured_result.data else 0,
                "categories_count": len(self.categories),
                "recent_articles": len(recent_result.data) if recent_result.data else 0
            }

        except Exception as e:
            logger.error(f"❌ Error getting news stats: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "total_articles": 0,
                "featured_articles": 0,
                "categories_count": len(self.categories),
                "recent_articles": 0
            }

    def _get_fallback_news(self, limit: int) -> List[Dict]:
        """Fallback news when database is not available"""
        fallback_news = [
            {
                "id": 1,
                "title": "Welcome to GoodDollar Analytics Platform!",
                "content": "Explore your UBI journey with enhanced analytics, Learn & Earn quizzes, and mobile top-ups.",
                "category": "announcement",
                "category_display": "📢 Announcements",
                "priority": "high",
                "priority_class": "priority-high",
                "author": "GoodDollar Team",
                "featured": True,
                "image_url": None,
                "time_ago": "2 hours ago",
                "created_at": (datetime.now() - timedelta(hours=2)).isoformat()
            },
            {
                "id": 2,
                "title": "Learn & Earn System Now Live",
                "content": "Take quizzes and earn up to 2000 G$ per quiz! Test your GoodDollar knowledge.",
                "category": "feature",
                "category_display": "✨ New Features",
                "priority": "high",
                "priority_class": "priority-high",
                "author": "GIMT Team",
                "featured": True,
                "image_url": None,
                "time_ago": "6 hours ago",
                "created_at": (datetime.now() - timedelta(hours=6)).isoformat()
            },
            {
                "id": 3,
                "title": "12-Hour Bonus Available",
                "content": "Claim 50 G$ every 12 hours! Never miss your regular bonus rewards.",
                "category": "reward",
                "category_display": "💰 Rewards & Bonuses",
                "priority": "medium",
                "priority_class": "priority-medium",
                "author": "Platform Team",
                "featured": False,
                "image_url": None,
                "time_ago": "1 day ago",
                "created_at": (datetime.now() - timedelta(days=1)).isoformat()
            }
        ]

        return fallback_news[:limit]

    def _format_time_ago(self, timestamp_str: str) -> str:
        """Format timestamp as time ago string"""
        try:
            # Parse the timestamp - handle various formats
            if not timestamp_str:
                return "Recently"

            # Remove timezone info and parse
            timestamp_clean = timestamp_str.replace('Z', '').split('+')[0].split('T')[0] + ' ' + timestamp_str.replace('Z', '').split('+')[0].split('T')[1] if 'T' in timestamp_str else timestamp_str.replace('Z', '').split('+')[0]

            # Parse to datetime
            if 'T' in timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '').split('+')[0])
            else:
                timestamp = datetime.fromisoformat(timestamp_str)

            # Get current UTC time (timezone-naive)
            now = datetime.utcnow()
            diff = now - timestamp

            if diff.days > 7:
                return timestamp.strftime('%B %d, %Y')
            elif diff.days > 0:
                return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
            elif diff.seconds > 3600:
                hours = diff.seconds // 3600
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
            elif diff.seconds > 60:
                minutes = diff.seconds // 60
                return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            else:
                return "Just now"

        except Exception as e:
            logger.error(f"❌ Error formatting time ago for '{timestamp_str}': {e}")
            return "Recently"

    def get_news_article(self, article_id: str, increment_view: bool = True) -> Optional[Dict]:
        """Get single news article by ID and optionally increment view count (works for ALL visitors including guests)"""
        if not self.enabled:
            return None

        try:
            result = self.client.table("news_articles")\
                .select("*")\
                .eq("id", article_id)\
                .eq("published", True)\
                .execute()

            if result.data and len(result.data) > 0:
                article = result.data[0]

                # Increment view count if requested - WORKS FOR ALL VISITORS (authenticated + guests)
                if increment_view:
                    try:
                        current_views = article.get('view_count', 0)
                        self.client.table("news_articles")\
                            .update({'view_count': current_views + 1})\
                            .eq("id", article_id)\
                            .execute()
                        article['view_count'] = current_views + 1
                        logger.info(f"📊 Article '{article.get('title', 'Untitled')[:30]}...' views: {current_views + 1} (guest or authenticated)")
                    except Exception as view_error:
                        logger.error(f"❌ Error incrementing view count: {view_error}")

                # Clean up image_url
                image_url = article.get('image_url')
                if image_url and image_url not in ['None', 'null', ''] and image_url.lower() not in ['none', 'null']:
                    has_image = True
                    clean_image_url = image_url
                else:
                    has_image = False
                    clean_image_url = None

                # Get raw content
                raw_content = article.get('content', '')
                
                # Create excerpt (first 200 characters of plain text)
                import re
                plain_text = re.sub(r'<[^>]+>', '', raw_content).strip()
                excerpt = plain_text[:200].strip()
                if len(plain_text) > 200:
                    last_space = excerpt.rfind(' ')
                    if last_space > 100:
                        excerpt = excerpt[:last_space]
                    excerpt += '...'

                # Format content with better spacing
                content = raw_content
                # Add paragraph breaks for double line breaks
                content = content.replace('\n\n', '</p><p style="margin-top: 1rem;">')
                # Single line breaks become <br> with spacing
                content = content.replace('\n', '<br style="margin-bottom: 0.5rem;">')
                # Wrap in paragraph tags if not already wrapped
                if not content.startswith('<p'):
                    content = f'<p>{content}</p>'

                formatted_article = {
                    **article,
                    'image_url': clean_image_url,
                    'content': content,
                    'excerpt': excerpt,
                    'category_display': self.categories.get(article.get('category', 'announcement'), '📰 News'),
                    'time_ago': self._format_time_ago(article.get('created_at')),
                    'priority_class': f"priority-{article.get('priority', 'medium')}",
                    'has_image': has_image,
                    'url': article.get('url', ''),  # Keep original URL field
                    'share_url': f"/news/article/{article['id']}", # Add shareable URL
                    'view_count': article.get('view_count', 0)
                }
                return formatted_article

            return None

        except Exception as e:
            logger.error(f"❌ Error getting news article: {e}")
            return None

# Global news feed service instance
news_feed_service = NewsFeedService()

def init_news_feed(app):
    """Initialize news feed routes and service for Flask app"""

    @app.route('/api/news-feed')
    def get_news_feed_api():
        """API endpoint to get news feed"""
        try:
            limit = int(request.args.get('limit', 20))
            category = request.args.get('category')
            featured_only = request.args.get('featured') == 'true'

            news_articles = news_feed_service.get_news_feed(
                limit=limit,
                category=category,
                featured_only=featured_only
            )

            stats = news_feed_service.get_news_stats()

            return jsonify({
                'success': True,
                'news': news_articles,
                'stats': stats,
                'categories': news_feed_service.categories
            })

        except Exception as e:
            logger.error(f"❌ News feed API error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/news')
    def news_feed_page():
        """News feed page"""
        try:
            wallet = session.get("wallet")
            verified = session.get("verified")
            username = None

            # Check if user is authenticated
            if wallet and verified:
                try:
                    # Get username for authenticated users
                    username = supabase_logger.get_username(wallet)
                    # Track news page visit for authenticated users only
                    analytics.track_page_view(wallet, "news_feed")
                except Exception as user_error:
                    logger.error(f"❌ Error getting user info: {user_error}")
                    username = "Guest"

            # Get news feed data for initial page load (available to all users)
            try:
                featured_news = news_feed_service.get_featured_news(limit=3)
            except Exception as featured_error:
                logger.error(f"❌ Error getting featured news: {featured_error}")
                featured_news = []

            try:
                recent_news = news_feed_service.get_news_feed(limit=10)
            except Exception as recent_error:
                logger.error(f"❌ Error getting recent news: {recent_error}")
                recent_news = []

            try:
                news_stats = news_feed_service.get_news_stats()
            except Exception as stats_error:
                logger.error(f"❌ Error getting news stats: {stats_error}")
                news_stats = {
                    "total_articles": 0,
                    "featured_articles": 0,
                    "categories_count": len(news_feed_service.categories),
                    "recent_articles": 0
                }

            return render_template("news_feed.html",
                                 wallet=wallet if wallet and verified else None,
                                 username=username if username else "Guest",
                                 featured_news=featured_news,
                                 recent_news=recent_news,
                                 news_stats=news_stats,
                                 categories=news_feed_service.categories)
        except Exception as e:
            logger.error(f"❌ News page error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return render_template("news_feed.html",
                                 wallet=None,
                                 username="Guest",
                                 featured_news=[],
                                 recent_news=[],
                                 news_stats={
                                     "total_articles": 0,
                                     "featured_articles": 0,
                                     "categories_count": 0,
                                     "recent_articles": 0
                                 },
                                 categories={})

    @app.route('/news/article/<article_id>')
    def news_article_page(article_id: str):
        """Individual news article page"""
        article = news_feed_service.get_news_article(article_id)

        if not article:
            return render_template("404.html"), 404 # Assuming a 404 template exists

        # Prepare meta tags for social media sharing
        meta_tags = {
            "title": article.get('title', 'GoodDollar News'),
            "description": article.get('content', '')[:200], # Truncate description
            "image": article.get('image_url', ''),
            "url": request.url # Current page URL
        }

        # Add any additional session/wallet checks if this page requires authentication
        wallet = session.get("wallet")
        verified = session.get("verified")
        username = None
        if wallet and verified:
            username = supabase_logger.get_username(wallet)
            analytics.track_page_view(wallet, f"news_article_{article_id}")

        return render_template("news_article.html",
                             article=article,
                             meta_tags=meta_tags,
                             wallet=wallet if wallet and verified else None,
                             username=username if username else "Guest")


    logger.info("✅ News feed routes initialized")
    return True
