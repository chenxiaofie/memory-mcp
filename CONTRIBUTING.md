# Contributing to Memory MCP Service

感谢您有兴趣为 Memory MCP Service 项目做出贡献！

## 如何贡献

### 报告问题

如果您发现了 bug 或有功能需求，请：

1. 先检查是否已经有相关的 issue
2. 如果没有，请创建一个新的 issue
3. 提供详细的描述，包括：
   - 问题的具体表现
   - 复现步骤
   - 您使用的操作系统和 Python 版本
   - 相关的错误信息

### 提交代码

1. Fork 项目到您的 GitHub 账号
2. 创建一个新的分支
3. 实现您的功能或修复 bug
4. 提交您的更改，并附上清晰的提交信息
5. 创建一个 PR 到主仓库

### 开发环境

#### 安装依赖

```bash
cd C:\devfiles\memory-mcp
python -m venv venv310
venv310\Scripts\activate  # Windows
# source venv310/bin/activate  # Mac/Linux
pip install -e .
```

#### 运行测试

```bash
pytest test_race_condition.py
```

#### 运行服务器

```bash
python -m src.server
```

## 代码规范

- 遵循 PEP8 代码风格
- 使用类型注解
- 添加适当的文档字符串
- 编写测试用例

## 许可证

By contributing to Memory MCP Service, you agree that your contributions will be licensed under the MIT License.
