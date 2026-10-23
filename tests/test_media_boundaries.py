"""MediaStore 的两条硬边界：路径必须在临时目录内、条数必须先卡再动手。

与 test_media_store.py 的分工：那个验的是正常保存路径，这个验的是拒绝。

两条都来自真机复现：

- `media.path` 原来只查文件类型、符号链接和大小，没有任何路径白名单，
  `..` 和绝对路径畅通无阻——服务器上任何可读文件都能被复制进 vault 变成
  记忆附件。
- 10 万个媒体项会被逐个持久化完（实测 35.9 秒）才由 bucket_manager 的
  `_normalize_media` 截成 20 条。上限一直存在，只是执行在动手之后。
"""

import base64

import pytest

from ombrebrain.storage.media_store import MediaPersistenceError, MediaStore


def _建store(tmp_path):
    return MediaStore(str(tmp_path / "vault"), str(tmp_path / "vault" / "_media"))


def _一项(data="合成媒体内容"):
    原始 = data.encode("utf-8") if isinstance(data, str) else data
    return {"data_base64": base64.b64encode(原始).decode("ascii"),
            "filename": "合成.txt"}


@pytest.mark.asyncio
async def test_临时目录内的路径照常接受(tmp_path):
    """反面用例，必须先立在这里。

    path 这条路本来就是给「客户端刚上传、还躺在服务器临时目录里」的文件用的。
    白名单要是把它们也挡了，等于把功能删掉——pytest 的 tmp_path 正好在系统
    临时目录下，所以这条同时也是对白名单口径的锚定。
    """
    源 = tmp_path / "合成上传.txt"
    源.write_text("合成内容", encoding="utf-8")
    store = _建store(tmp_path)

    结果 = await store.persist("合成桶", [{"path": str(源)}])
    assert 结果[0]["stored"] is True


@pytest.mark.asyncio
async def test_临时目录之外的路径被拒(tmp_path, monkeypatch):
    """把允许根收窄成 vault 自己，再拿 tmp 下的文件去试——它就在允许根之外了。

    不直接拿 /etc/passwd 之类真实文件当靶子：那样测试本身就在读系统文件，
    而且不同机器上未必存在。
    """
    源 = tmp_path / "合成外部.txt"
    源.write_text("这个不该被读走", encoding="utf-8")
    store = _建store(tmp_path)
    monkeypatch.setattr(store, "allowed_roots", ((tmp_path / "vault").resolve(),))

    with pytest.raises(MediaPersistenceError, match="不在允许的临时目录内"):
        await store.persist("合成桶", [{"path": str(源)}])


@pytest.mark.asyncio
async def test_带parent的穿越路径同样按真实位置判定(tmp_path, monkeypatch):
    """`..` 不能变成绕过手段：判定用的是解析后的真实路径。"""
    源 = tmp_path / "合成外部.txt"
    源.write_text("这个不该被读走", encoding="utf-8")
    store = _建store(tmp_path)
    monkeypatch.setattr(store, "allowed_roots", ((tmp_path / "vault").resolve(),))
    穿越 = str(tmp_path / "vault" / ".." / "合成外部.txt")

    with pytest.raises(MediaPersistenceError, match="不在允许的临时目录内"):
        await store.persist("合成桶", [{"path": 穿越}])


@pytest.mark.asyncio
async def test_超过条数上限在写第一个字节之前就拒绝(tmp_path):
    store = _建store(tmp_path)
    媒体目录 = tmp_path / "vault" / "_media"

    with pytest.raises(MediaPersistenceError, match="一次最多"):
        await store.persist("合成桶", [_一项()] * (store.max_items + 1))

    落盘 = list(媒体目录.glob("**/*")) if 媒体目录.exists() else []
    assert not [p for p in 落盘 if p.is_file()], "被拒的调用不该留下任何媒体文件"


@pytest.mark.asyncio
async def test_正好等于上限仍然接受(tmp_path):
    """边界的另一侧：卡的是「超过」，不是「接近」。"""
    store = _建store(tmp_path)
    结果 = await store.persist(
        "合成桶", [_一项(f"第{i}项") for i in range(store.max_items)]
    )
    assert len(结果) == store.max_items


@pytest.mark.asyncio
async def test_precheck只看不写(tmp_path):
    """precheck 的存在是为了让 hold 在写原文之前就知道媒体能不能读。

    它必须真的不落盘，否则「先校验再提交」就成了「写两遍」。
    """
    store = _建store(tmp_path)
    媒体目录 = tmp_path / "vault" / "_media"

    await store.precheck([_一项()])
    落盘 = list(媒体目录.glob("**/*")) if 媒体目录.exists() else []
    assert not [p for p in 落盘 if p.is_file()]

    with pytest.raises(MediaPersistenceError, match="Base64"):
        await store.precheck([{"data_base64": "@@@不是base64@@@", "filename": "x"}])


# --- 可配置的额外白名单根 ----------------------------------------------------
#
# 为什么需要这个口子：并非所有客户端都把上传文件放进系统临时目录。AstrBot 把
# 收到的图片存在自己的 data/temp 下，于是 media=path 这条路对它永远不通。
# 而报错文案原本建议的 data_base64 在这个场景里是条死路——模型拿到的是图片
# 描述，字节从未进入上下文，没法凭空生成 base64。
#
# 关键是：这仍然是**显式白名单**，不是放开任意路径。下面三条分别锚定
# 「加了就能用」「加了也不等于全开」「穿越照样按真实位置判定」。


def _建store带额外根(tmp_path, 额外根, monkeypatch=None):
    """建一个默认根被收窄成 vault 自己的 store。

    为什么要收窄：pytest 的 tmp_path 本身就在系统临时目录下，默认白名单
    天然就接受它，那样「额外根起了作用」和「默认根本来就放行」分不开。
    把默认根换成 vault，剩下的通过与否就只可能来自额外根。
    """
    if monkeypatch is not None:
        monkeypatch.setattr(
            MediaStore,
            "_default_allowed_roots",
            staticmethod(lambda: ((tmp_path / "vault").resolve(),)),
        )
    return MediaStore(
        str(tmp_path / "vault"),
        str(tmp_path / "vault" / "_media"),
        extra_allowed_roots=额外根,
    )


def test_额外根与默认根合并且去重丢空(tmp_path):
    """纯合并逻辑：默认根保留、额外根追加、空项丢弃、重复不叠加。"""
    默认 = MediaStore._default_allowed_roots()
    额外 = str(tmp_path / "客户端媒体")

    结果 = MediaStore._resolve_allowed_roots([额外, "", "   ", 额外, None])

    assert 结果[: len(默认)] == 默认, "默认根必须原样保留在前面"
    assert 结果[len(默认):] == ((tmp_path / "客户端媒体").resolve(),)


@pytest.mark.asyncio
async def test_额外白名单根让客户端自有目录可用(tmp_path, monkeypatch):
    """真机场景：客户端把上传文件存在自己的目录，不在系统临时目录下。"""
    客户端目录 = tmp_path / "客户端媒体"
    客户端目录.mkdir()
    源 = 客户端目录 / "合成上传.jpg"
    字节 = b"\xff\xd8\xff\xe0" + "合成图片字节".encode("utf-8")
    源.write_bytes(字节)

    # 先证明：不加额外根，这个路径确实被拒（否则下面那条通过说明不了任何事）
    没加根 = _建store带额外根(tmp_path, [], monkeypatch)
    with pytest.raises(MediaPersistenceError, match="不在允许的临时目录内"):
        await 没加根.persist("合成桶", [{"path": str(源)}])

    加了根 = _建store带额外根(tmp_path, [str(客户端目录)], monkeypatch)
    结果 = await 加了根.persist("合成桶", [{"path": str(源)}])

    assert 结果[0]["stored"] is True
    assert 结果[0]["size"] == len(字节)


@pytest.mark.asyncio
async def test_额外白名单根不等于放开任意路径(tmp_path, monkeypatch):
    """加了额外根之后，两个根之外的文件仍然要被拒。

    这条是整个功能的安全底线：口子是「多列一个显式目录」，不是「取消白名单」。
    """
    客户端目录 = tmp_path / "客户端媒体"
    客户端目录.mkdir()
    外面的 = tmp_path / "合成外部.txt"
    外面的.write_text("这个不该被读走", encoding="utf-8")

    store = _建store带额外根(tmp_path, [str(客户端目录)], monkeypatch)

    with pytest.raises(MediaPersistenceError, match="不在允许的临时目录内"):
        await store.persist("合成桶", [{"path": str(外面的)}])


@pytest.mark.asyncio
async def test_借额外根做parent穿越仍按真实位置判定(tmp_path, monkeypatch):
    """`..` 不能因为额外根的存在就变成绕过手段。"""
    客户端目录 = tmp_path / "客户端媒体"
    客户端目录.mkdir()
    外面的 = tmp_path / "合成外部.txt"
    外面的.write_text("这个不该被读走", encoding="utf-8")

    store = _建store带额外根(tmp_path, [str(客户端目录)], monkeypatch)
    穿越 = str(客户端目录 / ".." / "合成外部.txt")

    with pytest.raises(MediaPersistenceError, match="不在允许的临时目录内"):
        await store.persist("合成桶", [{"path": 穿越}])


@pytest.mark.asyncio
async def test_拒绝文案会把当前白名单和出路一起说清(tmp_path, monkeypatch):
    """报错必须可行动。

    原文案只说「请改传 data_base64」，但在「模型只拿到图片描述、没拿到字节」
    的场景里那条路根本走不通，调用方照着做只会再失败一次。现在文案里带上
    当前白名单和 OMBRE_MEDIA_ALLOWED_ROOTS 这个真正的出口。
    """
    源 = tmp_path / "合成外部.txt"
    源.write_text("这个不该被读走", encoding="utf-8")
    store = _建store带额外根(tmp_path, [], monkeypatch)

    with pytest.raises(MediaPersistenceError) as 异常:
        await store.persist("合成桶", [{"path": str(源)}])

    文案 = str(异常.value)
    assert str((tmp_path / "vault").resolve()) in 文案, "要列出当前白名单"
    assert "OMBRE_MEDIA_ALLOWED_ROOTS" in 文案, "要指出真正的出口"
    assert "data_base64" in 文案, "持有字节的调用方仍然可以走这条"
