# Dot ChatGPT/Codex 用量同步

这个工具在 Windows 上读取当前 Codex 登录账号的最新用量，把剩余百分比、重置时间和更新时间发送到 Dot 墨水屏。存在两个用量窗口时显示两个窗口；只有一个窗口时，右侧随机显示两行格言。

同步过程不调用大模型，不消耗模型 token。计划任务使用 `pythonw.exe` 静默运行，默认每 15 分钟同步一次。

> 这是社区工具，并非 OpenAI 或 MindReset 的官方项目。脚本读取 Codex 客户端本地 app-server 的用量接口；Codex 客户端升级后，该接口如有变化，脚本可能需要同步调整。

## 使用条件

- Windows 10/11。
- Python 3.10 或更高版本。
- 已安装 Codex Windows 客户端，并已登录需要查询用量的账号。
- 已绑定的 Dot 设备。
- 自己的 Dot OpenAPI 密钥、设备 ID 和 Canvas 任务 key。

## 获取安装所需的三个值

### 1. Dot API 密钥

1. 打开 Dot App，进入“更多”（More）。
2. 点击“API Key”。
3. 点击“创建 API Key”。
4. 立即复制并妥善保存生成的完整密钥。

Dot App 关闭创建结果后不会再次显示密钥正文。如果丢失，请删除旧密钥并重新创建。

### 2. 设备 ID

1. 在 Dot App 的“更多”（More）页面，点击头像下方的设备列表。
2. 选择需要显示用量的设备。
3. 向下找到“设备序列号”（Device Serial Number）。
4. 点击序列号进行复制。这个序列号就是脚本所需的设备 ID。

### 3. Canvas 任务 key

1. 在 Dot App 的 Content Studio 中，将一个“Canvas API”内容加入目标设备的循环内容列表。
2. 打开官方“List Device Content”页面：<https://dot.mindreset.tech/docs/service/open/list_device_tasks_api>。
3. 填入刚才取得的 API 密钥和设备 ID。
4. 内容列表选择 `loop`，然后发送查询。
5. 在返回结果中找到 `"type": "CANVAS_API"` 的项目。
6. 复制该项目的 `key` 值；这个值就是安装程序要求的 Canvas 任务 key。

示例：

```json
{
  "type": "CANVAS_API",
  "key": "这里就是 Canvas 任务 key"
}
```

如果 Canvas API 内容放在固定内容列表，应查询 `fixed`。当前脚本按循环列表发送，建议直接使用循环内容。

每个人都必须使用自己的 API 密钥、设备 ID 和 Canvas 任务 key。不要使用别人发来的凭据。

## 自动安装

1. 解压整个文件夹，文件之间的相对位置不要改变。
2. 双击 `install.cmd`（或 `安装.cmd`）。
3. 按提示输入：
   - Dot 设备 ID；
   - Canvas 任务 key；
   - `DOT_API_KEY`。API 密钥输入时不会显示在屏幕上。
4. 安装程序会立即测试一次同步，并创建名为 `Dot ChatGPT Plus Usage` 的 Windows 计划任务。

安装通常不需要管理员权限。计划任务每 15 分钟运行一次，使用 `pythonw.exe`，运行时不会弹出黑色窗口。

## 生成的本地文件

首次安装后会生成：

- `config.json`：设备 ID、Canvas 任务 key 和计划任务名称，不包含 API 密钥。
- `data/canvas-payload.json`：最近一次发送的 Canvas 内容。
- `data/sync.log`：运行日志。

API 密钥保存在当前 Windows 用户的 `DOT_API_KEY` 环境变量中，不会写入 Python 文件、配置文件、Canvas 文件或日志。

这些运行时文件已写入 `.gitignore`。再次分享或上传源码时，不要附带 `config.json` 和 `data` 文件夹。

## 常用操作

立即同步一次：双击 `sync-now.cmd`（或 `立即同步.cmd`）。

卸载计划任务：双击 `uninstall.cmd`（或 `卸载.cmd`）。卸载不会删除配置、日志或环境变量。

也可以在 PowerShell 中运行：

```powershell
py .\dot_usage_sync.py --install
py .\dot_usage_sync.py --sync
py .\dot_usage_sync.py --uninstall
```

修改设备或 Canvas 任务时，编辑 `config.json` 后重新运行 `安装.cmd`。计划任务会被覆盖更新。

## 修改同步间隔

打开 `dot_usage_sync.py`，在 `schtasks.exe` 参数中找到：

```python
"/MO",
"15",
```

将 `15` 改为需要的分钟数，然后重新运行 `安装.cmd`。

## 切换 ChatGPT/Codex 账号

脚本不保存 ChatGPT 账号 ID。它读取 Codex Windows 客户端当前登录账号的用量。切换账号后，先在 Codex 中确认新账号已登录，再双击 `立即同步.cmd`。

## 排查问题

查看最近一次计划任务结果：

```powershell
Get-ScheduledTaskInfo -TaskName "Dot ChatGPT Plus Usage"
```

查看日志：

```powershell
Get-Content -Tail 30 .\data\sync.log
```

常见原因：

- `DOT_API_KEY is not configured`：重新运行 `安装.cmd` 并输入 API 密钥。
- `Codex rate-limit window is unavailable`：确认 Codex 已登录正确账号，然后手动同步。
- Dot API 返回 401/403：API 密钥、设备 ID 或任务归属不匹配。
- Canvas 任务不存在：确认任务 key 正确，并已将 Canvas 内容加入设备内容循环。
- 计划任务成功但屏幕没有立即变化：墨水屏完成实际刷新可能需要几分钟。

如需清除当前 Windows 用户保存的 API 密钥：

```powershell
[Environment]::SetEnvironmentVariable("DOT_API_KEY", $null, "User")
```

## 文件说明

- `dot_usage_sync.py`：同步、配置、安装和卸载逻辑。
- `canvas-template.json`：不含个人数据的 Canvas 布局模板。
- `install.cmd` / `安装.cmd`：自动配置并创建计划任务。
- `sync-now.cmd` / `立即同步.cmd`：手动执行一次同步。
- `uninstall.cmd` / `卸载.cmd`：删除计划任务。
- `config.example.json`：配置文件格式示例。

## 许可证

[MIT License](LICENSE)
