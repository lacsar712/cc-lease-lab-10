from __future__ import annotations

from app.db import 连接
from app.services import 担保, 校验, 说明


def 跑一次() -> dict:
    conn = 连接()
    try:
        租约总数 = conn.execute("SELECT COUNT(*) FROM 租约").fetchone()[0]
        生效 = conn.execute(
            "SELECT COUNT(*) FROM 租约 WHERE 状态 IN ('生效中','已续约')"
        ).fetchone()[0]
        待回收 = conn.execute("SELECT COUNT(*) FROM 回收匣 WHERE 状态='待回收'").fetchone()[0]
        池已占合计 = conn.execute(
            "SELECT COALESCE(SUM(已占),0) FROM 资源池"
        ).fetchone()[0]

        # 读集合改道：现行占用不再按租约状态合并 COUNT，
        # 一律以担保闭环后的指纹状态为准（冻结+转正）。
        待生效租约数 = conn.execute(
            "SELECT COUNT(*) FROM 租约 WHERE 状态='待生效'"
        ).fetchone()[0]
        生效租约数 = conn.execute(
            "SELECT COUNT(*) FROM 租约 WHERE 状态 IN ('生效中','已续约')"
        ).fetchone()[0]
        已取消租约数 = conn.execute(
            "SELECT COUNT(*) FROM 租约 WHERE 状态='已取消'"
        ).fetchone()[0]

        冻结担保数 = conn.execute(
            "SELECT COUNT(*) FROM 担保账 WHERE 状态=?", (担保.冻结,)
        ).fetchone()[0]
        转正担保数 = conn.execute(
            "SELECT COUNT(*) FROM 担保账 WHERE 状态=?", (担保.转正,)
        ).fetchone()[0]
        # 半退影子：已退冻指纹只读归档，不计现行占用，也不能被误标成已退净
        已退冻影子数 = conn.execute(
            "SELECT COUNT(*) FROM 担保账 WHERE 状态=?", (担保.已退冻,)
        ).fetchone()[0]
        担保现行 = 冻结担保数 + 转正担保数

        差异 = []

        # 交叉核对一：池主表占用合计 == 担保边表现行指纹数（双写两轨对账）
        if int(池已占合计) != int(担保现行):
            差异.append(
                f"池已占合计 {池已占合计} 与担保现行占用 {担保现行} 不一致（双写两轨错位）"
            )

        # 交叉核对二：租约状态机与担保指纹状态机逐态对齐
        if int(冻结担保数) != int(待生效租约数):
            差异.append(
                f"担保冻结数 {冻结担保数} 与待生效租约数 {待生效租约数} 不一致"
            )
        if int(转正担保数) != int(生效租约数):
            差异.append(
                f"担保转正数 {转正担保数} 与生效租约数 {生效租约数} 不一致"
            )

        # 交叉核对三：逐笔指纹与租约状态错配（半退影子误标即在此现形）
        错配 = conn.execute(
            """SELECT g.租约号, g.状态 AS 担保状态, l.状态 AS 租约状态
               FROM 担保账 g JOIN 租约 l ON g.租约号=l.租约号
               WHERE (g.状态=? AND l.状态!='待生效')
                  OR (g.状态=? AND l.状态 NOT IN ('生效中','已续约'))
                  OR (g.状态=? AND l.状态 NOT IN ('已取消','已回收'))""",
            (担保.冻结, 担保.转正, 担保.已退冻),
        ).fetchall()
        for r in 错配:
            差异.append(
                f"担保状态错配: {r['租约号']} 担保={r['担保状态']} 租约={r['租约状态']}"
            )

        # 无指纹的未结租约（申领漏登记冻结）
        漏冻 = conn.execute(
            """SELECT l.租约号 FROM 租约 l
               LEFT JOIN 担保账 g ON l.租约号=g.租约号
               WHERE l.状态 IN ('待生效','生效中','已续约') AND g.指纹 IS NULL"""
        ).fetchall()
        for r in 漏冻:
            差异.append(f"租约缺担保指纹: {r['租约号']}")

        禁用池租约 = conn.execute(
            """SELECT l.租约号 FROM 租约 l JOIN 资源池 p ON l.池键=p.池键
               WHERE p.启用=0 AND l.状态 IN ('生效中','已续约')"""
        ).fetchall()
        if 禁用池租约:
            差异.append(
                "禁用池仍有生效租约: " + ",".join(r["租约号"] for r in 禁用池租约)
            )
        待生效过期 = conn.execute(
            """SELECT 租约号 FROM 租约 WHERE 状态='待生效'
               AND 到期时刻 < datetime('now')"""
        ).fetchall()
        if 待生效过期:
            差异.append("待生效但已过期: " + ",".join(r["租约号"] for r in 待生效过期))

        对齐 = len(差异) == 0
        结论 = "租账互证通过" if 对齐 else "租账互证发现差异"
        摘要 = "；".join(差异) if 差异 else "担保边表与资源池占用、租约台账一致"
        时刻 = 校验.此刻()
        conn.execute(
            """INSERT INTO 互证报告(时刻,结论,差异摘要,租约总数,生效中数,待回收数,池已占合计,是否对齐)
               VALUES (?,?,?,?,?,?,?,?)""",
            (时刻, 结论, 摘要, 租约总数, 生效, 待回收, 池已占合计, 1 if 对齐 else 0),
        )
        报告号 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO 操作留痕(时刻,操作,详情) VALUES (?,?,?)",
            (时刻, "跑租账互证", 摘要),
        )
        conn.commit()
        return {
            "报告号": 报告号,
            "时刻": 时刻,
            "结论": 结论,
            "差异摘要": 摘要,
            "差异明细": 差异,
            "是否全部对齐": 对齐,
            "租约总数": 租约总数,
            "生效中数": 生效,
            "待回收数": 待回收,
            "池已占合计": 池已占合计,
            "待生效租约数": 待生效租约数,
            "生效租约数": 生效租约数,
            "已取消租约数": 已取消租约数,
            "冻结担保数": 冻结担保数,
            "转正担保数": 转正担保数,
            "已退冻影子数": 已退冻影子数,
            "担保现行占用": 担保现行,
        }
    finally:
        conn.close()
