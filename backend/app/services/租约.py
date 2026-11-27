from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.db import 连接
from app.services import 担保, 资源, 校验, 说明


def _默认租期分钟() -> int:
    规 = 说明.租账规()
    try:
        return max(5, int(规.get("默认租期分钟", "120")))
    except ValueError:
        return 120


def _留痕(conn, 操作, 租约号="", 池键="", 详情=""):
    conn.execute(
        "INSERT INTO 操作留痕(时刻,操作,租约号,池键,详情) VALUES (?,?,?,?,?)",
        (校验.此刻(), 操作, 租约号, 池键, 详情),
    )


def 申领(body: dict) -> dict:
    池键 = 校验.池键(body.get("池键"))
    租户 = 校验.租户(body.get("租户"))
    租约号 = str(body.get("租约号") or f"ls-{uuid.uuid4().hex[:10]}")
    租约号 = 校验.租约号(租约号)
    分钟 = int(body.get("租期分钟") or _默认租期分钟())
    分钟 = 校验.正整数("租期分钟", 分钟, 下限=5, 上限=60 * 24 * 30)

    conn = 连接()
    try:
        if conn.execute("SELECT 1 FROM 租约 WHERE 租约号=?", (租约号,)).fetchone():
            raise ValueError("租约号已存在")
        现在 = datetime.now(timezone.utc)
        到期 = 现在 + timedelta(minutes=分钟)
        iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        生效 = bool(body.get("立即生效", True))
        状态 = "生效中" if 生效 else "待生效"
        # 退占双写两轨：池名额写穿与担保指纹登记必须同一事务，
        # 待生效先冻结一笔担保占用，激活转正、取消退冻。
        资源._预占(conn, 池键)
        conn.execute(
            """INSERT INTO 租约(租约号,池键,租户,状态,申领时,生效时,到期时刻,续约次数,更新时)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                租约号,
                池键,
                租户,
                状态,
                iso(现在),
                iso(现在) if 生效 else "",
                iso(到期),
                0,
                iso(现在),
            ),
        )
        if 生效:
            担保.登记冻结(conn, 租约号, 池键, "申领即生效")
            担保.转正指纹(conn, 租约号)
        else:
            担保.登记冻结(conn, 租约号, 池键, "待生效担保冻结")
        _留痕(conn, "申领租约", 租约号, 池键, 租户)
        conn.commit()
        return 说明.租约一条(租约号)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def 激活(租约号: str) -> dict:
    租约号 = 校验.租约号(租约号)
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 租约 WHERE 租约号=?", (租约号,)).fetchone()
        if not row:
            raise ValueError("无此租约")
        if row["状态"] != "待生效":
            raise ValueError("仅待生效租约可激活")
        现在 = 校验.此刻()
        # 冻结转正：只迁指纹状态，池名额早在申领冻结时写穿，不得再扣一次
        担保.转正指纹(conn, 租约号)
        conn.execute(
            "UPDATE 租约 SET 状态='生效中', 生效时=?, 更新时=? WHERE 租约号=?",
            (现在, 现在, 租约号),
        )
        _留痕(conn, "激活租约", 租约号, row["池键"])
        conn.commit()
        return 说明.租约一条(租约号)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def 取消(租约号: str) -> dict:
    """取消待生效：退净担保占用并回补池名额，骨签即取消必须退净。

    担保退冻是带状态条件的原子更新，并发双取消只有一侧成功，
    另一侧因指纹已非冻结而拒回刷，池名额保证只回落一格。
    """
    租约号 = 校验.租约号(租约号)
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 租约 WHERE 租约号=?", (租约号,)).fetchone()
        if not row:
            raise ValueError("无此租约")
        if row["状态"] != "待生效":
            raise ValueError("仅待生效租约可取消")
        池键 = row["池键"]
        # 先退指纹（条件更新，重复/并发退冻在此被拒），成功后才回补池名额
        担保.退冻指纹(conn, 租约号)
        资源._释放(conn, 池键)
        现在 = 校验.此刻()
        conn.execute(
            "UPDATE 租约 SET 状态='已取消', 更新时=? WHERE 租约号=?",
            (现在, 租约号),
        )
        _留痕(conn, "取消租约", 租约号, 池键, "担保已退冻，池名额已回补")
        conn.commit()
        return 说明.租约一条(租约号)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def 标记回收(租约号: str, conn=None) -> dict:
    """标记回收。允许复用调用方连接（回收确认场景），避免同线程嵌套连接自锁。"""
    租约号 = 校验.租约号(租约号)
    自有连接 = conn is None
    if 自有连接:
        conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 租约 WHERE 租约号=?", (租约号,)).fetchone()
        if not row:
            raise ValueError("无此租约")
        if row["状态"] == "已回收":
            return dict(row)
        池键 = row["池键"]
        conn.execute(
            "UPDATE 租约 SET 状态='已回收', 更新时=? WHERE 租约号=?",
            (校验.此刻(), 租约号),
        )
        # 回收释放与担保结转同事务：转正指纹转为已退冻影子，池名额回补
        账 = conn.execute(
            "SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)
        ).fetchone()
        if 账 and 账["状态"] == 担保.转正:
            担保.退转正指纹(conn, 租约号)
        资源._释放(conn, 池键)
        _留痕(conn, "租约已回收", 租约号, 池键)
        if 自有连接:
            conn.commit()
        return 说明.租约一条(租约号)
    except Exception:
        if 自有连接:
            conn.rollback()
        raise
    finally:
        if 自有连接:
            conn.close()


def 扫描逾期() -> list:
    """将已过宽限的生效租约送入回收匣，返回处理列表。"""
    规 = 说明.租账规()
    try:
        宽限 = int(规.get("心跳宽限分钟", "15"))
    except ValueError:
        宽限 = 15
    conn = 连接()
    out = []
    try:
        rows = conn.execute(
            "SELECT * FROM 租约 WHERE 状态 IN ('生效中','已续约')"
        ).fetchall()
        for row in rows:
            if not 校验.是否到期(row["到期时刻"], 宽限):
                continue
            from app.services import 回收

            item = 回收.入匣(
                {
                    "租约号": row["租约号"],
                    "原因": "到期未续",
                }
            )
            标记回收(row["租约号"])
            out.append(item)
        return out
    finally:
        conn.close()