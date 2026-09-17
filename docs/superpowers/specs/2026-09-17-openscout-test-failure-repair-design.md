# OpenScout 完整测试失败修复设计

## 目标

修复 2026-09-17 完整后端测试中剩余的 22 个失败项，使 MCP、BYOM 和
GraphRAG 定向测试在可复现环境中通过，同时保持现有 SSRF 防护和 OpenScout
产品规格不变。

## 当前诊断

完整测试在固定 PostgreSQL 端口的非沙箱环境中得到 `10,088 passed、451
skipped、22 failed`。失败分为三组：

1. `tests/api/user/test_tools_mcp_pg.py` 的 5 个端点测试使用
   `https://example.com/mcp`，当前测试环境的 DNS 将其解析为被 SSRF 校验器
   拒绝的地址。端点测试已经 mock 了 `MCPTool`，它们验证的是响应分支，不是
   DNS 或 URL 安全策略。
2. BYOM 转发测试使用 `https://api.mistral.ai/v1`，当前环境将该域名解析为
   保留地址 `198.18.2.182`，安全校验在测试断言前终止。已有 DNS pinning
   测试证明了安全路径本身，转发字段测试需要稳定的公开 DNS 夹具。
3. GraphRAG 的 NetworkX PageRank 路径依赖 SciPy，但核心依赖声明没有直接
   包含 SciPy。缺少依赖时 GraphRAG 捕获 `ModuleNotFoundError` 并回退到
   ClassicRAG，导致排序、批处理和成功路径测试失败；重复 `close()` 是该
   回退路径的观测结果，安装依赖后再判断是否仍需生命周期改动。

## 修复设计

### MCP 测试隔离

仅在端点响应测试中 patch `docsgpt.api.user.tools.mcp.validate_url`，使测试
继续验证成功、连接失败、OAuth 和异常响应分支。保留
`TestValidateMcpServerUrl` 的真实 SSRF 测试，并继续拒绝 `127.0.0.1` 等
私有地址。生产代码和安全策略不变。

### BYOM 测试隔离

在 4 个只验证模型 API key、上游模型名和 capability 转发的测试中 patch
`docsgpt.security.safe_url` 的 DNS 解析，使 `api.mistral.ai` 稳定映射到
公开 IP。测试仍执行 URL 校验和 pinned-client 构造；独立的
`test_dispatch_injects_pinned_http_client_for_user_model` 继续覆盖真实
DNS pinning 行为。生产代码不放宽地址检查。

### GraphRAG 依赖

在 `pyproject.toml` 中加入核心运行依赖 `scipy>=1.18.1,<2`，然后运行
`uv lock` 和 `bash scripts/export_requirements.sh`，由锁文件生成
`docsgpt/requirements*.txt`。不手动编辑导出文件，也不实现另一套 PageRank
算法。安装依赖后重新运行 GraphRAG 定向测试；只有重复关闭在依赖恢复后仍
存在，才增加最小的释放所有权修复和对应回归测试。

## 验证顺序

1. 运行 MCP 定向测试，确认 5 个失败项归零，并确认 SSRF 拒绝测试仍通过。
2. 运行 BYOM 定向测试，确认 4 个失败项归零，并确认 pinned-client 测试仍通过。
3. 更新并安装依赖，运行完整 GraphRAG 测试；仅在必要时修改资源关闭逻辑。
4. 对每组完成 `ruff check` 和相关定向 pytest 后提交并推送到 `main` 与
   `feature/openscout-design`。
5. 最后使用固定 PostgreSQL 临时端口运行完整后端测试，记录剩余结果，不把
   环境阻断误报为通过。

## 范围边界

- 不修改产品规格、SSRF allowlist 或生产网络安全策略。
- 不修改封存的 OpenScout 评估题目、答案或门槛。
- 不进行无关重构，不把用户已有的 `AGENTS.md` 修改加入提交。
- 若依赖安装或数据库环境再次阻塞，记录具体原因并停止当前组，不跳过验证。
