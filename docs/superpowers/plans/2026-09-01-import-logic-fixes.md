# 导入链路修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 阻止恶意文件路径，保证 Milvus 更新失败不丢旧数据，并让文件 hash、文档版本和任务状态反映真实导入结果。

**架构：** 上传边界先验证文件名；Milvus 使用“读取旧主键—插入新数据—按旧主键删除”的无损顺序；Mongo 只把同文件名最新记录视为活动版本。保留既有 VARCHAR schema，将 `part` 在写入边界统一转为字符串。

**技术栈：** FastAPI UploadFile、pathlib、LangGraph、PyMilvus、MongoDB、pytest

---

## 文件职责

- `app/api/http/import_server.py`：安全文件名和任务失败状态。
- `app/rag/import_/entry_service.py`：支持类型与活动版本判断。
- `app/rag/import_/index_service.py`：写入规范化、过滤转义和无损替换。
- `app/shared/clients/mongo_file_hash_utils.py`：按文件名维护活动 hash。
- `app/shared/clients/mongo_history_utils.py`：按主体 upsert 文档版本时间。
- `app/process/import_/agent/nodes/node_import_milvus.py`：成功后更新两个 Mongo 元数据源。
- `test/test_import_api.py`、创建 `test/test_import_entry.py`、`test/test_import_index.py`：回归测试。

### 任务 1：拒绝路径穿越和不支持类型

**文件：**
- 修改：`test/test_import_api.py`
- 创建：`test/test_import_entry.py`
- 修改：`app/api/http/import_server.py`
- 修改：`app/rag/import_/entry_service.py`

- [ ] **步骤 1：编写失败测试**

```python
@pytest.mark.parametrize("filename", ["../evil.md", "..\\evil.md", "C:\\evil.md", "\\\\host\\share\\evil.md"])
def test_upload_rejects_path_traversal(filename):
    response = client.post("/upload", files=[("files", (filename, b"# x", "text/markdown"))])
    assert response.status_code == 400


def test_unsupported_file_type_raises(tmp_path, monkeypatch):
    path = tmp_path / "payload.exe"
    path.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="不支持"):
        analysis_input_file(create_default_state(local_file_path=str(path)))
```

- [ ] **步骤 2：运行红灯**

```powershell
$env:JWT_SECRET='test-only-secret-at-least-32-bytes-long'
.\.venv\Scripts\python.exe -m pytest test/test_import_api.py -k traversal test/test_import_entry.py -v
```

预期：路径被写入或请求成功，不支持类型正常返回，测试 FAIL。

- [ ] **步骤 3：实现最少边界校验**

在 `import_server.py` 增加：

```python
from pathlib import PurePosixPath, PureWindowsPath


def safe_upload_filename(filename: str | None) -> str:
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="无效文件名")
    if PurePosixPath(filename).name != filename or PureWindowsPath(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不能包含路径")
    return filename
```

保存前使用 `filename = safe_upload_filename(cur_file.filename)`，且只拼接该返回值。

`entry_service.py` 对不支持类型执行：

```python
raise ValueError(
    f"不支持的文件类型: {suffix or '<none>'}; 支持: {', '.join(sorted(SUPPORTED_FILE_TYPES))}"
)
```

- [ ] **步骤 4：运行绿灯**

运行任务 1 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/api/http/import_server.py app/rag/import_/entry_service.py test/test_import_api.py test/test_import_entry.py
git commit -m "fix: 校验导入文件边界"
```

### 任务 2：规范化 Milvus 字段并转义过滤器

**文件：**
- 创建：`test/test_import_index.py`
- 修改：`app/rag/import_/index_service.py`

- [ ] **步骤 1：编写失败测试**

```python
from types import SimpleNamespace
from unittest.mock import Mock


def test_prepare_chunks_converts_part_to_string():
    chunks = [{"part": 1, "file_title": "a", "content": "x"}]
    prepared = prepare_chunks_for_insert(chunks)
    assert prepared[0]["part"] == "1"
    assert chunks[0]["part"] == 1


def test_old_chunk_query_escapes_file_title(monkeypatch):
    client = Mock()
    client.query.return_value = []
    monkeypatch.setattr(index_service, "milvus_gateway", SimpleNamespace(
        client=client, get_chunks_collection="kb_chunks"
    ))
    list_old_chunk_ids('a" or file_title != "')
    expression = client.query.call_args.kwargs["filter"]
    assert '\\"' in expression
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_import_index.py -v
```

预期：两个新函数不存在，测试 FAIL。

- [ ] **步骤 3：实现最少写入边界**

复用 `app.shared.utils.escape_milvus_string_utils.escape_milvus_string`：

```python
def prepare_chunks_for_insert(chunks: list[dict]) -> list[dict]:
    prepared = []
    for chunk in chunks:
        row = chunk.copy()
        row["part"] = str(row.get("part", ""))
        prepared.append(row)
    return prepared


def list_old_chunk_ids(file_title: str) -> list[int]:
    escaped = escape_milvus_string(file_title)
    rows = milvus_gateway.client.query(
        collection_name=milvus_gateway.get_chunks_collection,
        filter=f'file_title == "{escaped}"',
        output_fields=["chunk_id"],
    )
    return [row["chunk_id"] for row in rows]
```

`insert_chunks()` 只接收 `prepare_chunks_for_insert(chunks)` 的返回值。任何以 file_title 构造的 Milvus filter 都使用现有 escape helper。

- [ ] **步骤 4：运行绿灯**

运行任务 2 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/rag/import_/index_service.py test/test_import_index.py
git commit -m "fix: 规范化 Milvus 导入字段"
```

### 任务 3：改为先插新数据再删除旧主键

**文件：**
- 修改：`test/test_import_index.py`
- 修改：`app/rag/import_/index_service.py`

- [ ] **步骤 1：编写失败测试**

```python
def valid_chunk() -> dict:
    return {
        "content": "x", "file_title": "doc", "item_name": "item",
        "parent_title": "p", "title": "t", "part": 1,
        "dense_vector": [0.0] * 1024, "sparse_vector": {0: 1.0},
    }


def test_insert_failure_keeps_old_chunks(monkeypatch):
    client = Mock()
    client.query.return_value = [{"chunk_id": 10}, {"chunk_id": 11}]
    client.insert.side_effect = RuntimeError("insert failed")
    monkeypatch.setattr(index_service, "milvus_gateway", SimpleNamespace(
        client=client, get_chunks_collection="kb_chunks"
    ))
    monkeypatch.setattr(index_service, "prepare_chunks_collection", lambda: None)
    with pytest.raises(RuntimeError, match="insert failed"):
        index_chunks({"file_title": "doc", "chunks": [valid_chunk()]})
    client.delete.assert_not_called()


def test_success_deletes_only_old_primary_keys(monkeypatch):
    client = Mock()
    client.query.return_value = [{"chunk_id": 10}, {"chunk_id": 11}]
    monkeypatch.setattr(index_service, "milvus_gateway", SimpleNamespace(
        client=client, get_chunks_collection="kb_chunks"
    ))
    monkeypatch.setattr(index_service, "prepare_chunks_collection", lambda: None)
    index_chunks({"file_title": "doc", "chunks": [valid_chunk()]})
    assert client.insert.call_count == 1
    assert client.delete.call_args.kwargs["filter"] == "chunk_id in [10, 11]"
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_import_index.py -k "old_chunks or old_primary" -v
```

预期：当前先 delete，第一条测试 FAIL；当前按 file_title 删除，第二条 FAIL。

- [ ] **步骤 3：实现无损顺序**

把 `index_chunks()` 的核心顺序改成：

```python
old_ids = list_old_chunk_ids(file_title)
insert_chunks(prepare_chunks_for_insert(chunks))
if old_ids:
    milvus_gateway.client.delete(
        collection_name=milvus_gateway.get_chunks_collection,
        filter=f"chunk_id in [{', '.join(map(str, old_ids))}]",
    )
```

删除原 `remove_old_chunks(file_title)` 调用。插入异常自然向上抛出，旧主键未删除；删除异常也向上抛出，让任务成为 FAILED，而不是假完成。

- [ ] **步骤 4：运行绿灯**

运行任务 3 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/rag/import_/index_service.py test/test_import_index.py
git commit -m "fix: 无损替换文档向量"
```

### 任务 4：维护文件活动 hash 和文档版本

**文件：**
- 修改：`test/test_import_entry.py`
- 创建：`test/test_import_metadata.py`
- 修改：`app/shared/clients/mongo_file_hash_utils.py`
- 修改：`app/shared/clients/mongo_history_utils.py`
- 修改：`app/rag/import_/entry_service.py`
- 修改：`app/process/import_/agent/nodes/node_import_milvus.py`

- [ ] **步骤 1：编写失败测试**

```python
def valid_state(tmp_path) -> dict:
    path = tmp_path / "doc.md"
    path.write_text("# doc", encoding="utf-8")
    return {
        "task_id": "t1", "local_file_path": str(path), "file_hash": "abc",
        "item_name": "item", "file_title": "doc", "chunks": [],
    }


def test_dedup_uses_current_version_for_same_filename(tmp_path, monkeypatch):
    path = tmp_path / "doc.md"
    path.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(entry_service, "find_current_by_file_name", lambda name: {
        "file_name": name, "file_hash": hashlib.sha256(b"v2").hexdigest()
    })
    state = analysis_input_file(create_default_state(local_file_path=str(path)))
    assert state["skip_import"] is False
    assert state["is_update"] is True


def test_metadata_updates_only_after_index_success(tmp_path, monkeypatch):
    monkeypatch.setattr(node_import_milvus_module, "index_chunks", Mock(side_effect=RuntimeError("db")))
    save_hash = Mock()
    save_version = Mock()
    monkeypatch.setattr(node_import_milvus_module, "save_file_hash", save_hash)
    monkeypatch.setattr(node_import_milvus_module, "save_document_version", save_version)
    with pytest.raises(RuntimeError):
        node_import_milvus(valid_state(tmp_path))
    save_hash.assert_not_called()
    save_version.assert_not_called()
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_import_entry.py test/test_import_metadata.py -v
```

预期：活动版本函数不存在，入口仍按任意历史 hash 跳过，版本函数未接入，测试 FAIL。

- [ ] **步骤 3：实现活动版本与版本时间**

在 file hash 工具实现：

```python
def find_current_by_file_name(file_name: str) -> Optional[dict]:
    return get_file_hash_mongo_tool().file_hashes.find_one(
        {"file_name": file_name}, sort=[("import_time", -1)]
    )
```

`save_file_hash()` 改为 `update_one({"file_name": file_name}, {"$set": document}, upsert=True)`。入口只查询当前同名记录：hash 相等则 skip；记录存在但 hash 不同则 update。删除全局 `find_by_file_hash()` 去重调用。

将 document version 保存函数改为标量时间和 upsert：

```python
def save_document_version(item_name: str, file_name: str, file_hash: str) -> str:
    document = {
        "item_name": item_name,
        "file_name": file_name,
        "file_hash": file_hash,
        "last_import_time": datetime.now().timestamp(),
    }
    get_history_mongo_tool().document_versions.update_one(
        {"_id": item_name}, {"$set": document}, upsert=True
    )
    return item_name
```

`node_import_milvus()` 在 `index_chunks(state)` 成功后依次保存活动 hash 和 document version；任一失败返回空值时抛 RuntimeError，不能继续标记节点完成。

- [ ] **步骤 4：运行绿灯并验证 v1→v2→v1**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_import_entry.py test/test_import_metadata.py -v
```

预期：全部 PASS，活动 hash 每次与最后成功导入内容一致。

- [ ] **步骤 5：提交**

```powershell
git add app/shared/clients/mongo_file_hash_utils.py app/shared/clients/mongo_history_utils.py app/rag/import_/entry_service.py app/process/import_/agent/nodes/node_import_milvus.py test/test_import_entry.py test/test_import_metadata.py
git commit -m "fix: 维护文档活动版本元数据"
```
