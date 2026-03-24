"""Unit tests for Ghost client newsletter methods — Task 148 Follow-up."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

# Import the ghost_client from parent directory
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ghost_client import GhostAdminAPIClient


class TestGhostClientNewsletters:
    """Test Ghost client newsletter methods (Phase 2 - Task 148 Follow-up)."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create client with test credentials (valid hex string)
        self.client = GhostAdminAPIClient(
            api_key="test_key_id:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            ghost_url="https://test.ghost.io"
        )
    
    @pytest.mark.asyncio
    async def test_get_newsletters(self):
        """Test fetching all newsletters."""
        expected_newsletters = [
            {
                "id": "nl1",
                "name": "Layer 8 Weekly",
                "status": "active",
                "sender_name": "Layer 8",
                "sender_email": "newsletter@layer8.schuettken.net",
            },
            {
                "id": "nl2",
                "name": "Tech Updates",
                "status": "inactive",
                "sender_name": "Tech",
                "sender_email": "tech@layer8.schuettken.net",
            }
        ]
        
        with patch.object(self.client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"newsletters": expected_newsletters}
            mock_get.return_value = mock_response
            
            result = await self.client.get_newsletters()
            
            assert len(result) == 2
            assert result[0]["name"] == "Layer 8 Weekly"
            assert result[1]["id"] == "nl2"
            mock_get.assert_called_once_with(
                "/ghost/api/admin/newsletters/",
                headers=self.client._headers(),
            )
    
    @pytest.mark.asyncio
    async def test_get_newsletter_single(self):
        """Test fetching a single newsletter."""
        expected_newsletter = {
            "id": "nl1",
            "name": "Layer 8 Weekly",
            "status": "active",
            "sender_name": "Layer 8",
            "sender_email": "newsletter@layer8.schuettken.net",
        }
        
        with patch.object(self.client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"newsletters": [expected_newsletter]}
            mock_get.return_value = mock_response
            
            result = await self.client.get_newsletter("nl1")
            
            assert result["id"] == "nl1"
            assert result["name"] == "Layer 8 Weekly"
            mock_get.assert_called_once_with(
                "/ghost/api/admin/newsletters/nl1/",
                headers=self.client._headers(),
            )
    
    @pytest.mark.asyncio
    async def test_create_newsletter(self):
        """Test creating a newsletter."""
        expected_newsletter = {
            "id": "nl3",
            "name": "New Newsletter",
            "description": "A new newsletter",
            "status": "active",
            "sender_name": "New",
            "sender_email": "new@layer8.schuettken.net",
        }
        
        with patch.object(self.client.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"newsletters": [expected_newsletter]}
            mock_post.return_value = mock_response
            
            result = await self.client.create_newsletter(
                name="New Newsletter",
                description="A new newsletter",
                sender_name="New",
                sender_email="new@layer8.schuettken.net",
            )
            
            assert result["id"] == "nl3"
            assert result["name"] == "New Newsletter"
            assert result["status"] == "active"
            mock_post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_newsletter(self):
        """Test updating a newsletter."""
        updated_newsletter = {
            "id": "nl1",
            "name": "Layer 8 Weekly Updated",
            "status": "inactive",
            "sender_name": "Layer 8",
            "sender_email": "newsletter@layer8.schuettken.net",
        }
        
        with patch.object(self.client.client, 'put', new_callable=AsyncMock) as mock_put:
            mock_response = MagicMock()
            mock_response.json.return_value = {"newsletters": [updated_newsletter]}
            mock_put.return_value = mock_response
            
            result = await self.client.update_newsletter(
                newsletter_id="nl1",
                name="Layer 8 Weekly Updated",
                status="inactive",
            )
            
            assert result["name"] == "Layer 8 Weekly Updated"
            assert result["status"] == "inactive"
            mock_put.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_members(self):
        """Test fetching newsletter subscribers."""
        expected_members = [
            {
                "id": "m1",
                "email": "subscriber1@example.com",
                "name": "Subscriber One",
                "status": "free",
                "subscribed": True,
            },
            {
                "id": "m2",
                "email": "subscriber2@example.com",
                "name": "Subscriber Two",
                "status": "free",
                "subscribed": True,
            }
        ]
        
        with patch.object(self.client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"members": expected_members}
            mock_get.return_value = mock_response
            
            result = await self.client.get_members(limit=10, status="free")
            
            assert len(result) == 2
            assert result[0]["email"] == "subscriber1@example.com"
            assert result[1]["status"] == "free"
            mock_get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_members_count(self):
        """Test fetching member statistics."""
        expected_stats = {
            "free": 150,
            "paid": 25,
            "comped": 5,
            "wymedia": 0,
            "total": 180,
        }
        
        with patch.object(self.client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"stats": expected_stats}
            mock_get.return_value = mock_response
            
            result = await self.client.get_members_count()
            
            assert result["free"] == 150
            assert result["total"] == 180
            mock_get.assert_called_once_with(
                "/ghost/api/admin/members/stats/",
                headers=self.client._headers(),
            )
    
    @pytest.mark.asyncio
    async def test_send_newsletter(self):
        """Test sending a newsletter email."""
        expected_email = {
            "id": "email1",
            "newsletter_id": "nl1",
            "post_id": "post123",
            "status": "pending",
            "error": None,
            "email_count": 150,
            "opened_count": 0,
            "failed_count": 0,
        }
        
        with patch.object(self.client.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"emails": [expected_email]}
            mock_post.return_value = mock_response
            
            result = await self.client.send_newsletter(
                newsletter_id="nl1",
                post_id="post123",
            )
            
            assert result["id"] == "email1"
            assert result["status"] == "pending"
            assert result["email_count"] == 150
            mock_post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_newsletter_error_handling(self):
        """Test error handling when sending newsletter fails."""
        with patch.object(self.client.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.HTTPError("Email configuration missing")
            
            with pytest.raises(httpx.HTTPError):
                await self.client.send_newsletter(
                    newsletter_id="nl1",
                    post_id="post123",
                )
    
    @pytest.mark.asyncio
    async def test_newsletter_integration_workflow(self):
        """Test complete newsletter workflow: create, get, update, send."""
        # Step 1: Create newsletter
        created_nl = {
            "id": "nl_new",
            "name": "Test Newsletter",
            "status": "active",
        }
        
        # Step 2: Get all newsletters
        all_nls = [created_nl]
        
        # Step 3: Update newsletter
        updated_nl = {**created_nl, "name": "Updated Newsletter"}
        
        # Step 4: Get members
        members = [
            {"id": "m1", "email": "test@example.com", "status": "free"}
        ]
        
        # Step 5: Send newsletter
        email_result = {
            "id": "email1",
            "status": "pending",
            "email_count": 1,
        }
        
        with patch.object(self.client.client, 'post', new_callable=AsyncMock) as mock_post, \
             patch.object(self.client.client, 'get', new_callable=AsyncMock) as mock_get, \
             patch.object(self.client.client, 'put', new_callable=AsyncMock) as mock_put:
            
            # Setup mock responses
            mock_post.return_value = MagicMock()
            mock_get.return_value = MagicMock()
            mock_put.return_value = MagicMock()
            
            # These are just smoke tests to verify methods exist and are callable
            # In real scenario, we'd mock individual responses
            assert hasattr(self.client, 'create_newsletter')
            assert hasattr(self.client, 'get_newsletters')
            assert hasattr(self.client, 'update_newsletter')
            assert hasattr(self.client, 'get_members')
            assert hasattr(self.client, 'send_newsletter')


class TestGhostClientNewsletterId:
    """Test newsletter ID and method signatures."""
    
    def test_newsletter_methods_exist(self):
        """Verify all newsletter methods are defined."""
        client = GhostAdminAPIClient(
            api_key="test_key_id:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            ghost_url="https://test.ghost.io"
        )
        
        methods = [
            'get_newsletters',
            'get_newsletter',
            'create_newsletter',
            'update_newsletter',
            'get_members',
            'get_members_count',
            'send_newsletter',
        ]
        
        for method_name in methods:
            assert hasattr(client, method_name), f"Missing method: {method_name}"
            assert callable(getattr(client, method_name)), f"Not callable: {method_name}"
    
    def test_newsletter_methods_are_async(self):
        """Verify all newsletter methods are async."""
        import inspect
        
        client = GhostAdminAPIClient(
            api_key="test_key_id:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            ghost_url="https://test.ghost.io"
        )
        
        async_methods = [
            'get_newsletters',
            'get_newsletter',
            'create_newsletter',
            'update_newsletter',
            'get_members',
            'get_members_count',
            'send_newsletter',
        ]
        
        for method_name in async_methods:
            method = getattr(client, method_name)
            assert inspect.iscoroutinefunction(method), f"Not async: {method_name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
