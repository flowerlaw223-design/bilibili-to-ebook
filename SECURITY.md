# SECURITY｜凭据与隐私政策

本项目会用到**登录态**（B 站 cookie）来获取官方字幕。这类数据一旦泄露等同于账号被盗。
请严格遵守以下规则；提 PR 前请先跑 §4 的检查脚本。

## 1. 永不提交的内容

| 类型 | 例子 | 为什么危险 |
|---|---|---|
| Cookie 文件 | `bilibili_cookies_clean.txt`、`youtube_cookies.txt` | 含 SESSDATA / bili_jct，可直接接管账号 |
| 浏览器配置副本 | `chrome_profile*/`、`chrome_cap*/`、`cookies_work/` | 内含 `Login Data`（保存的密码库）、`Cookies`、`Trust Tokens` |
| 密钥 | `.env`、`*.pem`、`*.key`、各类 API Token | 直接可被滥用 |
| 受版权素材 | 付费专栏导出、课程逐字稿、付费课件 | 版权侵权，与安全无关但同样禁止 |

`.gitignore` 已覆盖上述模式，但**不要只依赖 .gitignore**。

## 2. 代码里的正确写法

- cookie 一律通过参数或环境变量传入，**不要硬编码、不要写进默认值**：
  ```bash
  bbook run "<url>" --cookies /path/to/cookies.txt
  # 或
  export BILIBILI_COOKIES=/path/to/cookies.txt
  ```
- **不要打印 cookie 内容**：日志里只允许出现"cookie 数量""是否登录成功""有效期"这类元信息。
- 报错信息里不要 echo 请求头或 cookie jar。
- 示例文件一律使用 `.example` 后缀（例如 `cookies.txt.example`），里面只放占位符。

## 3. 一旦泄露怎么办

1. **立刻改密码**并退出所有设备（B 站：设置 → 安全隐私 → 退出所有设备）；
2. 重新登录后重新导出 cookie；
3. 如果已经推到 GitHub：删仓库不够，历史里仍在 → 用 `git filter-repo` 清洗并强推，或直接删库重建；
4. GitHub 会自动扫描公开仓库的已知密钥格式并通知，但**不要指望它兜底**。

## 4. 提交前自检

```bash
python tools/preflight_scan.py .
```

退出码非 0 表示存在阻断项，**处理完再提交**。建议同时接到 pre-commit 钩子或 CI 里。

## 5. 本项目的定位

本工具用于**个人学习目的**的内容整理。使用时请遵守：

- 视频平台的用户协议与 robots 规则；
- 原作者版权与授权协议（例如原视频标注 CC BY-SA 4.0 时，衍生作品需署名并以相同方式共享）；
- 不将生成的电子书用于商业分发。
