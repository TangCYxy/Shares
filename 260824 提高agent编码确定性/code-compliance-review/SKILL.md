---
name: code-compliance-review
description: 按本地配置的 Markdown 规范文件、默认 skills，以及本次项目代码改动涉及的额外 skills，对当前 git 有效生产代码实现变更进行编码规范审查，不约束单测代码实现。适用于编码完成后、completion gate 前，或外部编排服务需要获得确定性的 Java/DB/Redis/Web3/SDK、代码风格、语言无关生产代码规范遵守证据时使用；调用时应把本次改动实际涉及的专项 skill 名字作为第二参数传入。
---

# Code Compliance Review

## 使用方式

执行本 skill 携带的脚本：

```bash
python3 scripts/code_compliance_review.py <repo_root> [extra_skill_names_csv] [target_paths_csv]
```

`<repo_root>` 必须传仓库绝对路径。第二个参数可选，表示本次项目代码改动实际涉及、且需要额外遵守的专项 skill 名字列表，使用英文逗号分隔；这里传的是 skill 名字，不是文件路径。

第二参数由外部调度服务根据本次改动内容决定。例如本次版本改动涉及 FSM，就传入 `sdk-wanel-fsm-java`；涉及 Safe + gas relay 提交，就传入 `java-safe-gas-relay-tx-submission,wanel-gas-relay-client-integration`。

第三参数可选，表示除了当前 git 变更外，还要额外审查的代码目录或文件路径列表，使用英文逗号分隔；这里传的是仓库相对路径，不是绝对路径。该参数适用于代码已经提交、当前 git 变更很少，但仍需要对某些模块或目录下的功能代码做规范审查的场景。

示例：

```bash
python3 scripts/code_compliance_review.py /home/tc/wanel-common
python3 scripts/code_compliance_review.py /home/tc/wanel-common java-jpa-db-service-design,sdk-wanel-fsm-java
python3 scripts/code_compliance_review.py /home/tc/wanel-common "" "wanel-components/wanel-cross-chain-payment-server,wanel-components/wanel-observer-server"
```

## 执行行为

- 读取本 skill 的 `config.toml`。
- 将配置中的 Markdown 文件解析为 `<repo_root>` 下的相对路径。
- 将配置中的默认 skill 名字和参数传入的额外 skill 名字解析为 `<repo_root>/<skills_root>/<skill_name>`。
- 将第三参数中的 target paths 解析为 `<repo_root>` 下的相对路径。
- 找不到或不可读的文件、目录、skill 直接忽略，不让脚本失败。
- 脚本只把有效 Markdown 文件路径和 skill 目录路径传给一个新的 Codex CLI 会话，不在脚本内读取规范正文。
- 由该 Codex CLI 会话自行读取 Markdown 文件；对 skill 目录，至少读取 `SKILL.md`，其他文件按理解规范所需自行决定是否读取。
- 调用 Codex CLI 从所有有效规范路径中抽取“有效生产代码实现规范”，要求一行一个规范。
- 规范抽取阶段只关注生产代码结构、函数/类设计、语言编码、DB/JPA/SQL、Redis/缓存/锁、RPC/HTTP/SDK/Web3/中间件访问边界等；不抽取单测、测试代码、测试覆盖率、测试证据、测试执行方式、设计文档写作、发布材料、研发流程、proposal/openspec 流程、调度规则、沟通风格、归档步骤等非生产代码实现规范。
- 将 `config.toml` 中的 `ignored_paths` 和 `evidence_dir` 解析为 `<repo_root>` 下的忽略路径。
- 生成 git status、diff、diff stat 和 changed file context 时会排除所有忽略路径。
- 每个批量审查 Codex CLI 会话都会收到忽略路径列表，并被要求不得把这些路径作为阻塞证据。
- 脚本不会读取 target paths 下的文件内容，只会把有效 target paths 透传给每个批量审查 Codex CLI 会话。
- 每个批量审查 Codex CLI 会话必须自行读取 target paths 中与当前规范相关的有效生产代码实现文件；target paths 只用于生产代码实现审查。
- 每个批量审查 Codex CLI 会话不得把 `src/test/`、`*Test.java`、`*Tests.java` 或其他单测文件作为阻塞证据；只能针对单测或测试证据判断的规范必须返回 `忽略`。
- Codex CLI 调用使用 `--output-last-message` 捕获子会话最后返回值；evidence 默认只记录最后返回值和解析后的审查块。
- `config.toml` 中 `record_codex_stderr = false` 时，不把 Codex CLI stderr 会话轨迹写入 evidence；只有调试脚本本身时才临时改为 `true`。
- 按 `config.toml` 中的 `match_round` 将抽取后的规范拆成若干批，每批由一个 Codex CLI 会话审查多条规范。
- 按 `config.toml` 中的 `concurrency` 并发执行批量审查任务。
- 批量审查任务失败时，该批规范按 `忽略` 处理，不让整个脚本失败。
- 将每条规范的原始审查结论直接追加写入 `<repo_root>` 下配置的 evidence 目录。
- 在 stdout 输出 JSON，包含最终状态、统计数量和 evidence 文件绝对路径。
- 外部调度服务应以 stdout JSON 中的 `status` 为准；脚本退出码只表示脚本是否成功执行到审查结果生成阶段。

## 结果语义

- `PASSED`：没有任何规范返回 `阻塞`。
- `BLOCKED`：至少一条规范返回 `阻塞`。
- `NO_RULES`：没有找到可用规范源，或没有抽取到规范行。
- `ERROR`：脚本调用方式错误，或执行环境导致脚本无法继续。

外部调度服务应直接使用脚本返回的 evidence 文件，将其转交给 coding agent 返修，或继续转交给 completion gate 做结束判定。不要再让其他 LLM 对 evidence 做改写或重新整合。
