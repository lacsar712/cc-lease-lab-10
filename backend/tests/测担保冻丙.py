"""争用失败测丙：两名操作员同时取消同一笔待生效租约。

不加锁、不靠指纹条件更新时，两侧各退一次，池名额被双扣、占用互盖。
正确形态：冻结指纹的退冻是条件原子更新（状态必须仍为冻结），
只有一侧能退净，另一侧被拒回刷，池已占只回落一格。

红的判定（旧实现）：无取消入口 / 无担保账册，直接 AttributeError。
"""
import os
import tempfile
import threading
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="guarantee-bing-")
os.environ["数据目录"] = _tmp

from app import db as _db
from app import seed
from app.services import 担保, 租约, 资源, 说明

_db.库路径 = Path(_tmp) / "租约台.db"
_db.数据目录 = Path(_tmp)


def setup_module():
    _db.库路径 = Path(_tmp) / "租约台.db"
    _db.数据目录 = Path(_tmp)
    seed.初始化库()


def test_并发取消同一待生效只退一次():
    池键 = "pool-compute"
    取消前 = 资源.一条(池键)["已占"]

    租约.申领(
        {
            "池键": 池键,
            "租户": "team-bing",
            "租约号": "ls-bing-01",
            "立即生效": False,
            "租期分钟": 60,
        }
    )
    assert 资源.一条(池键)["已占"] == 取消前 + 1

    起跑 = threading.Barrier(2)
    结果 = []
    错误 = []

    def 操作员():
        try:
            起跑.wait()
            结果.append(租约.取消("ls-bing-01"))
        except ValueError as e:
            错误.append(str(e))

    t1 = threading.Thread(target=操作员)
    t2 = threading.Thread(target=操作员)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 恰好一侧成功、一侧被拒回刷
    assert len(结果) == 1
    assert len(错误) == 1
    assert 结果[0]["状态"] == "已取消"

    # 池名额只回落一格，绝不能双扣
    assert 资源.一条(池键)["已占"] == 取消前

    # 担保账只有一笔指纹，且已退净，无重复回刷行
    账 = 担保.按租约("ls-bing-01")
    assert 账["状态"] == "已退冻"
    conn = _db.连接()
    try:
        行数 = conn.execute(
            "SELECT COUNT(*) FROM 担保账 WHERE 租约号=?", ("ls-bing-01",)
        ).fetchone()[0]
        退冻笔数 = conn.execute(
            "SELECT COALESCE(SUM(退冻次数),0) FROM 担保账 WHERE 租约号=?",
            ("ls-bing-01",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert 行数 == 1
    assert 退冻笔数 == 1

    assert "ls-bing-01" not in 说明.现行占用租约号()
