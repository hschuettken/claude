"""Ghost Admin API client for marketing agent."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import jwt

from config import settings


class GhostAdminClient:
    """Client for Ghost Admin API with JWT authentication."""

    def __init__(
        self,
        ghost_url: str,
        admin_api_key: str,
    ):
        """Initialize Ghost Admin client.

        Args:
            ghost_url: Base URL of Ghost instance (e.g., https://layer8.schuettken.net)
            admin_api_key: Ghost Admin API key (format: id:secret)
        """
        self.ghost_url = ghost_url.rstrip("/")
        self.admin_api_key = admin_api_key
        self._parse_api_key()
        self.client = httpx.AsyncClient(base_url=self.ghost_url)

    def _parse_api_key(self) -> None:
        """Parse Admin API key into id and secret."""
        parts = self.admin_api_key.split(":")
        if len(parts) != 2:
            raise ValueError("Ghost Admin API key must be in format 'id:secret'")
        self.key_id, self.key_secret = parts

    def _generate_jwt(self) -> str:
        """Generate JWT token for Ghost Admin API authentication."""
        iat = int(time.time())
        exp = iat + 600  # 10 minutes expiry

        header = {"alg": "HS256", "typ": "JWT", "kid": self.key_id}

        payload = {
            "iat": iat,
            "exp": exp,
            "aud": "/admin/",
        }

        # Encode secret as bytes for hmac
        secret_bytes = bytes.fromhex(self.key_secret)

        token = jwt.encode(
            payload,
            secret_bytes,
            algorithm="HS256",
            headers=header,
        )

        return token

    def _get_headers(self) -> Dict[str, str]:
        """Get authenticated headers for Ghost API requests."""
        token = self._generate_jwt()
        return {
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
        }

    async def create_post(
        self,
        title: str,
        html: str,
        tags: Optional[List[str]] = None,
        status: str = "draft",
        feature_image: Optional[str] = None,
        custom_excerpt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new post in Ghost.

        Args:
            title: Post title
            html: Post content in HTML
            tags: List of tag names
            status: Post status (draft, published, scheduled)
            feature_image: Featured image URL
            custom_excerpt: Custom excerpt/summary

        Returns:
            Created post object from Ghost API
        """
        post_data = {
            "posts": [
                {
                    "title": title,
                    "html": html,
                    "status": status,
                }
            ]
        }

        if tags:
            post_data["posts"][0]["tags"] = [{"name": tag} for tag in tags]

        if feature_image:
            post_data["posts"][0]["feature_image"] = feature_image

        if custom_excerpt:
            post_data["posts"][0]["custom_excerpt"] = custom_excerpt

        headers = self._get_headers()
        response = await self.client.post(
            "/ghost/api/admin/posts/",
            json=post_data,
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        return result["posts"][0] if result.get("posts") else result

    async def update_post(
        self,
        post_id: str,
        **fields,
    ) -> Dict[str, Any]:
        """Update an existing post.

        Args:
            post_id: Ghost post ID
            **fields: Fields to update (title, html, status, tags, etc.)

        Returns:
            Updated post object
        """
        post_data = {"posts": [fields]}
        headers = self._get_headers()

        response = await self.client.put(
            f"/ghost/api/admin/posts/{post_id}/",
            json=post_data,
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        return result["posts"][0] if result.get("posts") else result

    async def get_posts(
        self,
        limit: int = 15,
        filter_: Optional[str] = None,
        include: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch posts from Ghost.

        Args:
            limit: Number of posts to fetch
            filter_: Ghost filter syntax (e.g., "status:[draft,scheduled]")
            include: Comma-separated fields to include (e.g., "authors,tags")

        Returns:
            List of post objects
        """
        headers = self._get_headers()
        params = {"limit": limit}

        if filter_:
            params["filter"] = filter_

        if include:
            params["include"] = include

        response = await self.client.get(
            "/ghost/api/admin/posts/",
            headers=headers,
            params=params,
        )
        response.raise_for_status()

        result = response.json()
        return result.get("posts", [])

    async def get_post(self, post_id: str) -> Dict[str, Any]:
        """Fetch a single post by ID.

        Args:
            post_id: Ghost post ID

        Returns:
            Post object
        """
        headers = self._get_headers()
        response = await self.client.get(
            f"/ghost/api/admin/posts/{post_id}/",
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        return result.get("posts", [{}])[0]

    async def delete_post(self, post_id: str) -> bool:
        """Delete a post.

        Args:
            post_id: Ghost post ID

        Returns:
            True if successful
        """
        headers = self._get_headers()
        response = await self.client.delete(
            f"/ghost/api/admin/posts/{post_id}/",
            headers=headers,
        )
        response.raise_for_status()
        return True

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


def get_ghost_client() -> GhostAdminClient:
    """Factory function to create Ghost client from settings."""
    return GhostAdminClient(
        ghost_url=settings.ghost_url,
        admin_api_key=settings.ghost_admin_api_key,
    )
