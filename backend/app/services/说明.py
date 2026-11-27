from __future__ import annotations

from app.db import 连接
from app.services import 校验


def 租账规() -> dict:
    conn = 连接()
    try:
        return 租账规_连接(conn)
    finally:
        conn.close()


def 租账规_连接(conn) -> dict:
    rows = conn.execute("SELECT 键,值 FROM 租账规").fetchall()
    return {r["键"]: r["值"] for r in rows}


def 改租账规(body: dict) -> dict:
    conn = 连接()
    try:
        for k, v in body.items():
            键 = 校验.非空("键", k)
            值 = 校验.非空("值", v)
            conn.execute(
                "INSERT INTO 租账规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (键, 值),
            )
        conn.commit()
        return 租账规()
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        def c(sql, *a):
            return conn.execute(sql, a).fetchone()[0]

        return {
            "资源池数": c("SELECT COUNT(*) FROM 资源池"),
            "启用池": c("SELECT COUNT(*) FROM 资源池 WHERE 启用=1"),
            "租约总数": c("SELECT COUNT(*) FROM 租约"),
            "待生效": c("SELECT COUNT(*) FROM 租约 WHERE 状态='待生效'"),
            "生效中": c("SELECT COUNT(*) FROM 租约 WHERE 状态 IN ('生效中','已续约')"),
            "已回收": c("SELECT COUNT(*) FROM 租约 WHERE 状态='已回收'"),
            "已取消": c("SELECT COUNT(*) FROM 租约 WHERE 状态='已取消'"),
            "担保冻结": c("SELECT COUNT(*) FROM 担保账 WHERE 状态='冻结'"),
            "担保转正": c("SELECT COUNT(*) FROM 担保账 WHERE 状态='转正'"),
            "担保影子": c("SELECT COUNT(*) FROM 担保账 WHERE 状态='已退冻'"),
            "心跳条数": c("SELECT COUNT(*) FROM 心跳"),
            "回收匣待处置": c("SELECT COUNT(*) FROM 回收匣 WHERE 状态='待回收'"),
            "互证报告数": c("SELECT COUNT(*) FROM 互证报告"),
            "租账规": 租账规(),
        }
    finally:
        conn.close()


def 仓情() -> dict:
    return {
        "主链": "资源池 → 申领租约 → 心跳续约 → 到期回收匣 → 租账互证对齐池占用",
        "领域": "应用开发全栈 · 资源租约台",
        "技术": "FastAPI + 多页原生 JS · 左侧栏冷灰琥珀",
    }


def 资源池列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 资源池 ORDER BY 池键").fetchall()]
    finally:
        conn.close()


_租约列 = ("租约号", "池键", "租户", "状态", "申领时", "生效时", "到期时刻", "续约次数", "更新时")


def _装租约行(row) -> dict:
    # 联查边表后的行拆成租约主体 + 担保子对象；指纹为空即无担保
    data = {k: row[k] for k in _租约列}
    if row["g_指纹"] is None:
        data["担保"] = None
    else:
        data["担保"] = {
            "指纹": row["g_指纹"],
            "担保状态": row["g_担保状态"],
            "冻结时": row["g_冻结时"],
            "转正时": row["g_转正时"],
            "退冻时": row["g_退冻时"],
        }
    return data


_联查sql = (
    "SELECT l.租约号,l.池键,l.租户,l.状态,l.申领时,l.生效时,l.到期时刻,l.续约次数,l.更新时,"
    "g.指纹 AS g_指纹,g.状态 AS g_担保状态,g.冻结时 AS g_冻结时,"
    "g.转正时 AS g_转正时,g.退冻时 AS g_退冻时 "
    "FROM 租约 l LEFT JOIN 担保账 g ON l.租约号=g.租约号"
)


def 租约列表(状态: str | None = None) -> list:
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                _联查sql + " WHERE l.状态=? ORDER BY l.更新时 DESC", (状态,)
            ).fetchall()
        else:
            rows = conn.execute(
                _联查sql + " ORDER BY l.更新时 DESC"
            ).fetchall()
        return [_装租约行(r) for r in rows]
    finally:
        conn.close()


def 租约一条(租约号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute(
            _联查sql + " WHERE l.租约号=?", (租约号,)
        ).fetchone()
        return _装租约行(row) if row else None
    finally:
        conn.close()


def 现行占用租约号() -> set:
    """读集合改道：现行占用只认担保闭环后的指纹（冻结+转正）。

    已退冻影子（半退归档）不在可申/现行集合内，杜绝旧的租约状态合并查询误算。
    """
    from app.services import 担保

    return 担保.现行占用租约号()


def 心跳列表(租约号: str | None = None) -> list:
    conn = 连接()
    try:
        if 租约号:
            rows = conn.execute(
                "SELECT * FROM 心跳 WHERE 租约号=? ORDER BY 时刻 DESC", (租约号,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM 心跳 ORDER BY 时刻 DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 回收列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 回收匣 ORDER BY 入匣时 DESC").fetchall()]
    finally:
        conn.close()


def 互证列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 互证报告 ORDER BY 报告号 DESC").fetchall()]
    finally:
        conn.close()


def 留痕列表() -> list:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute("SELECT * FROM 操作留痕 ORDER BY 编号 DESC LIMIT 80").fetchall()
        ]
    finally:
        conn.close()