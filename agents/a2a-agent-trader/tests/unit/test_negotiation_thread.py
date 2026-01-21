"""Unit tests for negotiation thread store with SQLite backend."""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path

from app.policies.sqlite_client import SQLiteClient
from app.policies.negotiation_thread import get_thread_store, NegotiationThreadStore


@pytest.fixture
def temp_db():
    """Create a temporary database file for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def sqlite_client(temp_db):
    """Create a SQLiteClient instance with temporary database."""
    return SQLiteClient(db_path=temp_db)


@pytest.fixture
def thread_store(sqlite_client):
    """Create a NegotiationThreadStore instance."""
    return NegotiationThreadStore(sqlite_client=sqlite_client)


class TestNegotiationThreadStore:
    """Tests for NegotiationThreadStore with SQLite backend."""
    
    @pytest.mark.asyncio
    async def test_save_and_load_message(self, thread_store):
        """Test saving and loading a single message."""
        # Save a message
        round_num = await thread_store.add_message(
            negotiation_id="test-123",
            sender="agent-1",
            our_price=100,
            their_price=120,
            proposed_price=110,
            action_taken="COUNTER_OFFER",
            message_type="initial_proposal"
        )
        
        assert round_num == 0
        
        # Load thread
        thread = await thread_store.get_thread("test-123")
        
        assert len(thread) == 1
        assert thread[0]["round"] == 0
        assert thread[0]["sender"] == "agent-1"
        assert thread[0]["our_price"] == 100
        assert thread[0]["their_price"] == 120
        assert thread[0]["proposed_price"] == 110
        assert thread[0]["action_taken"] == "COUNTER_OFFER"
        assert thread[0]["message_type"] == "initial_proposal"
        assert "timestamp" in thread[0]
    
    @pytest.mark.asyncio
    async def test_multiple_messages_round_numbers(self, thread_store):
        """Test that round numbers increment correctly for multiple messages."""
        # Add multiple messages
        for i in range(3):
            round_num = await thread_store.add_message(
                negotiation_id="test-multi",
                sender=f"agent-{i % 2}",
                our_price=100 + i * 10,
                their_price=120 + i * 10,
                proposed_price=None,
                action_taken="COUNTER_OFFER" if i < 2 else "ACCEPT_OFFER",
                message_type="counter_proposal" if i > 0 else "initial_proposal"
            )
            assert round_num == i
        
        # Load and verify
        thread = await thread_store.get_thread("test-multi")
        assert len(thread) == 3
        assert thread[0]["round"] == 0
        assert thread[1]["round"] == 1
        assert thread[2]["round"] == 2
        assert thread[0]["sender"] == "agent-0"
        assert thread[1]["sender"] == "agent-1"
        assert thread[2]["sender"] == "agent-0"
    
    @pytest.mark.asyncio
    async def test_empty_thread(self, thread_store):
        """Test loading a non-existent thread returns empty list."""
        thread = await thread_store.get_thread("non-existent")
        assert thread == []
    
    @pytest.mark.asyncio
    async def test_terminal_condition_accept_accept(self, thread_store):
        """Test ACCEPT-ACCEPT terminal condition (success)."""
        # Add two ACCEPT_OFFER messages
        await thread_store.add_message(
            "test-success", "agent-1", 100, 100, None, "ACCEPT_OFFER", "proposal"
        )
        await thread_store.add_message(
            "test-success", "agent-2", 100, 100, None, "ACCEPT_OFFER", "proposal"
        )
        
        is_terminal, state = await thread_store.check_terminal("test-success")
        assert is_terminal is True
        assert state == "success"
    
    @pytest.mark.asyncio
    async def test_terminal_condition_reject_reject(self, thread_store):
        """Test REJECT-REJECT terminal condition (failure)."""
        # Add two REJECT_OFFER messages
        await thread_store.add_message(
            "test-failure", "agent-1", 100, 150, None, "REJECT_OFFER", "proposal"
        )
        await thread_store.add_message(
            "test-failure", "agent-2", 100, 150, None, "REJECT_OFFER", "proposal"
        )
        
        is_terminal, state = await thread_store.check_terminal("test-failure")
        assert is_terminal is True
        assert state == "failure"
    
    @pytest.mark.asyncio
    async def test_terminal_condition_exit_negotiation(self, thread_store):
        """Test EXIT_NEGOTIATION terminal condition (timeout)."""
        # Add EXIT_NEGOTIATION message
        await thread_store.add_message(
            "test-timeout", "agent-1", 100, 120, None, "EXIT_NEGOTIATION", "exit"
        )
        
        is_terminal, state = await thread_store.check_terminal("test-timeout")
        assert is_terminal is True
        assert state == "timeout"
    
    @pytest.mark.asyncio
    async def test_terminal_condition_not_terminal(self, thread_store):
        """Test that non-terminal conditions return False."""
        # Add single message (not terminal)
        await thread_store.add_message(
            "test-not-terminal", "agent-1", 100, 120, 110, "COUNTER_OFFER", "proposal"
        )
        
        is_terminal, state = await thread_store.check_terminal("test-not-terminal")
        assert is_terminal is False
        assert state is None
        
        # Add ACCEPT then COUNTER (not terminal - need both to accept)
        await thread_store.add_message(
            "test-not-terminal-2", "agent-1", 100, 100, None, "ACCEPT_OFFER", "proposal"
        )
        await thread_store.add_message(
            "test-not-terminal-2", "agent-2", 100, 100, 110, "COUNTER_OFFER", "proposal"
        )
        
        is_terminal, state = await thread_store.check_terminal("test-not-terminal-2")
        assert is_terminal is False
        assert state is None
    
    @pytest.mark.asyncio
    async def test_clear_thread(self, thread_store):
        """Test clearing a thread removes all messages."""
        # Add messages
        await thread_store.add_message(
            "test-clear", "agent-1", 100, 120, None, "ACCEPT_OFFER", "proposal"
        )
        await thread_store.add_message(
            "test-clear", "agent-2", 100, 120, None, "ACCEPT_OFFER", "proposal"
        )
        
        # Verify thread exists
        thread = await thread_store.get_thread("test-clear")
        assert len(thread) == 2
        
        # Clear thread
        await thread_store.clear_thread("test-clear")
        
        # Verify thread is gone
        thread = await thread_store.get_thread("test-clear")
        assert len(thread) == 0
    
    @pytest.mark.asyncio
    async def test_thread_persistence(self, sqlite_client, temp_db):
        """Test that threads persist across store instances."""
        # Create first store and add message
        store1 = NegotiationThreadStore(sqlite_client=sqlite_client)
        await store1.add_message(
            "test-persist", "agent-1", 100, 120, 110, "COUNTER_OFFER", "proposal"
        )
        
        # Create second store with same database
        client2 = SQLiteClient(db_path=temp_db)
        store2 = NegotiationThreadStore(sqlite_client=client2)
        
        # Load thread from second store
        thread = await store2.get_thread("test-persist")
        assert len(thread) == 1
        assert thread[0]["our_price"] == 100
        assert thread[0]["their_price"] == 120
    
    @pytest.mark.asyncio
    async def test_none_prices(self, thread_store):
        """Test handling of None prices."""
        await thread_store.add_message(
            "test-none", "agent-1", None, None, None, "EXIT_NEGOTIATION", "exit"
        )
        
        thread = await thread_store.get_thread("test-none")
        assert len(thread) == 1
        assert thread[0]["our_price"] is None
        assert thread[0]["their_price"] is None
        assert thread[0]["proposed_price"] is None


class TestGetThreadStore:
    """Tests for get_thread_store() function."""
    
    def test_get_thread_store_requires_sqlite_client(self, sqlite_client):
        """Test that get_thread_store() requires sqlite_client on first call."""
        # Reset global state by importing fresh
        import importlib
        import app.policies.negotiation_thread as nthread_module
        importlib.reload(nthread_module)
        
        # Get the NegotiationThreadStore class from the reloaded module
        ReloadedNegotiationThreadStore = nthread_module.NegotiationThreadStore
        
        # First call without sqlite_client should raise ValueError
        with pytest.raises(ValueError, match="SQLiteClient must be provided"):
            nthread_module.get_thread_store()
        
        # First call with sqlite_client should work
        store = nthread_module.get_thread_store(sqlite_client=sqlite_client)
        assert isinstance(store, ReloadedNegotiationThreadStore)
        
        # Subsequent calls can omit parameter
        store2 = nthread_module.get_thread_store()
        assert store2 is store  # Same instance
    
    def test_get_thread_store_singleton(self, sqlite_client):
        """Test that get_thread_store() returns singleton instance."""
        import importlib
        import app.policies.negotiation_thread as nthread_module
        importlib.reload(nthread_module)
        
        # Get the NegotiationThreadStore class from the reloaded module
        ReloadedNegotiationThreadStore = nthread_module.NegotiationThreadStore
        
        store1 = nthread_module.get_thread_store(sqlite_client=sqlite_client)
        store2 = nthread_module.get_thread_store()
        store3 = nthread_module.get_thread_store()
        
        assert isinstance(store1, ReloadedNegotiationThreadStore)
        assert store1 is store2
        assert store2 is store3


class TestSQLiteClientNegotiationMethods:
    """Tests for SQLiteClient negotiation thread methods."""
    
    @pytest.mark.asyncio
    async def test_save_negotiation_message(self, sqlite_client):
        """Test saving a negotiation message directly."""
        await sqlite_client.save_negotiation_message(
            negotiation_id="test-direct",
            round=0,
            sender="agent-1",
            our_price=100,
            their_price=120,
            proposed_price=110,
            action_taken="COUNTER_OFFER",
            message_type="proposal",
            timestamp="2025-01-01T00:00:00"
        )
        
        # Verify message was saved
        thread = await sqlite_client.load_negotiation_thread(negotiation_id="test-direct")
        assert len(thread) == 1
        assert thread[0]["sender"] == "agent-1"
    
    @pytest.mark.asyncio
    async def test_load_negotiation_thread_ordered(self, sqlite_client):
        """Test that messages are loaded in round order."""
        # Save messages in reverse order
        for i in range(3):
            await sqlite_client.save_negotiation_message(
                negotiation_id="test-order",
                round=i,
                sender=f"agent-{i}",
                our_price=100,
                their_price=120,
                proposed_price=None,
                action_taken="COUNTER_OFFER",
                message_type="proposal",
                timestamp=f"2025-01-01T00:00:0{i}"
            )
        
        # Load and verify order
        thread = await sqlite_client.load_negotiation_thread(negotiation_id="test-order")
        assert len(thread) == 3
        assert thread[0]["round"] == 0
        assert thread[1]["round"] == 1
        assert thread[2]["round"] == 2
    
    @pytest.mark.asyncio
    async def test_update_negotiation_thread_terminal(self, sqlite_client):
        """Test updating terminal state."""
        # Create thread
        await sqlite_client.save_negotiation_message(
            negotiation_id="test-terminal",
            round=0,
            sender="agent-1",
            our_price=100,
            their_price=100,
            proposed_price=None,
            action_taken="ACCEPT_OFFER",
            message_type="proposal",
            timestamp="2025-01-01T00:00:00"
        )
        
        # Update terminal state
        await sqlite_client.update_negotiation_thread_terminal(
            negotiation_id="test-terminal",
            terminal_state="success"
        )
        
        # Verify in database (direct query)
        import sqlite3
        conn = sqlite3.connect(sqlite_client.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT terminal_state FROM negotiation_threads WHERE negotiation_id = ?",
            ("test-terminal",)
        )
        result = cur.fetchone()
        conn.close()
        assert result[0] == "success"
    
    @pytest.mark.asyncio
    async def test_delete_negotiation_thread(self, sqlite_client):
        """Test deleting a negotiation thread."""
        # Create thread with messages
        for i in range(2):
            await sqlite_client.save_negotiation_message(
                negotiation_id="test-delete",
                round=i,
                sender=f"agent-{i}",
                our_price=100,
                their_price=120,
                proposed_price=None,
                action_taken="COUNTER_OFFER",
                message_type="proposal",
                timestamp=f"2025-01-01T00:00:0{i}"
            )
        
        # Verify exists
        thread = await sqlite_client.load_negotiation_thread(negotiation_id="test-delete")
        assert len(thread) == 2
        
        # Delete
        await sqlite_client.delete_negotiation_thread(negotiation_id="test-delete")
        
        # Verify deleted
        thread = await sqlite_client.load_negotiation_thread(negotiation_id="test-delete")
        assert len(thread) == 0
        
        # Verify database cleanup
        import sqlite3
        conn = sqlite3.connect(sqlite_client.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM negotiation_messages WHERE negotiation_id = ?",
            ("test-delete",)
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT COUNT(*) FROM negotiation_threads WHERE negotiation_id = ?",
            ("test-delete",)
        )
        assert cur.fetchone()[0] == 0
        conn.close()
