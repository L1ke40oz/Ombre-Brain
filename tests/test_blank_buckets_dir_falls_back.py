from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from utils import load_config


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for name in (
        "OMBRE_BUCKETS_DIR",
        "OMBRE_VAULT_DIR",
        "OMBRE_MEDIA_DIR",
        "OMBRE_MEDIA_ALLOWED_ROOTS",
    ):
        monkeypatch.delenv(name, raising=False)


def _write(tmp_path, mapping):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_buckets_dir_does_not_become_the_working_directory(
    tmp_path, monkeypatch, blank
):
    monkeypatch.chdir(tmp_path)
    config = load_config(_write(tmp_path, {"buckets_dir": blank}))

    assert str(config["buckets_dir"]).strip()
    assert not (tmp_path / "dynamic").exists()
    assert not (tmp_path / "permanent").exists()


def test_a_real_buckets_dir_is_still_honoured(tmp_path):
    wanted = tmp_path / "我的记忆库"
    config = load_config(_write(tmp_path, {"buckets_dir": str(wanted)}))

    assert Path(config["buckets_dir"]) == wanted
    assert (wanted / "dynamic").is_dir()


def test_media_dir_follows_the_repaired_buckets_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config(_write(tmp_path, {"buckets_dir": ""}))

    assert os.path.commonpath(
        [str(config["media_dir"]), str(config["buckets_dir"])]
    ) == str(config["buckets_dir"])


def test_media_allowed_roots_defaults_to_empty(tmp_path, monkeypatch):
    """没配就是没配：默认白名单只有系统临时目录，一个额外根都不加。

    这条锚定的是「新入口不改变默认行为」——不配环境变量的部署，安全口径
    和加这个功能之前完全一致。
    """
    monkeypatch.chdir(tmp_path)
    config = load_config(_write(tmp_path, {"buckets_dir": str(tmp_path / "b")}))

    assert config["media_allowed_roots"] == []


def test_media_allowed_roots_parses_comma_separated_env(tmp_path, monkeypatch):
    """逗号分隔、逐项 strip、空项丢弃。

    为什么要 strip 且丢空项：这个值通常写在 .env 或 compose 里，人手换行
    缩进很常见，`" a , b "` split 出来会带上空格和空串。空串进白名单虽然
    匹配不到任何真实路径，但会让报错文案里的白名单列表多出一行空白，
    排查时容易看错。
    """
    monkeypatch.chdir(tmp_path)
    客户端目录 = tmp_path / "客户端媒体"
    另一块盘 = tmp_path / "另一块盘"
    monkeypatch.setenv(
        "OMBRE_MEDIA_ALLOWED_ROOTS",
        f" {客户端目录} , ,{另一块盘},   ",
    )

    config = load_config(_write(tmp_path, {"buckets_dir": str(tmp_path / "b")}))

    assert config["media_allowed_roots"] == [str(客户端目录), str(另一块盘)]


def test_media_allowed_roots_can_come_from_config_yaml(tmp_path, monkeypatch):
    """没有 docker 的本地部署靠这条：直接写 config.yaml，不用碰系统环境变量。

    列表和逗号字符串两种写法都认——yaml 里手写列表容易漏引号，写成一行
    逗号串更省事，没理由只支持其中一种。
    """
    monkeypatch.chdir(tmp_path)
    目录甲 = str(tmp_path / "客户端媒体")
    目录乙 = str(tmp_path / "另一块盘")

    列表版 = load_config(_write(tmp_path, {"media_allowed_roots": [目录甲, 目录乙]}))
    assert 列表版["media_allowed_roots"] == [目录甲, 目录乙]

    字符串版 = load_config(_write(tmp_path, {"media_allowed_roots": f"{目录甲},{目录乙}"}))
    assert 字符串版["media_allowed_roots"] == [目录甲, 目录乙]


def test_media_allowed_roots_env_overrides_config_yaml(tmp_path, monkeypatch):
    """优先级要和本函数其它配置项一致：env > config.yaml。

    不一致的话，部署方在 yaml 里写了一份、环境变量里又有一份，生效的是哪份
    就变成需要读源码才能回答的问题。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OMBRE_MEDIA_ALLOWED_ROOTS", str(tmp_path / "来自环境"))

    config = load_config(
        _write(tmp_path, {"media_allowed_roots": [str(tmp_path / "来自yaml")]})
    )

    assert config["media_allowed_roots"] == [str(tmp_path / "来自环境")]
