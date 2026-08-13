"""새 DB에 코인 테이블이 생기지 않는다.

기존 운영 DB의 빈 coin_* 테이블은 일부러 남긴다(라이브 마이그레이션 위험 회피).
이 테스트가 보는 것은 '새로 만드는 DB'다.
"""
import sqlite3

import pytest

from services.storage_service import StorageService


@pytest.mark.asyncio
async def test_fresh_db_has_no_coin_tables(tmp_path):
    db = tmp_path / "fresh.db"
    storage = StorageService(db_path=str(db))
    await storage.initialize()

    conn = sqlite3.connect(str(db))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()

    coin_tables = {n for n in names if "coin" in n}
    assert coin_tables == set(), f"새 DB에 코인 테이블이 생겼다: {coin_tables}"
    # 살아 있어야 하는 것들
    assert "kr_stock_trades" in names
    assert "daily_perf_snapshot" in names


@pytest.mark.asyncio
async def test_fresh_db_has_no_coin_indexes(tmp_path):
    db = tmp_path / "fresh2.db"
    storage = StorageService(db_path=str(db))
    await storage.initialize()

    conn = sqlite3.connect(str(db))
    idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()

    assert {i for i in idx if "coin" in i} == set()


def test_storage_service_has_no_coin_accessors():
    coin_attrs = [a for a in dir(StorageService) if "coin" in a.lower()]
    assert coin_attrs == [], f"코인 접근자가 남아 있다: {coin_attrs}"
