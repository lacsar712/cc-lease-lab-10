"""失败测乙：互证不得把半退影子误标成已退净。

担保账册里已退冻的指纹是只读归档（影子），不计现行占用；
互证必须交叉核对租约状态机与担保指纹状态机：
- 待生效租约 ↔ 冻结指纹，逐笔对齐；
- 生效/续约租约 ↔ 转正指纹；
- 已取消租约 ↔ 已退冻影子，影子不算占用、也不算退净缺口。

红的判定（旧实现）：互证只按租约状态 COUNT，没有任何担保字段，KeyError。
"""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="guarantee-yi-")
os.environ["数据目录"] = _tmp

from app import db as _db
from app import seed
from app.services import 互证, 担保, 租约, 资源, 说明

_db.库路径 = Path(_tmp) / "租约台.db"
_db.数据目录 = Path(_tmp)


def setup_module():
    _db.库路径 = Path(_tmp) / "租约台.db"
    _db.数据目录 = Path(_tmp)
    seed.初始化库()


def test_互证含担保交叉核对且影子不计占用():
    池键 = "pool-net"
    租约.申领(
        {
            "池键": 池键,
            "租户": "team-yi-shadow",
            "租约号": "ls-yi-01",
            "立即生效": False,
            "租期分钟": 60,
        }
    )
    租约.申领(
        {
            "池键": 池键,
            "租户": "team-yi-keep",
            "租约号": "ls-yi-02",
            "立即生效": False,
            "租期分钟": 60,
        }
    )
    租约.取消("ls-yi-01")

    rep = 互证.跑一次()

    # 读集合改道后，互证必须直接读担保边表，而不是只数租约状态
    assert "冻结担保数" in rep
    assert "转正担保数" in rep
    assert "已退冻影子数" in rep
    assert "待生效租约数" in rep

    # 半退影子单独成集合，不能被当成现行冻结、也不能被当成“已退净”
    assert rep["已退冻影子数"] >= 1
    assert rep["冻结担保数"] == rep["待生效租约数"]

    # 现行冻结集合里绝不能混入已退冻影子
    冻结号 = {r["租约号"] for r in 担保.列表(状态="冻结")}
    assert "ls-yi-01" not in 冻结号
    影子 = 担保.按租约("ls-yi-01")
    assert 影子["状态"] == "已退冻"

    assert rep["是否全部对齐"] is True
    assert "ls-yi-01" not in 说明.现行占用租约号()
    assert "ls-yi-02" in 说明.现行占用租约号()


def test_冻结与租约不一致时互证必须报差异():
    池键 = "pool-db"
    租约.申领(
        {
            "池键": 池键,
            "租户": "team-yi-broken",
            "租约号": "ls-yi-03",
            "立即生效": False,
            "租期分钟": 60,
        }
    )
    # 人为制造账册与租约不一致：直接把指纹置为影子，绕过状态机
    conn = _db.连接()
    try:
        conn.execute(
            "UPDATE 担保账 SET 状态='已退冻' WHERE 租约号=?", ("ls-yi-03",)
        )
        conn.commit()
    finally:
        conn.close()

    rep = 互证.跑一次()
    assert rep["是否全部对齐"] is False
    assert any("担保" in d for d in rep["差异明细"])
