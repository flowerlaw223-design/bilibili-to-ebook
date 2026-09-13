# bilibili-to-ebook

> 把 B 站视频变成**能坐下来读的电子书**（EPUB3）——本地转写、章节化、术语归正、一键构建。
> Turn Bilibili videos into readable E-books (EPUB3). Local ASR, chapterization, term correction, one-command build.

---

## 这个项目解决什么问题

B 站上大量高质量的长视频（技术讲解、课程、访谈）**只有视频，没有文字版**：想复习要拖进度条，想检索无从下手，想看只能"看"。

市面上的总结工具产出的是**摘要**——信息被压缩掉了。这个项目要的是反过来的东西：**信息不丢，但变得可读**。

实测：一个 **45 分 51 秒**的技术长视频 →

- 转写 **878 段 / 16,715 字**
- 切成 **11 章**（按视频自身的叙述节点，不是等长时间切）
- 生成 **19 条术语表 + 10 条金句** + 每章导读
- 产出 **EPUB（含封面、目录、时间轴索引）** + DOCX + Markdown
- 全程 LLM 成本 **约 ¥0.21**（本地 ASR 免费）

## 为什么便宜

| 环节 | 做法 | 成本 |
|---|---|---|
| 下载 / 抽帧 / OCR / 构建 / 校验 | 全部脚本化 | ¥0 |
| 语音转写 | faster-whisper 本地 CPU | ¥0（46 分钟音频约 13 分钟跑完） |
| 切章 / 起标题 / 术语归正 | LLM（唯一花钱的地方） | ¥0.2 上下 |

关键纪律：**字幕正文一律落盘、按需分段读，绝不整段贴回对话**。
把 16k 字原文反复塞进上下文，成本会从 ¥0.2 涨到 ¥20——这是本项目最贵的一课。

## 快速开始（傻瓜式：两条命令）

```bash
# 1. 安装（把 [all] 带上就是转写 + 配图全功能）
pip install -e ".[all]"

# 2. 出书。对，就这一条。
bbook run "https://www.bilibili.com/video/BVxxxxxxxxxx/"
```

跑完你会得到 `work/<视频ID>/book.epub`（含封面、目录、章节、配图、术语表）。

**它自己会做的事**：取元数据 → 下音频 → 本地转写 → 清洗归正 → 抽帧配图 →
**自动切章** → 生成 EPUB → 结构审计。整个过程不需要你回答任何问题。

**没装的东西会自动降级**，不会中途崩：
`pandoc` 不在 → 用内置的零依赖 EPUB 构建器；`ffmpeg` 不在 → 跳过配图；
`faster-whisper` 不在 → 给出安装命令。所以先跑一条 `bbook doctor` 看看缺什么：

```bash
bbook doctor        # 检查 yt-dlp / ffmpeg / pandoc / 中文字体 / faster-whisper
```

### 章节标题不满意？

自动切章有三种策略，依次降级：

1. **简介时间点**——UP 主在简介里写了 `00:00 章节名`时最准；
2. **幻灯片标题卡**——从 OCR 数据里找短文本页（正片内容页 80+ 字，标题卡只有二三十字）。
   实测能把人工切的章复现到 30 秒以内；
3. **时长兜底**——按固定分钟数切。

标题不满意就编辑 `work/<id>/chapters.json`，然后 `bbook build work/<id>` 重建——
**配图是按段落索引定位的，重新切章不会错位**。

想逐步核对（可选）：

```bash
bbook probe    "<url>"  --workdir work/BVxxx    # Phase 1 元数据
bbook audio    "<url>"  --workdir work/BVxxx    # Phase 2 音频
bbook asr      work/BVxxx --model small         # Phase 2 本地转写
bbook clean    work/BVxxx                       # Phase 3 清洗 + 术语归正
bbook frames   work/BVxxx --url "<url>"         # Phase 6 抽帧配图
bbook chapters work/BVxxx                       # Phase 4 自动切章
bbook build    work/BVxxx                       # Phase 7-8 构建 + 审计
```
```

**为什么 `run` 会停在章节划分？** 因为"哪里是一章、这一章叫什么"是需要判断的事，
脚本不猜。你（或 LLM）填好 `chapters.json` 后重跑 `build` 即可。

> 例外：**合集模式不需要人工切章**——一个分 P 天然就是一章，标题直接取 B 站分 P 名。

### 合集 / 多 P：一条命令出一本书

```bash
python -m bbook series "https://www.bilibili.com/video/BVxxxxxxxxxx/" \
       --limit 3 \            # 先试跑前 3 个分 P（不填则全部）
       --parts 1,3,5 \        # 或指定分 P
       --interval 15 \        # 抽帧间隔
       --terms terms/ai-coding.json
```

目录结构：**一个分 P 一个工作目录**，各 P 独立跑完 Phase 1–6，最后合并成一本书：

```
work/<id>-series/
├── series.json          合集与分 P 清单
├── part-001/            该 P 的完整中间产物（与单视频工作目录同构）
├── part-002/
├── chapters.json        一章 = 一个分 P
├── figures.json         合并后的配图（索引已换算为全局段落号）
└── book.epub
```

三点实测结论：

1. **不要用 yt-dlp 取分 P 标题**——合集里每个 P 返回的都是同一个合集标题。
   必须用 B 站 `view` 接口的 `pages[].part`（本项目已内置）。
2. 分 P 名常带编号和画质后缀（`1-1.课程开场-1080P 高清-AVC`），会自动清洗成 `课程开场`。
3. 各 P 时间都从 00:00 开始，所以时间轴必须带 P 号（`P1 00:00:00`），否则读者会误以为全书时间连续。

### 断点续跑

每个阶段完成后会写入 `work/<id>/state.json`。中断后重跑 `run` 会跳过已完成的阶段——
ASR 跑 13 分钟、模型下载 6 分钟，中断一次不必从头再来。

## 流水线（Phase 1–8）

| Phase | 做什么 | 产物 |
|---|---|---|
| 1 | 元数据与分 P 清单 | `meta.json` |
| 2 | 字幕获取（官方 cookie 优先，否则音频 + ASR） | `asr_segments.json` |
| 3 | 清洗：合并短句、去噪、**术语归正**、段落化 | `cleaned_paragraphs.json` |
| 4 | 章节切分（简介时间点 > 多 P > 语义转折 > 时长兜底） | `chapters.json` |
| 5 | 口语 → 书面改写（可选，保真红线见下） | — |
| 6 | 关键帧抽帧 + OCR + 字幕带过滤 + 幻灯片聚类配图 | `figures.json` + `frames/*.jpg` |
| 7 | EPUB / DOCX 构建（pandoc） | `book.epub` |
| 8 | 审计：覆盖对账 + EPUB 结构校验 | `EBOOK_AUDIT.md` |

**保真红线**：改写只允许补标点、删口头禅、合并重复、顺语序；
**不得添加视频里没说过的事实、数据、结论**。拿不到画面就如实标注，绝不生成假图。

## 实测结论（避免你重复踩坑）

| 事项 | 结论 |
|---|---|
| 视频元数据 | ✅ 无需登录即可获取 |
| 官方 CC / AI 字幕 | ❌ **必须登录**，否则只列出弹幕 |
| 音频流 | ✅ 无需登录（m4a 最高 122k） |
| 弹幕 | ✅ 无需登录 |
| cookie 有效期 | ⚠️ 通常十几天，用前先验 `isLogin` |
| B 站搜索接口 | ❌ 风控（412），请直接传 BV 号 |
| pandoc 2.12 | ⚠️ 不支持 `--split-level`；无 xelatex 则不能直出 PDF |
| 术语归正 | ⚠️ **不能用 `\b`**：中英之间无词边界，必须用 lookaround |
| huggingface_hub | ⚠️ 可能下载失败，改用 requests 直拉模型文件（已内置该回退） |
| Windows 管道输出 | ⚠️ 控制台默认 GBK，非 tty 时强制 UTF-8，否则打印 emoji 会直接崩 |
| 幻灯片标题卡 | ⚠️ 阈值不能"自适应"：幻灯片长度均匀时会把阈值压到 20 出头，一张卡都认不出 |

## 目录结构

```
bilibili-to-ebook/
├── README.md · SECURITY.md · LICENSE · pyproject.toml · .gitignore
├── .github/workflows/ci.yml        # Linux + Windows × py3.9/3.12，跑测试与发布前扫描
├── skills/
│   └── SKILL_BILIBILI_TO_EBOOK.md  # 流水线权威指令（给 LLM / 人读的规范）
├── src/bbook/                      # 实现（11 个模块）
│   ├── paths.py     工作目录契约 · 断点续跑状态 · 跨平台字体/工具探测
│   ├── fetch.py     Phase 1-2：元数据 / 官方字幕 / 音频 / 弹幕 / cookie 校验
│   ├── asr.py       Phase 2：faster-whisper 本地转写（模型自动下载、镜像回退）
│   ├── text.py      Phase 3：段落化 + 术语归正（CJK 安全 lookaround）
│   ├── chapters.py  Phase 4：自动切章（简介时间点 → 幻灯片标题卡 → 时长兜底）
│   ├── frames.py    Phase 6：抽帧 + OCR + 字幕带过滤 + 幻灯片聚类
│   ├── book.py      Phase 7-8：Markdown / EPUB / DOCX 构建 + 审计
│   ├── series.py    多 P / 合集 → 一整本书
│   └── cli.py       CLI 入口（12 个子命令）
├── terms/ai-coding.json            # 可插拔术语表（AI / 编程领域，68 条）
├── tests/                          # pytest 用例 + 假数据夹具（不需要模型即可跑）
│   ├── test_text.py · test_chapters.py · test_book.py · test_paths.py
│   └── fixtures/                   # 合成 ASR 分段 / 幻灯片 OCR / 视频简介
└── tools/preflight_scan.py         # 发布前扫描：凭据 / 大文件 / 版权风险
```

> `examples/`（用 CC 授权视频产出的示例电子书）与 `docs/` 尚未创建，见路线图。

## 路线图

- [x] **CLI 化**：`bbook probe/audio/asr/clean/build/run` 单入口，**零硬编码路径**
- [x] **断点续跑**：阶段状态写入 `state.json`，重跑自动跳过已完成阶段
- [x] **术语表插件化**：`terms/ai-coding.json`（68 条），可继续加金融 / 医学等
- [x] **零依赖 EPUB 构建**：内置纯 Python EPUB3 构建器，pandoc 缺失时自动回退
- [x] **跨平台**：字体自动探测（Windows / macOS / Linux），无 PowerShell 依赖
- [x] **配图版**：抽帧 + OCR + 字幕带过滤 + 幻灯片聚类 → 每章 3 张图（`bbook frames`）
- [ ] **精编版**：口语 → 书面改写（默认不做，保真是当前底线）
- [ ] **精编版**：口语 → 书面改写
- [ ] **配图版**：抽帧 + OCR 插入章节
- [x] **多 P / 合集** → 一整本书：**一章 = 一个分 P**，标题自动取自 B 站分 P 名（`bbook series`）
- [ ] **可点击时间戳**：EPUB 内链跳回视频对应秒数
- [x] **自动切章**：简介时间点 → 幻灯片标题卡 → 时长兜底，三级自动降级（`bbook chapters`）
- [x] **打包安装**：`pip install -e ".[all"]` + `bbook` 命令
- [ ] **CI**：假 ASR 输出的 golden test + lint（不需要下载模型即可跑）
- [ ] **EPUBCheck 集成**：目前只有自研结构检查；W3C 官方校验器需要 Java
- [ ] **兜底构建器已修**：nav 命名空间 / manifest properties="nav" / dcterms:modified 均已补齐

## 版权与致谢

- 本项目**只做格式转换，不产生内容**。生成物的版权归原视频作者所有。
- 若原视频标注 CC BY-SA 4.0 等协议，请遵守署名与相同方式共享要求。
- 请勿将生成物用于商业分发。
- 灵感与验证来自实际把 Stanford MS&E435 课程与 B 站技术视频做成可读文本的过程。

## License

- 代码：**MIT**（待定，欢迎建议）
- 文档与 Skill：**CC BY-SA 4.0**
