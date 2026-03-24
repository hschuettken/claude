"""
Ghost CMS Admin API Client.
Handles authentication, post creation, publishing, and updates.
"""
import os
import time
import jwt
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)


class GhostAdminAPIClient:
    """
    Ghost Admin API client for creating and managing posts.
    
    Requires environment variables:
      - GHOST_ADMIN_API_KEY: format "id:secret_hex" from Ghost Admin panel
      - GHOST_URL: base URL (e.g., https://layer8.schuettken.net)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        ghost_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize Ghost API client.
        
        Args:
            api_key: Admin API key (env GHOST_ADMIN_API_KEY if not provided)
            ghost_url: Ghost base URL (env GHOST_URL if not provided)
            timeout: HTTP timeout in seconds
        """
        self.admin_api_key = api_key or os.getenv("GHOST_ADMIN_API_KEY", "")
        self.ghost_url = ghost_url or os.getenv("GHOST_URL", "https://layer8.schuettken.net")
        self.ghost_url = self.ghost_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(base_url=self.ghost_url, timeout=timeout)
        
        if not self.admin_api_key:
            raise ValueError("GHOST_ADMIN_API_KEY env var not set (format: id:secret)")
        
        try:
            self.key_id, self.key_secret = self.admin_api_key.split(":", 1)
        except ValueError:
            raise ValueError("GHOST_ADMIN_API_KEY must be in format 'id:secret_hex'")
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.close()
    
    def _generate_jwt(self) -> str:
        """Generate JWT token for Ghost Admin API authentication."""
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 600,  # 10 minute expiry
            "aud": "/admin/",
        }
        
        try:
            secret_bytes = bytes.fromhex(self.key_secret)
        except ValueError as e:
            raise ValueError(f"Invalid hex in GHOST_ADMIN_API_KEY secret: {e}")
        
        return jwt.encode(
            payload,
            secret_bytes,
            algorithm="HS256",
            headers={"kid": self.key_id},
        )
    
    def _headers(self) -> Dict[str, str]:
        """Get authorization headers for API requests."""
        return {
            "Authorization": f"Ghost {self._generate_jwt()}",
            "Content-Type": "application/json",
        }
    
    async def create_post(
        self,
        title: str,
        html: str,
        tags: Optional[List[str]] = None,
        status: str = "draft",
        custom_excerpt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new Ghost post.
        
        Args:
            title: Post title
            html: HTML content
            tags: List of tag names
            status: draft, scheduled, published
            custom_excerpt: Short description for post list
        
        Returns:
            Post dict with id, url, slug, etc.
        """
        post_data = {
            "title": title,
            "html": html,
            "status": status,
        }
        
        if custom_excerpt:
            post_data["custom_excerpt"] = custom_excerpt
        
        if tags:
            post_data["tags"] = [{"name": t} for t in tags]
        
        body = {"posts": [post_data]}
        
        logger.info(f"Creating Ghost post: {title} (status={status})")
        
        try:
            resp = await self.client.post(
                "/ghost/api/admin/posts/",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error creating post: {e}")
            raise
        
        result = resp.json()
        posts = result.get("posts", [])
        
        if not posts:
            raise ValueError("No post returned from Ghost API")
        
        post = posts[0]
        logger.info(f"Post created: id={post.get('id')}, slug={post.get('slug')}")
        return post
    
    async def publish_post(self, ghost_post_id: str) -> Dict[str, Any]:
        """
        Publish a draft post.
        
        Args:
            ghost_post_id: Ghost post UUID
        
        Returns:
            Updated post dict
        """
        logger.info(f"Publishing post {ghost_post_id}")
        
        try:
            # Fetch current post to get updated_at (optimistic locking)
            resp = await self.client.get(
                f"/ghost/api/admin/posts/{ghost_post_id}/",
                headers=self._headers(),
            )
            resp.raise_for_status()
            current = resp.json()["posts"][0]
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching post: {e}")
            raise
        
        # Update status to published
        update_body = {
            "posts": [
                {
                    "status": "published",
                    "updated_at": current["updated_at"],
                }
            ]
        }
        
        try:
            resp = await self.client.put(
                f"/ghost/api/admin/posts/{ghost_post_id}/",
                json=update_body,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error publishing post: {e}")
            raise
        
        result = resp.json()
        post = result.get("posts", [{}])[0]
        logger.info(f"Post published: {post.get('url')}")
        return post
    
    async def get_post(self, ghost_post_id: str) -> Dict[str, Any]:
        """Fetch a single post by ID."""
        try:
            resp = await self.client.get(
                f"/ghost/api/admin/posts/{ghost_post_id}/",
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching post: {e}")
            raise
        
        return resp.json()["posts"][0]
    
    async def get_posts(
        self,
        limit: int = 10,
        status: Optional[str] = None,
        filter_str: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch multiple posts.
        
        Args:
            limit: Maximum number of posts
            status: Filter by status (draft, published, etc.)
            filter_str: Ghost filter syntax
        
        Returns:
            List of post dicts
        """
        params = {"limit": limit}
        
        if status:
            params["filter"] = f"status:{status}"
        elif filter_str:
            params["filter"] = filter_str
        
        try:
            resp = await self.client.get(
                "/ghost/api/admin/posts/",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching posts: {e}")
            raise
        
        return resp.json().get("posts", [])
    
    async def update_post(
        self,
        ghost_post_id: str,
        **fields,
    ) -> Dict[str, Any]:
        """
        Update a post. Must include 'updated_at' for optimistic locking.
        
        Args:
            ghost_post_id: Ghost post UUID
            **fields: Fields to update (title, html, tags, etc.)
        
        Returns:
            Updated post dict
        """
        if "updated_at" not in fields:
            # Fetch current to get updated_at
            try:
                current = await self.get_post(ghost_post_id)
                fields["updated_at"] = current["updated_at"]
            except Exception as e:
                logger.error(f"Could not fetch current post for update: {e}")
                raise
        
        body = {"posts": [fields]}
        
        try:
            resp = await self.client.put(
                f"/ghost/api/admin/posts/{ghost_post_id}/",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error updating post: {e}")
            raise
        
        return resp.json()["posts"][0]
    
    async def delete_post(self, ghost_post_id: str) -> bool:
        """Delete a post."""
        logger.info(f"Deleting post {ghost_post_id}")
        
        try:
            resp = await self.client.delete(
                f"/ghost/api/admin/posts/{ghost_post_id}/",
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error deleting post: {e}")
            raise
        
        return True
    
    # ============================================================================
    # Newsletter Management Methods (Phase 2 Follow-up — Task 148)
    # ============================================================================
    
    async def get_newsletters(self) -> List[Dict[str, Any]]:
        """
        Fetch all newsletters.
        
        Returns:
            List of newsletter dicts with id, name, status, sender_email, etc.
        """
        logger.info("Fetching all newsletters")
        
        try:
            resp = await self.client.get(
                "/ghost/api/admin/newsletters/",
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching newsletters: {e}")
            raise
        
        return resp.json().get("newsletters", [])
    
    async def get_newsletter(self, newsletter_id: str) -> Dict[str, Any]:
        """
        Fetch a single newsletter by ID.
        
        Args:
            newsletter_id: Newsletter UUID
        
        Returns:
            Newsletter dict
        """
        logger.info(f"Fetching newsletter {newsletter_id}")
        
        try:
            resp = await self.client.get(
                f"/ghost/api/admin/newsletters/{newsletter_id}/",
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching newsletter: {e}")
            raise
        
        return resp.json().get("newsletters", [{}])[0]
    
    async def create_newsletter(
        self,
        name: str,
        description: Optional[str] = None,
        sender_name: Optional[str] = None,
        sender_email: Optional[str] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """
        Create a new newsletter.
        
        Args:
            name: Newsletter name
            description: Optional newsletter description
            sender_name: Name to appear in "From" (defaults to site title)
            sender_email: Email to appear in "From"
            status: 'active' or 'inactive'
        
        Returns:
            Created newsletter dict with id
        """
        logger.info(f"Creating newsletter: {name}")
        
        newsletter_data = {
            "name": name,
            "status": status,
        }
        
        if description:
            newsletter_data["description"] = description
        if sender_name:
            newsletter_data["sender_name"] = sender_name
        if sender_email:
            newsletter_data["sender_email"] = sender_email
        
        body = {"newsletters": [newsletter_data]}
        
        try:
            resp = await self.client.post(
                "/ghost/api/admin/newsletters/",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error creating newsletter: {e}")
            raise
        
        result = resp.json()
        newsletters = result.get("newsletters", [])
        
        if not newsletters:
            raise ValueError("No newsletter returned from Ghost API")
        
        newsletter = newsletters[0]
        logger.info(f"Newsletter created: id={newsletter.get('id')}, name={newsletter.get('name')}")
        return newsletter
    
    async def update_newsletter(
        self,
        newsletter_id: str,
        **fields,
    ) -> Dict[str, Any]:
        """
        Update a newsletter.
        
        Args:
            newsletter_id: Newsletter UUID
            **fields: Fields to update (name, status, sender_name, sender_email, etc.)
        
        Returns:
            Updated newsletter dict
        """
        logger.info(f"Updating newsletter {newsletter_id}")
        
        body = {"newsletters": [fields]}
        
        try:
            resp = await self.client.put(
                f"/ghost/api/admin/newsletters/{newsletter_id}/",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error updating newsletter: {e}")
            raise
        
        return resp.json().get("newsletters", [{}])[0]
    
    async def get_members(
        self,
        limit: int = 15,
        status: Optional[str] = None,
        filter_str: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch newsletter subscribers (members).
        
        Args:
            limit: Maximum number of members to fetch
            status: Filter by status ('free', 'paid', 'comped')
            filter_str: Ghost filter syntax
        
        Returns:
            List of member dicts with email, name, status, subscribed, etc.
        """
        logger.info(f"Fetching members (limit={limit}, status={status})")
        
        params = {"limit": limit}
        
        if status:
            params["filter"] = f"status:{status}"
        elif filter_str:
            params["filter"] = filter_str
        
        try:
            resp = await self.client.get(
                "/ghost/api/admin/members/",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching members: {e}")
            raise
        
        return resp.json().get("members", [])
    
    async def get_members_count(self) -> Dict[str, int]:
        """
        Get subscriber statistics.
        
        Returns:
            Dict with counts: free, paid, comped, wymedia, total
        """
        logger.info("Fetching member statistics")
        
        try:
            resp = await self.client.get(
                "/ghost/api/admin/members/stats/",
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error fetching member stats: {e}")
            raise
        
        return resp.json().get("stats", {})
    
    async def send_newsletter(
        self,
        newsletter_id: str,
        post_id: str,
    ) -> Dict[str, Any]:
        """
        Send a newsletter email to all free subscribers for a specific post.
        
        Args:
            newsletter_id: Newsletter UUID
            post_id: Ghost post UUID to send as newsletter
        
        Returns:
            Email send result dict with status, sent_count, etc.
        
        Note:
            This endpoint requires email to be configured (Mailgun, SendGrid, SMTP).
            Without email setup, the request will fail.
        """
        logger.info(f"Sending newsletter {newsletter_id} for post {post_id}")
        
        email_data = {
            "posts": [{"post_id": post_id}],
        }
        
        body = {"emails": [email_data]}
        
        try:
            resp = await self.client.post(
                f"/ghost/api/admin/newsletters/{newsletter_id}/emails/",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Ghost API error sending newsletter: {e}")
            raise
        
        result = resp.json()
        emails = result.get("emails", [])
        
        if not emails:
            raise ValueError("No email result returned from Ghost API")
        
        email = emails[0]
        logger.info(f"Newsletter sent: status={email.get('status')}, id={email.get('id')}")
        return email
