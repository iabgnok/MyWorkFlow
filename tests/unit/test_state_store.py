import pytest
import asyncio
import aiosqlite
import os
from engine.state_store import StateStore

@pytest.mark.asyncio
async def test_mask_secrets(tmp_path):
    db_path = tmp_path / "test.db"
    store = StateStore(str(db_path))
    await store.connect()
    
    context = {
        "normal_key": "abc",
        "api_key": "sensitive123",
        "nested": {
            "my_password": "hello"
        }
    }
    
    await store.save_run_state("test1", "wf1", "running", 1, context)
    
    loaded = await store.load_run_state("test1")
    assert loaded["context"]["normal_key"] == "abc"
    assert loaded["context"]["api_key"] == "******"
    assert loaded["context"]["nested"]["my_password"] == "******"
    
    await store.close()

@pytest.mark.asyncio
async def test_unserializable_context(tmp_path):
    db_path = tmp_path / "test_serialize.db"
    store = StateStore(str(db_path))
    await store.connect()
    
    # Adding a function mapping to cause JSON serialize error
    context = {
        "func": lambda x: x
    }
    
    # Needs to not raise JSON Exception but log it and use "{}"
    await store.save_run_state("test_serialize", "wf1", "running", 1, context)
    loaded = await store.load_run_state("test_serialize")
    assert loaded["context"] == {}
    
    await store.close()

@pytest.mark.asyncio
async def test_concurrent_write_lock(tmp_path):
    db_path = tmp_path / "test_lock.db"
    store1 = StateStore(str(db_path))
    store2 = StateStore(str(db_path))
    
    await store1.connect()
    await store2.connect()
    
    # Use execute directly to mimic a lock on thread 1
    # We will simulate the table is locked by beginning a transaction
    async with store1._conn.execute('BEGIN EXCLUSIVE TRANSACTION'):
        with pytest.raises(Exception, match="Failed to write state into database"):
            # Set a very low timeout for store2 to fail fast
            await store2._conn.execute('PRAGMA busy_timeout=1')
            await store2.save_run_state("test_lock", "wf", "running", 1, {"a":1})
        
    await store1.close()
    await store2.close()
