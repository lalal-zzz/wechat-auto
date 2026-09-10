# 开发环境

- Windows 10/11
- Python：`python`
- 微信实测版本：`4.1.13.12`
- 主窗口类：`Qt51514QWindowIcon`

安装数据库可选依赖：

```powershell
python -m pip install -r requirements-db.txt
```

运行测试：

```powershell
python -m pytest tests -q
```

架构和开发约束见 `AGENTS.md` 与 `ARCHITECTURE.md`。UI 动作只允许通过
`BasicSkill -> KeyboardOnlyDriver -> HWND WM_*` 执行。
