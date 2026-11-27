"""担保工程：冻结指纹旁路账册。

工程形态（提交前择定）：
- 申领待生效即冻结一笔担保占用，指纹先登记到旁路账册 担保账，池名额写穿占住；
- 激活时指纹「冻结 → 转正」，只迁状态、不重复扣池名额；
- 取消时指纹「冻结 → 已退冻」，与池名额回放在同一事务内双写两轨；
- 退冻是带状态条件的原子更新（必须仍为冻结），重复退冻拒回刷；
  已退冻行作为只读影子归档，不计现行占用。

读集合改道：现行占用判断一律以担保闭环后的指纹状态为准，
不再走「按租约状态合并 COUNT」的旧查询。
"""
from __future__ import annotations

import uuid

from app.db import 连接
from app.services import 校验

冻结 = "冻结"
转正 = "转正"
已退冻 = "已退冻"


def _留痕(conn, 操作: str, 租约号: str, 池键: str, 详情: str = "") -> None:
    conn.execute(
        "INSERT INTO 操作留痕(时刻,操作,租约号,池键,详情) VALUES (?,?,?,?,?)",
        (校验.此刻(), 操作, 租约号, 池键, 详情),
    )


def 登记冻结(conn, 租约号: str, 池键: str, 详情: str = "") -> dict:
    """在调用方事务内登记一笔冻结指纹。指纹先入账，再由调用方写穿池占用。"""
    指纹 = f"gz-{uuid.uuid4().hex}"
    现在 = 校验.此刻()
    conn.execute(
        """INSERT INTO 担保账(指纹,租约号,池键,状态,冻结时,详情)
           VALUES (?,?,?,?,?,?)""",
        (指纹, 租约号, 池键, 冻结, 现在, 详情),
    )
    _留痕(conn, "担保冻结", 租约号, 池键, 指纹)
    return {"指纹": 指纹, "租约号": 租约号, "池键": 池键, "状态": 冻结}


def 转正指纹(conn, 租约号: str) -> dict:
    """激活时冻结转正。仅冻结指纹可转正，幂等拒绝重复转正。"""
    row = conn.execute("SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)).fetchone()
    if not row:
        raise ValueError("无担保冻结记录，无法转正")
    if row["状态"] == 转正:
        raise ValueError("担保已转正，禁止重复转正")
    if row["状态"] != 冻结:
        raise ValueError(f"担保状态为{row['状态']}，不可转正")
    现在 = 校验.此刻()
    cur = conn.execute(
        "UPDATE 担保账 SET 状态=?, 转正时=? WHERE 租约号=? AND 状态=?",
        (转正, 现在, 租约号, 冻结),
    )
    if cur.rowcount != 1:
        raise ValueError("担保转正冲突，状态已被并发改动")
    _留痕(conn, "担保转正", 租约号, row["池键"], row["指纹"])
    return dict(
        conn.execute("SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)).fetchone()
    )


def 退冻指纹(conn, 租约号: str) -> dict:
    """取消时退净担保。条件原子更新，重复退冻一律拒回刷。

    返回 (账册行, 池键)；仅当本次真正退冻时返回，已退冻/已转正均抛错，
    调用方据此决定是否回补池名额，保证不会双扣。
    """
    row = conn.execute("SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)).fetchone()
    if not row:
        raise ValueError("无担保冻结记录，无法退冻")
    if row["状态"] == 已退冻:
        raise ValueError("担保已退冻，拒绝重复回刷")
    if row["状态"] == 转正:
        raise ValueError("担保已转正，须走回收释放，不能退冻")
    现在 = 校验.此刻()
    cur = conn.execute(
        """UPDATE 担保账
           SET 状态=?, 退冻时=?, 退冻次数=退冻次数+1
           WHERE 租约号=? AND 状态=?""",
        (已退冻, 现在, 租约号, 冻结),
    )
    if cur.rowcount != 1:
        # 并发下另一侧已先退净：拒回刷，不允许再动池名额
        raise ValueError("担保退冻冲突，该笔已被处置")
    _留痕(conn, "担保退冻", 租约号, row["池键"], row["指纹"])
    return dict(
        conn.execute("SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)).fetchone()
    )


def 退转正指纹(conn, 租约号: str) -> dict:
    """回收专用：转正指纹随池释放结转为已退冻影子。

    与取消路径的冻结退冻区分——这里指纹早已转正，回收时归档，
    同样以条件原子更新保证只结转一次。
    """
    row = conn.execute("SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)).fetchone()
    if not row:
        raise ValueError("无担保记录，无法回收结转")
    if row["状态"] == 已退冻:
        raise ValueError("担保已归档，禁止重复结转")
    现在 = 校验.此刻()
    cur = conn.execute(
        """UPDATE 担保账
           SET 状态=?, 退冻时=?, 退冻次数=退冻次数+1
           WHERE 租约号=? AND 状态=?""",
        (已退冻, 现在, 租约号, 转正),
    )
    if cur.rowcount != 1:
        raise ValueError("担保回收结转冲突，状态已被并发改动")
    _留痕(conn, "担保回收结转", 租约号, row["池键"], row["指纹"])
    return dict(
        conn.execute("SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)).fetchone()
    )


def 按租约(租约号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute(
            "SELECT * FROM 担保账 WHERE 租约号=?", (租约号,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def 列表(状态: str | None = None) -> list:
    """读集合：按担保闭环后的指纹状态取数，与租约状态合并查询彻底改道。"""
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 担保账 WHERE 状态=? ORDER BY 冻结时 DESC", (状态,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 担保账 ORDER BY 冻结时 DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 现行占用租约号() -> set:
    """担保闭环后仍占着池名额的租约：冻结 + 转正。已退冻影子不在其中。"""
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 租约号 FROM 担保账 WHERE 状态 IN (?, ?)", (冻结, 转正)
        ).fetchall()
        return {r["租约号"] for r in rows}
    finally:
        conn.close()


def 计数(状态: str) -> int:
    conn = 连接()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM 担保账 WHERE 状态=?", (状态,)
        ).fetchone()[0]
    finally:
        conn.close()
