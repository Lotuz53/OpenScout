# OpenScout 首次同步 FAISS 生命周期修复设计

## 目标

修复 OpenScout 首次同步 GitHub 项目时因 FAISS 索引尚不存在而失败、但项目和同步运行永久停留在 `syncing`/`running` 的问题。修复后，首次同步能够建立并持久化索引；后续同步能够复用已有索引并执行增量替换；索引、数据库或持久化异常都能留下可诊断的失败终态，同时继续向 Celery 传播原始异常。

## 已确认的调用链与根因

生产同步任务由 `docsgpt/intelligence/tasks.py` 构造 `SyncService`，服务在第一次发生变化的来源批次中通过 `_get_indexer()` 创建 `IntelligenceIndexer` 和配置的向量存储。当前 FAISS 创建调用没有传入初始文档或“允许首次创建”的信号，因此 `FaissStore` 在没有任何索引文件时进入 `_load_from_storage()`，抛出 `Index files not found in storage`。

`IntelligenceIndexer.replace_records()` 随后会删除旧 chunks 并调用 `add_texts()`，但 FAISS 的 `add_texts()` 只更新内存索引和 sidecar 映射，没有保证三份索引文件写回存储。与此同时，`SyncService.run_incremental()` 只在正常路径调用 `finish_sync_run()` 和最终项目状态更新；本地索引或数据库异常直接跳出，因此已写入的 `running`/`syncing` 状态不会收尾。

## 方案

### 1. 仅对 OpenScout 首次同步开放缺失索引创建

为 `FaissStore` 增加显式的 `create_if_missing` 参数，默认值保持关闭。默认行为不变：普通检索、已有索引加载和现有“缺少索引时报错”测试仍然保留。

OpenScout 的 `SyncService._get_indexer()` 仅在 `VECTOR_STORE=faiss` 时传入 `create_if_missing=True`。FAISS 构造过程区分两种情况：

- `index.faiss`、`index.json`、`index.pkl` 全部不存在：允许进入空的内存状态；首批 `add_texts()` 根据实际 embedding 维度创建 `IndexFlatL2`。
- 三份文件中任意一份存在：按已有索引加载。缺少配套 sidecar、格式损坏、读取异常或 embedding 维度不匹配都继续抛出，绝不自动当作新索引覆盖。

这样既解决全新项目，又不会把真实损坏的已有索引静默重置。

### 2. 统一保证 FAISS 变更持久化

FAISS 的新增向量、记录替换和确认删除都必须使 `index.faiss`、JSON sidecar 和兼容用 pickle sidecar 保持可重新打开状态。具体边界如下：

- `FaissStore.add_texts()` 在成功追加向量和文档映射后持久化三份文件；保存失败直接抛出。
- `IntelligenceIndexer.replace_records()` 和 `delete_records()` 保持现有按记录替换的行为，并在操作结束时确认支持的向量存储已完成持久化。
- 保存异常不被吞掉；数据库事务由现有 `db_session` 回滚，下一次同步仍会从上一次可读取的索引开始。

不改变其他向量存储的接口或生命周期；对没有 `save_local()` 的存储沿用其现有写入行为。

### 3. 本地失败的终态收尾与异常传播

在同步运行已经创建并将项目置为 `syncing` 后，用最小范围的失败保护包住剩余同步流程。发生 FAISS 创建/加载/保存、数据库写入、索引替换或其他本地持久化异常时：

1. 构造 `status="failed"` 的 `SyncSummary`，保留已经统计的 counts/coverage，并写入本地同步失败类别和异常文本。
2. 通过现有 `finish_sync_run()` 将当前 run 写为 `failed`，通过现有 `set_project_status()` 将项目写为 `failed`。两个收尾操作分别尽力执行并记录收尾异常，避免一个收尾失败阻止另一个收尾。
3. 使用裸 `raise` 继续传播原始异常，保持 Celery 对非 GitHub 可恢复异常的现有处理，不伪装成成功。

扩展同步失败契约以表达本地失败（`local` 类别和同步流程来源标识），并为 UI 提供明确的“本地同步失败”标签。现有 GitHub 限流、网络、鉴权和 payload 失败仍由 `_run_source()` 按原有规则产生 `partial`/`failed` 结果，不改动其产品语义。

`tasks.py` 继续调用 `SyncService` 并返回成功 summary；只有测试证明任务包装层需要变化时才修改它。

### 4. 当前卡住数据的安全恢复

代码和聚焦测试通过后，使用现有数据库连接和 repository 事务只定位 `jinchenma94/bazi-skill` 对应的项目及其仍为 `running` 的同步 run。仅当状态仍匹配时，将该 run 和项目写入 `failed`，失败信息说明为历史 FAISS 首次创建失败；不删除已有记录、不删除索引文件、不修改其他项目。

随后使用现有同步任务重新触发该项目，使用新的幂等键，并通过项目状态和最新 sync run 观察实际结果，确认最终进入 `ready`、`partial` 或 `failed`，不再停留在 `syncing`/`running`。

## 测试设计（先红后绿）

新增失败测试后，先运行聚焦测试确认它们在当前代码上失败，再实现修复并重新运行：

1. `tests/vectorstore/test_faiss.py`
   - 全新目录在 `create_if_missing=True` 下可以首次追加并写出三个索引文件。
   - 新的 `FaissStore` 实例可以重新打开保存结果。
   - `add_texts()` 后索引和 sidecar 已持久化。
   - 已有索引的第二次打开复用原索引并能继续增量追加。
   - 真实损坏或不完整文件仍然明确报错，不被初始化逻辑覆盖。
2. `tests/intelligence/test_indexing.py`
   - `replace_records()` 替换同一稳定 source 后只保留新 chunks，并且重新打开的 FAISS store 内容正确。
   - `delete_records()` 后删除结果可持久化。
3. `tests/intelligence/test_sync_service.py` 与 `tests/intelligence/test_incremental_sync.py`
   - 生产 FAISS 创建调用收到 `create_if_missing=True`。
   - 模拟索引创建或保存异常时，run 为 `failed`、项目离开 `syncing`，并保留诊断消息。
   - 原始异常仍被抛出；GitHub 单来源可恢复失败仍保持现有 `partial` 行为。
4. `tests/intelligence/test_tasks.py`
   - 保持任务成功 summary 的序列化契约；如需要，补充原始本地异常继续传播的断言。

验证顺序为 FAISS、indexing、sync service/incremental sync、tasks 相关聚焦测试，随后运行改动文件的 Ruff。除非聚焦测试暴露直接相关问题，不运行完整项目测试套件，也不做向量存储重构。

## 修改范围与非目标

预计修改：

- `docsgpt/vectorstore/faiss.py`
- `docsgpt/intelligence/indexing.py`
- `docsgpt/intelligence/sync_service.py`
- 本地失败契约及其必要的 OpenScout UI 类型/文案
- 上述对应测试文件

不修改 GitHub 采集、normalizer、GraphRAG 算法、其他向量存储、Celery 重试策略或产品规格。任何与当前首次同步索引生命周期无关的既有失败都保持原状。
