from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 用户 (
  账号 TEXT PRIMARY KEY,
  密码哈希 TEXT NOT NULL,
  角色 TEXT NOT NULL DEFAULT '管理员'
);
CREATE TABLE IF NOT EXISTS 租账规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 资源池 (
  池键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL,
  容量 INTEGER NOT NULL DEFAULT 100,
  已占 INTEGER NOT NULL DEFAULT 0,
  启用 INTEGER NOT NULL DEFAULT 1,
  说明 TEXT NOT NULL DEFAULT '',
  更新时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 租约 (
  租约号 TEXT PRIMARY KEY,
  池键 TEXT NOT NULL,
  租户 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '待生效',
  申领时 TEXT NOT NULL,
  生效时 TEXT NOT NULL DEFAULT '',
  到期时刻 TEXT NOT NULL,
  续约次数 INTEGER NOT NULL DEFAULT 0,
  更新时 TEXT NOT NULL,
  FOREIGN KEY (池键) REFERENCES 资源池(池键)
);
CREATE TABLE IF NOT EXISTS 心跳 (
  心跳号 TEXT PRIMARY KEY,
  租约号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  结果 TEXT NOT NULL DEFAULT '成功',
  延迟毫秒 INTEGER NOT NULL DEFAULT 0,
  说明 TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (租约号) REFERENCES 租约(租约号)
);
CREATE TABLE IF NOT EXISTS 回收匣 (
  回收号 TEXT PRIMARY KEY,
  租约号 TEXT NOT NULL,
  池键 TEXT NOT NULL,
  租户 TEXT NOT NULL,
  原因 TEXT NOT NULL DEFAULT '到期未续',
  状态 TEXT NOT NULL DEFAULT '待回收',
  入匣时 TEXT NOT NULL,
  处置时 TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (租约号) REFERENCES 租约(租约号),
  FOREIGN KEY (池键) REFERENCES 资源池(池键)
);
CREATE TABLE IF NOT EXISTS 互证报告 (
  报告号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  结论 TEXT NOT NULL,
  差异摘要 TEXT NOT NULL DEFAULT '',
  租约总数 INTEGER NOT NULL,
  生效中数 INTEGER NOT NULL,
  待回收数 INTEGER NOT NULL,
  池已占合计 INTEGER NOT NULL,
  是否对齐 INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS 操作留痕 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  操作 TEXT NOT NULL,
  租约号 TEXT NOT NULL DEFAULT '',
  池键 TEXT NOT NULL DEFAULT '',
  详情 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 担保账 (
  指纹 TEXT PRIMARY KEY,
  租约号 TEXT NOT NULL UNIQUE,
  池键 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '冻结',
  冻结时 TEXT NOT NULL,
  转正时 TEXT NOT NULL DEFAULT '',
  退冻时 TEXT NOT NULL DEFAULT '',
  退冻次数 INTEGER NOT NULL DEFAULT 0,
  详情 TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (租约号) REFERENCES 租约(租约号),
  FOREIGN KEY (池键) REFERENCES 资源池(池键)
);
CREATE INDEX IF NOT EXISTS idx_担保账_状态 ON 担保账(状态);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _留痕(conn, 操作: str, 租约号: str = "", 池键: str = "", 详情: str = "") -> None:
    conn.execute(
        "INSERT INTO 操作留痕(时刻,操作,租约号,池键,详情) VALUES (?,?,?,?,?)",
        (此刻(), 操作, 租约号, 池键, 详情),
    )


def 初始化库() -> None:
    conn = 连接()
    try:
        conn.executescript(建表)
        n = conn.execute("SELECT COUNT(*) FROM 用户").fetchone()[0]
        if n == 0:
            conn.execute(
                "INSERT INTO 用户(账号,密码哈希,角色) VALUES (?,?,?)",
                ("admin", "123456", "管理员"),
            )
            规 = [
                ("默认租期分钟", "120"),
                ("心跳宽限分钟", "15"),
                ("回收策略", "到期进匣待处置"),
                ("允许超额申领", "0"),
            ]
            for 键, 值 in 规:
                conn.execute("INSERT INTO 租账规(键,值) VALUES (?,?)", (键, 值))
            t0 = datetime.now(timezone.utc)
            def iso(dt):
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            # 池初始已占一律为 0：占用只能由担保冻结写穿产生，
            # 下方播种租约后再按真实未结租约回算，杜绝与台账脱钩的历史数字。
            池们 = [
                ("pool-compute", "计算槽池", 64, 0, 1, "GPU 切片共享池"),
                ("pool-storage", "对象存储池", 200, 0, 1, "温存桶配额"),
                ("pool-net", "出口带宽池", 80, 0, 1, "跨区带宽租约"),
                ("pool-db", "只读连接池", 32, 0, 1, "分析库连接"),
                ("pool-msg", "消息主题池", 120, 0, 0, "维护中暂禁申领"),
            ]
            for 池键, 名称, 容量, 已占, 启用, 说明 in 池们:
                conn.execute(
                    """INSERT INTO 资源池(池键,名称,容量,已占,启用,说明,更新时)
                       VALUES (?,?,?,?,?,?,?)""",
                    (池键, 名称, 容量, 已占, 启用, 说明, iso(t0)),
                )

            租约样 = [
                (
                    "ls-active-01",
                    "pool-compute",
                    "team-ml",
                    "生效中",
                    iso(t0 - timedelta(hours=2)),
                    iso(t0 - timedelta(hours=2)),
                    iso(t0 + timedelta(hours=1)),
                    2,
                ),
                (
                    "ls-wait-02",
                    "pool-storage",
                    "team-etl",
                    "待生效",
                    iso(t0 - timedelta(minutes=30)),
                    "",
                    iso(t0 + timedelta(hours=3)),
                    0,
                ),
                (
                    "ls-renew-03",
                    "pool-net",
                    "svc-gateway",
                    "已续约",
                    iso(t0 - timedelta(days=1)),
                    iso(t0 - timedelta(days=1)),
                    iso(t0 + timedelta(minutes=40)),
                    5,
                ),
                (
                    "ls-over-04",
                    "pool-db",
                    "biz-report",
                    "生效中",
                    iso(t0 - timedelta(hours=5)),
                    iso(t0 - timedelta(hours=5)),
                    iso(t0 - timedelta(minutes=20)),
                    1,
                ),
            ]
            for row in 租约样:
                conn.execute(
                    """INSERT INTO 租约(租约号,池键,租户,状态,申领时,生效时,到期时刻,续约次数,更新时)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (*row, iso(t0)),
                )

            conn.execute(
                """INSERT INTO 心跳(心跳号,租约号,时刻,结果,延迟毫秒,说明) VALUES (?,?,?,?,?,?)""",
                (
                    "hb-0001",
                    "ls-active-01",
                    iso(t0 - timedelta(minutes=5)),
                    "成功",
                    42,
                    "定时续约",
                ),
            )
            conn.execute(
                """INSERT INTO 心跳(心跳号,租约号,时刻,结果,延迟毫秒,说明) VALUES (?,?,?,?,?,?)""",
                (
                    "hb-0002",
                    "ls-renew-03",
                    iso(t0 - timedelta(minutes=2)),
                    "成功",
                    38,
                    "宽限内续命",
                ),
            )
            conn.execute(
                """INSERT INTO 租约(租约号,池键,租户,状态,申领时,生效时,到期时刻,续约次数,更新时)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "ls-old-99",
                    "pool-compute",
                    "team-legacy",
                    "生效中",
                    iso(t0 - timedelta(days=2)),
                    iso(t0 - timedelta(days=2)),
                    iso(t0 - timedelta(hours=8)),
                    0,
                    iso(t0 - timedelta(hours=6)),
                ),
            )
            conn.execute(
                """INSERT INTO 回收匣(回收号,租约号,池键,租户,原因,状态,入匣时,处置时) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "rc-9001",
                    "ls-old-99",
                    "pool-compute",
                    "team-legacy",
                    "心跳超时",
                    "待回收",
                    iso(t0 - timedelta(hours=6)),
                    "",
                ),
            )
            conn.execute(
                """INSERT INTO 互证报告(时刻,结论,差异摘要,租约总数,生效中数,待回收数,池已占合计,是否对齐) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    iso(t0 - timedelta(hours=1)),
                    "池占用与生效租约基本一致",
                    "消息主题池禁用但无生效租约",
                    4,
                    2,
                    1,
                    95,
                    1,
                ),
            )
            _留痕(conn, "系统播种", 详情="初始资源池与样例租约")

        # 担保工程上线：为存量未结租约补建冻结/转正指纹，
        # 使旧库的担保边表与租约台账、池占用从上线时刻即对齐。
        存量 = conn.execute(
            """SELECT l.租约号, l.池键, l.状态, l.申领时 FROM 租约 l
               LEFT JOIN 担保账 g ON l.租约号=g.租约号
               WHERE g.指纹 IS NULL
                 AND l.状态 IN ('待生效','生效中','已续约')"""
        ).fetchall()
        import uuid as _uuid

        for r in 存量:
            指纹 = f"gz-seed-{_uuid.uuid4().hex[:8]}"
            if r["状态"] == "待生效":
                担保状态, 转正时 = "冻结", ""
            else:
                担保状态, 转正时 = "转正", r["申领时"]
            conn.execute(
                """INSERT OR IGNORE INTO 担保账(指纹,租约号,池键,状态,冻结时,转正时,详情)
                   VALUES (?,?,?,?,?,?,?)""",
                (指纹, r["租约号"], r["池键"], 担保状态, r["申领时"], 转正时, "存量补建"),
            )

        # 池主表已占按担保边表现行指纹（冻结+转正）回算，双写两轨对齐
        占用 = conn.execute(
            """SELECT 池键, COUNT(*) AS c FROM 担保账
               WHERE 状态 IN ('冻结','转正') GROUP BY 池键"""
        ).fetchall()
        占用映射 = {r["池键"]: r["c"] for r in 占用}
        for 池键, in conn.execute("SELECT 池键 FROM 资源池").fetchall():
            conn.execute(
                "UPDATE 资源池 SET 已占=? WHERE 池键=?",
                (占用映射.get(池键, 0), 池键),
            )
        conn.commit()
    finally:
        conn.close()