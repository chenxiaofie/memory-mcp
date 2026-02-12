# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-02-12

### Added

- Hook 脚本打包为 pip CLI 入口点，`pip install` 后直接可用：
  - `memory-mcp-session-start`
  - `memory-mcp-auto-save`
  - `memory-mcp-save-response`
  - `memory-mcp-session-end`
  - `memory-mcp-monitor`
- 新增 `src/hooks/` 包，所有 hook 脚本移入包内
- 根目录 hook 脚本改为向后兼容的薄包装器

### Changed

- Hook 日志文件 (`hook_debug.log`) 改为写入 `~/.claude/memory/`（用户级，始终可写）
- `session_start.py` 查找监控脚本时优先使用 `shutil.which("memory-mcp-monitor")`
- README 的 Hooks 配置文档简化为入口点命令方式

## [0.1.3] - 2026-02-12

### Added

- 注册 MCP 官方注册表 (`io.github.chenxiaofie/memory-mcp`)
- 添加 `server.json` 配置文件

## [0.1.2] - 2026-02-12

### Added

- GitHub Actions 自动发布到 PyPI（push tag 触发）
- README 添加 PyPI 版本、Python 版本、License 徽章

### Changed

- 更新 README hooks 配置文档

## [0.1.0] - 2026-02-06

### Added

- 初始版本发布
- 实现了情景记忆 (Episodes) 功能
- 实现了实体记忆 (Entities) 功能
- 支持用户级和项目级双层存储
- 实现了实时缓存和语义检索功能
- 提供了 4 个自动化 hooks 实现会话生命周期管理
- 支持中英文文档
