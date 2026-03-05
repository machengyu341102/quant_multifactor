"""
SQLite 数据存储层
================
WAL 模式, 替代高频变动的 JSON 文件 (scorecard/conflict_audit/trade_journal)。
保留 JSON 仅用于配置文件。

用法:
    from db_store import (
        load_scorecard, save_scorecard_records,
        load_conflict_audit, save_conflict_audit_record,
        load_trade_journal, save_trade_journal_entry,
    )
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

from log_config import get_logger

logger = get_logger("db_store")

_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "quant_data.db"
)

# 线程局部连接 (SQLite 不允许跨线程共享连接)
_local = threading.local()
_init_done = set()  # 已初始化的线程ID


def _get_conn() -> sqlite3.Connection:
    """获取线程局部 SQLite 连接 (WAL 模式)"""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def init_db():
    """初始化数据库表 (幂等)"""
    tid = threading.get_ident()
    if tid in _init_done:
        return
    conn = _get_conn()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scorecard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_date TEXT NOT NULL,
            code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            net_return_pct REAL NOT NULL DEFAULT 0,
            name TEXT,
            score REAL,
            rec_price REAL,
            entry_price REAL,
            exit_price REAL,
            next_open REAL,
            next_close REAL,
            next_high REAL,
            next_low REAL,
            raw_return_pct REAL,
            hit_stop_loss INTEGER,
            hit_take_profit INTEGER,
            result TEXT,
            win INTEGER,
            regime TEXT,
            factor_scores TEXT,
            verify_date TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE (rec_date, code, strategy)
        );

        CREATE INDEX IF NOT EXISTS idx_sc_date ON scorecard(rec_date);
        CREATE INDEX IF NOT EXISTS idx_sc_strategy ON scorecard(strategy);
        CREATE INDEX IF NOT EXISTS idx_sc_date_strategy ON scorecard(rec_date, strategy);

        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            strategy TEXT NOT NULL,
            regime_score REAL,
            regime_label TEXT,
            picks TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE (trade_date, strategy)
        );

        CREATE INDEX IF NOT EXISTS idx_tj_date ON trade_journal(trade_date);
        CREATE INDEX IF NOT EXISTS idx_tj_strategy ON trade_journal(strategy);

        CREATE TABLE IF NOT EXISTS conflict_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            strategy TEXT NOT NULL,
            winner_action TEXT NOT NULL,
            winner_authority INTEGER NOT NULL,
            loser_action TEXT NOT NULL,
            loser_authority INTEGER NOT NULL,
            findings TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            strategy TEXT NOT NULL DEFAULT '',
            entry_price REAL NOT NULL DEFAULT 0,
            entry_date TEXT NOT NULL,
            entry_time TEXT DEFAULT '',
            score REAL DEFAULT 0,
            reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'holding',
            holding_days INTEGER DEFAULT 1,
            highest_price REAL DEFAULT 0,
            atr REAL DEFAULT 0,
            partial_exited INTEGER DEFAULT 0,
            remaining_ratio REAL DEFAULT 1.0,
            exit_price REAL,
            exit_date TEXT,
            exit_time TEXT,
            exit_reason TEXT,
            pnl_pct REAL,
            last_exit_reason TEXT,
            extra TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE (code, entry_date, strategy)
        );

        CREATE INDEX IF NOT EXISTS idx_pos_status ON positions(status);
        CREATE INDEX IF NOT EXISTS idx_pos_date ON positions(entry_date);
    """)
    conn.commit()
    _init_done.add(tid)
    logger.info("数据库初始化完成: %s", _DB_PATH)


# ================================================================
#  Scorecard CRUD
# ================================================================

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Row → dict, 跳过 None 值字段 (兼容原 JSON 格式)"""
    d = {}
    for key in row.keys():
        val = row[key]
        if val is not None and key not in ("id", "created_at"):
            if key == "factor_scores" and isinstance(val, str):
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    d[key] = val
            else:
                d[key] = val
    return d


def load_scorecard(days: int | None = None, strategy: str | None = None) -> list[dict]:
    """读取记分卡 (替代 safe_load_strict 全量读取)

    Args:
        days: 仅返回最近 N 天的记录 (None=全部)
        strategy: 仅返回指定策略 (None=全部)
    """
    init_db()
    conn = _get_conn()
    conditions = []
    params = []

    if days is not None:
        conditions.append("rec_date >= date('now', 'localtime', ?)")
        params.append(f"-{days} days")
    if strategy:
        conditions.append("strategy = ?")
        params.append(strategy)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM scorecard {where} ORDER BY rec_date, id"

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def save_scorecard_records(records: list[dict]):
    """批量写入记分卡记录 (INSERT OR IGNORE 自动去重)"""
    if not records:
        return 0

    init_db()
    conn = _get_conn()
    count = 0

    for rec in records:
        factor_scores = rec.get("factor_scores")
        if isinstance(factor_scores, dict):
            factor_scores = json.dumps(factor_scores, ensure_ascii=False)

        try:
            conn.execute("""
                INSERT OR IGNORE INTO scorecard
                (rec_date, code, strategy, net_return_pct,
                 name, score, rec_price, entry_price, exit_price,
                 next_open, next_close, next_high, next_low,
                 raw_return_pct, hit_stop_loss, hit_take_profit,
                 result, win, regime, factor_scores, verify_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec.get("rec_date", ""),
                rec.get("code", ""),
                rec.get("strategy", ""),
                rec.get("net_return_pct", 0),
                rec.get("name"),
                rec.get("score"),
                rec.get("rec_price"),
                rec.get("entry_price"),
                rec.get("exit_price"),
                rec.get("next_open"),
                rec.get("next_close"),
                rec.get("next_high"),
                rec.get("next_low"),
                rec.get("raw_return_pct"),
                rec.get("hit_stop_loss"),
                rec.get("hit_take_profit"),
                rec.get("result"),
                rec.get("win"),
                rec.get("regime"),
                factor_scores,
                rec.get("verify_date"),
            ))
            count += 1
        except sqlite3.IntegrityError:
            pass  # 重复记录, 跳过

    conn.commit()
    return count


def scorecard_count() -> int:
    """记分卡总记录数"""
    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM scorecard").fetchone()
    return row[0] if row else 0


# ================================================================
#  Conflict Audit CRUD
# ================================================================

def load_conflict_audit(limit: int = 500) -> list[dict]:
    """读取冲突审计日志"""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM conflict_audit ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()

    result = []
    for r in rows:
        findings = r["findings"]
        if isinstance(findings, str):
            try:
                findings = json.loads(findings)
            except (json.JSONDecodeError, TypeError):
                pass
        result.append({
            "time": r["time"],
            "strategy": r["strategy"],
            "winner": {
                "action": r["winner_action"],
                "authority": r["winner_authority"],
            },
            "loser": {
                "action": r["loser_action"],
                "authority": r["loser_authority"],
                "findings": findings,
            },
        })

    result.reverse()  # 按时间正序
    return result


def save_conflict_audit_record(record: dict):
    """写入一条冲突审计记录 (自动保留最近500条)"""
    init_db()
    conn = _get_conn()

    winner = record.get("winner", {})
    loser = record.get("loser", {})
    findings = loser.get("findings", [])
    if isinstance(findings, list):
        findings = json.dumps(findings, ensure_ascii=False)

    conn.execute("""
        INSERT INTO conflict_audit
        (time, strategy, winner_action, winner_authority,
         loser_action, loser_authority, findings)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        record.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        record.get("strategy") or "SYSTEM",
        winner.get("action", ""),
        winner.get("authority", 0),
        loser.get("action", ""),
        loser.get("authority", 0),
        findings,
    ))

    # 保留最近500条
    conn.execute("""
        DELETE FROM conflict_audit
        WHERE id NOT IN (
            SELECT id FROM conflict_audit ORDER BY id DESC LIMIT 500
        )
    """)
    conn.commit()


# ================================================================
#  Trade Journal CRUD (EX-02)
# ================================================================

def load_trade_journal(days: int | None = None, strategy: str | None = None) -> list[dict]:
    """读取交易日志"""
    init_db()
    conn = _get_conn()
    conditions = []
    params = []

    if days is not None:
        conditions.append("trade_date >= date('now', 'localtime', ?)")
        params.append(f"-{days} days")
    if strategy:
        conditions.append("strategy = ?")
        params.append(strategy)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM trade_journal {where} ORDER BY trade_date, id"

    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        picks = r["picks"]
        if isinstance(picks, str):
            try:
                picks = json.loads(picks)
            except (json.JSONDecodeError, TypeError):
                picks = []
        result.append({
            "date": r["trade_date"],
            "strategy": r["strategy"],
            "regime": {
                "score": r["regime_score"] or 0,
                "regime": r["regime_label"] or "neutral",
            },
            "picks": picks or [],
        })
    return result


def save_trade_journal_entry(entry: dict) -> bool:
    """写入一条交易日志 (INSERT OR IGNORE 去重)"""
    init_db()
    conn = _get_conn()

    regime = entry.get("regime", {})
    picks = entry.get("picks", [])
    if isinstance(picks, list):
        picks = json.dumps(picks, ensure_ascii=False)

    try:
        conn.execute("""
            INSERT OR IGNORE INTO trade_journal
            (trade_date, strategy, regime_score, regime_label, picks)
            VALUES (?, ?, ?, ?, ?)
        """, (
            entry.get("date", ""),
            entry.get("strategy", ""),
            regime.get("score", 0),
            regime.get("regime", "neutral"),
            picks,
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def save_trade_journal_batch(entries: list[dict]) -> int:
    """批量写入交易日志"""
    count = 0
    for entry in entries:
        if save_trade_journal_entry(entry):
            count += 1
    return count


def migrate_trade_journal_from_json(json_path: str | None = None) -> int:
    """将 trade_journal.json 导入 SQLite"""
    if json_path is None:
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "trade_journal.json"
        )
    if not os.path.exists(json_path):
        logger.info("trade_journal.json 不存在, 跳过迁移")
        return 0

    from json_store import safe_load
    records = safe_load(json_path, default=[])
    if not records:
        return 0

    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM trade_journal").fetchone()
    existing = row[0] if row else 0
    if existing >= len(records):
        logger.info("trade_journal SQLite 已有 %d 条 (JSON %d), 跳过", existing, len(records))
        return 0

    logger.info("迁移 trade_journal.json → SQLite (%d 条)", len(records))
    count = save_trade_journal_batch(records)
    row2 = conn.execute("SELECT COUNT(*) FROM trade_journal").fetchone()
    total = row2[0] if row2 else 0
    logger.info("trade_journal 迁移完成: 新增 %d, 总计 %d", count, total)
    return count


# ================================================================
#  JSON → SQLite 迁移
# ================================================================

def migrate_scorecard_from_json(json_path: str | None = None) -> int:
    """将 scorecard.json 导入 SQLite (幂等, 已存在的记录自动跳过)"""
    if json_path is None:
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "scorecard.json"
        )
    if not os.path.exists(json_path):
        logger.info("scorecard.json 不存在, 跳过迁移")
        return 0

    from json_store import safe_load
    records = safe_load(json_path, default=[])
    if not records:
        return 0

    existing = scorecard_count()
    if existing >= len(records):
        logger.info("SQLite 已有 %d 条 (JSON %d 条), 跳过迁移", existing, len(records))
        return 0

    logger.info("开始迁移 scorecard.json → SQLite (%d 条记录)", len(records))
    count = save_scorecard_records(records)
    logger.info("迁移完成: 新增 %d 条, 总计 %d 条", count, scorecard_count())
    return count


def migrate_conflict_audit_from_json(json_path: str | None = None) -> int:
    """将 conflict_audit.json 导入 SQLite"""
    if json_path is None:
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "conflict_audit.json"
        )
    if not os.path.exists(json_path):
        return 0

    from json_store import safe_load
    records = safe_load(json_path, default=[])
    if not records:
        return 0

    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM conflict_audit").fetchone()
    existing = row[0] if row else 0
    if existing > 0:
        logger.info("conflict_audit 已有 %d 条, 跳过迁移", existing)
        return 0

    logger.info("迁移 conflict_audit.json → SQLite (%d 条)", len(records))
    for rec in records:
        save_conflict_audit_record(rec)
    return len(records)


def run_migration():
    """一键迁移所有 JSON → SQLite"""
    init_db()
    sc = migrate_scorecard_from_json()
    ca = migrate_conflict_audit_from_json()
    tj = migrate_trade_journal_from_json()
    print(f"[迁移完成] scorecard: {sc}, conflict_audit: {ca}, trade_journal: {tj}")
    return {"scorecard": sc, "conflict_audit": ca, "trade_journal": tj}


# ================================================================
#  入口
# ================================================================
#  Positions CRUD (原子事务)
# ================================================================

_POS_COLUMNS = (
    "code", "name", "strategy", "entry_price", "entry_date", "entry_time",
    "score", "reason", "status", "holding_days", "highest_price", "atr",
    "partial_exited", "remaining_ratio", "exit_price", "exit_date",
    "exit_time", "exit_reason", "pnl_pct", "last_exit_reason", "extra",
)


def _pos_to_row(p: dict) -> dict:
    """dict → DB row (boolean → int, extra fields → JSON)"""
    row = {}
    known = set(_POS_COLUMNS)
    for k in _POS_COLUMNS:
        v = p.get(k)
        if k == "partial_exited":
            row[k] = 1 if v else 0
        else:
            row[k] = v
    # 未知字段塞入 extra JSON
    extras = {k: v for k, v in p.items() if k not in known and k != "id"}
    row["extra"] = json.dumps(extras, ensure_ascii=False) if extras else None
    return row


def _row_to_pos(row: sqlite3.Row) -> dict:
    """DB row → position dict (int → boolean, extra JSON → flat)"""
    d = {}
    for key in row.keys():
        if key in ("id", "created_at"):
            continue
        val = row[key]
        if val is None:
            continue
        if key == "partial_exited":
            d[key] = bool(val)
        elif key == "extra":
            try:
                extras = json.loads(val) if val else {}
                d.update(extras)
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            d[key] = val
    return d


def load_positions_db() -> list[dict]:
    """从 SQLite 加载全部持仓"""
    init_db()
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
    return [_row_to_pos(r) for r in rows]


def save_position_entry(p: dict) -> bool:
    """原子写入一条持仓记录 (INSERT OR IGNORE, 返回是否新增)"""
    init_db()
    conn = _get_conn()
    row = _pos_to_row(p)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO positions
               (code, name, strategy, entry_price, entry_date, entry_time,
                score, reason, status, holding_days, highest_price, atr,
                partial_exited, remaining_ratio, extra)
               VALUES (:code, :name, :strategy, :entry_price, :entry_date,
                       :entry_time, :score, :reason, :status, :holding_days,
                       :highest_price, :atr, :partial_exited,
                       :remaining_ratio, :extra)""",
            row,
        )
        conn.commit()
        return conn.total_changes > 0
    except Exception as e:
        conn.rollback()
        logger.error("save_position_entry 失败: %s", e)
        return False


def update_positions_batch(updates: list[dict]):
    """原子批量更新持仓 (exit/partial exit/highest_price 等)

    每个 update dict 必须包含 code + entry_date + strategy 作为主键,
    其余字段为要更新的值。
    """
    if not updates:
        return
    init_db()
    conn = _get_conn()
    try:
        for u in updates:
            code = u["code"]
            entry_date = u["entry_date"]
            strategy = u["strategy"]
            # 构建 SET 子句
            fields = {k: v for k, v in u.items()
                      if k not in ("code", "entry_date", "strategy", "id")
                      and k in _POS_COLUMNS}
            if "partial_exited" in fields:
                fields["partial_exited"] = 1 if fields["partial_exited"] else 0
            if not fields:
                continue
            set_clause = ", ".join(f"{k} = :{k}" for k in fields)
            fields["_code"] = code
            fields["_entry_date"] = entry_date
            fields["_strategy"] = strategy
            conn.execute(
                f"UPDATE positions SET {set_clause} "
                "WHERE code = :_code AND entry_date = :_entry_date "
                "AND strategy = :_strategy",
                fields,
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("update_positions_batch 失败: %s", e)
        raise


def delete_old_positions(days: int = 30) -> int:
    """原子删除 N 天前已退出的记录"""
    init_db()
    conn = _get_conn()
    from datetime import date as _date, timedelta as _td
    cutoff = (_date.today() - _td(days=days)).isoformat()
    try:
        cursor = conn.execute(
            "DELETE FROM positions WHERE status = 'exited' AND exit_date < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("清理 %d 条过期持仓 (%d天前已退出)", deleted, days)
        return deleted
    except Exception as e:
        conn.rollback()
        logger.error("delete_old_positions 失败: %s", e)
        return 0


def migrate_positions_json():
    """一次性将 positions.json 迁移到 SQLite"""
    from json_store import safe_load
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "positions.json")
    positions = safe_load(json_path, default=[])
    if not positions:
        logger.info("positions.json 为空或不存在, 跳过迁移")
        return 0

    init_db()
    conn = _get_conn()
    count = 0
    for p in positions:
        row = _pos_to_row(p)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO positions
                   (code, name, strategy, entry_price, entry_date, entry_time,
                    score, reason, status, holding_days, highest_price, atr,
                    partial_exited, remaining_ratio, exit_price, exit_date,
                    exit_time, exit_reason, pnl_pct, last_exit_reason, extra)
                   VALUES (:code, :name, :strategy, :entry_price, :entry_date,
                           :entry_time, :score, :reason, :status, :holding_days,
                           :highest_price, :atr, :partial_exited,
                           :remaining_ratio, :exit_price, :exit_date,
                           :exit_time, :exit_reason, :pnl_pct,
                           :last_exit_reason, :extra)""",
                row,
            )
            count += 1
        except Exception as e:
            logger.warning("迁移跳过 %s: %s", p.get("code"), e)
    conn.commit()
    logger.info("positions.json → SQLite: %d/%d 条迁移成功", count, len(positions))
    return count


# ================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        run_migration()
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        init_db()
        conn = _get_conn()
        sc = (conn.execute("SELECT COUNT(*) FROM scorecard").fetchone() or (0,))[0]
        ca = (conn.execute("SELECT COUNT(*) FROM conflict_audit").fetchone() or (0,))[0]
        tj = (conn.execute("SELECT COUNT(*) FROM trade_journal").fetchone() or (0,))[0]
        print(f"scorecard: {sc}, conflict_audit: {ca}, trade_journal: {tj}")
    else:
        print("用法:")
        print("  python3 db_store.py migrate  # JSON → SQLite 迁移")
        print("  python3 db_store.py stats    # 查看记录数")
