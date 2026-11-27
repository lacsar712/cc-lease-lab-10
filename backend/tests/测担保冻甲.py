"""失败测甲：取消待生效后，担保占用必须退净，池名额同步释放；激活则冻结转正。

红的判定（旧实现）：
- 没有取消入口 / 没有担保账册，调用即 AttributeError、KeyError；
- 取消后池已占不回落、担保指纹仍挂冻结；
- 重复取消会再扣一次池名额。
"""
import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="guarantee-jia-")
os.environ["数据目录"] = _tmp

from app import db as _db
from app import seed
from app.services import 互证, 担保, 租约, 资源, 说明

_db.库路径 = Path(_tmp) / "租约台.db"
# 每个测试模块独占一份库，避免与其他模块的人为错配数据互相污染
_db.数据目录 = Path(_tmp)


def setup_module():
    # 后导入的测试模块会改写全局库路径，这里在本模块开跑前夺回自己的库
    _db.库路径 = Path(_tmp) / "租约台.db"
    _db.数据目录 = Path(_tmp)
    seed.初始化库()


def test_取消待生效退净担保与池占用():
    池键 = "pool-compute"
    取消前 = 资源.一条(池键)["已占"]

    ev = 租约.申领(
        {
            "池键": 池键,
            "租户": "team-jia",
            "租约号": "ls-jia-01",
            "立即生效": False,
            "租期分钟": 60,
        }
    )
    assert ev["状态"] == "待生效"
    # 申领即冻结一笔担保占用，池名额先占住
    冻账 = 担保.按租约("ls-jia-01")
    assert 冻账 is not None and 冻账["状态"] == "冻结"
    assert 资源.一条(池键)["已占"] == 取消前 + 1

    out = 租约.取消("ls-jia-01")
    assert out["状态"] == "已取消"

    # 骨签：取消必须退净担保占用
    账 = 担保.按租约("ls-jia-01")
    assert 账["状态"] == "已退冻"
    assert 资源.一条(池键)["已占"] == 取消前

    # 读集合改道：现行占用集合里不得再看见这笔
    assert "ls-jia-01" not in 说明.现行占用租约号()

    # 重复退冻拒回刷，不得二次扣减池名额
    with pytest.raises(ValueError):
        租约.取消("ls-jia-01")
    assert 资源.一条(池键)["已占"] == 取消前


def test_激活待生效冻结转正不重复扣占用():
    池键 = "pool-storage"
    激活前 = 资源.一条(池键)["已占"]

    租约.申领(
        {
            "池键": 池键,
            "租户": "team-jia-live",
            "租约号": "ls-jia-02",
            "立即生效": False,
            "租期分钟": 60,
        }
    )
    assert 资源.一条(池键)["已占"] == 激活前 + 1
    assert 担保.按租约("ls-jia-02")["状态"] == "冻结"

    租约.激活("ls-jia-02")

    assert 担保.按租约("ls-jia-02")["状态"] == "转正"
    # 转正只是指纹状态迁移，池名额不允许再扣一次
    assert 资源.一条(池键)["已占"] == 激活前 + 1
    assert "ls-jia-02" in 说明.现行占用租约号()


def test_互证在取消后仍然对齐():
    rep = 互证.跑一次()
    assert rep["是否全部对齐"] is True


def test_回收确认同事务退净担保不锁库():
    from app.services import 回收

    池键 = "pool-storage"
    前 = 资源.一条(池键)["已占"]
    租约.申领(
        {
            "池键": 池键,
            "租户": "team-jia-reclaim",
            "租约号": "ls-jia-03",
            "立即生效": True,
            "租期分钟": 5,
        }
    )
    assert 担保.按租约("ls-jia-03")["状态"] == "转正"
    assert 资源.一条(池键)["已占"] == 前 + 1

    匣 = 回收.入匣({"租约号": "ls-jia-03", "原因": "测试回收"})
    回收.确认回收(匣["回收号"])

    # 回收同事务完成：池名额回补、转正指纹结转为影子、不发生嵌套连接自锁
    assert 资源.一条(池键)["已占"] == 前
    assert 担保.按租约("ls-jia-03")["状态"] == "已退冻"
    assert 说明.租约一条("ls-jia-03")["状态"] == "已回收"
