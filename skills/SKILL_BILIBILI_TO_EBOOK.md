# SKILL｜B站视频 → 电子书（EPUB）精读流水线 · 扩展版 v1.0

> **用途**：把 B 站任意视频（单 P / 多 P / 合集 / UP 主系列）转换成**人能坐下来读的电子书**（EPUB3 为主，DOCX / DOCX→PDF 为辅），用于学习、复习、存档、二次阅读。
> **与《SKILL_MSE435_FIDELITY_EDITION.md》的关系**：那份是"英文课程视频 → 双语保真教材"，面向 YouTube，重英文原文逐句对齐；**这份是"中文口播视频 → 可读电子书"，面向 B 站，重可读性与章节化**。两者共享铁律与脚本化思路，产物形态不同。
> **执行者**：任意 LLM 或人类。本文件是唯一权威指令。
> **版本说明**：v1.0 的关键结论均在 2026-09-11 于本机实测（见 §5 实测表），未实测项已标注 ⚠️。

---

## 0.5 现在有 CLI 了（Phase → 命令对照）

本文件描述的是**流水线规范**；仓库里的 \`bbook\` 已经把 Phase 1–8 实现成了命令，
**默认路径不需要手工执行任何一步**：

\`\`\`bash
pip install -e ".[all]"
bbook run "<视频链接>"          # 一条命令出书：Phase 1→8 全自动
\`\`\`

需要逐段核对或排错时，按下面的对照关系单独调用：

| Phase | 做什么 | 命令 | 是否必须人工 |
|---|---|---|---|
| 1 | 元数据 / 分 P 清单 | \`bbook probe <url>\` | 否 |
| 2 | 官方字幕（需登录）或音频 | \`bbook subs\` / \`bbook audio\` / \`bbook cookies\` | 否 |
| 2′ | 本地 ASR 转写 | \`bbook asr <workdir> --model small\` | 否（免费，46 分钟约 13 分钟） |
| 3 | 清洗 + 术语归正 | \`bbook clean <workdir> --terms terms/ai-coding.json\` | 否 |
| 6 | 抽帧 + OCR + 配图 | \`bbook frames <workdir> --url <url>\` | 否 |
| 4 | **切章** | \`bbook chapters <workdir>\` | **自动**（三级降级）；不满意再手改 \`chapters.json\` |
| 5 | 口语 → 书面改写 | 无命令 | 是，且**默认不做**（保真优先） |
| 7–8 | 构建 EPUB / DOCX + 审计 | \`bbook build <workdir>\` | 否 |
| 合集 | 多 P → 一整本书 | \`bbook series <合集url> --limit 3\` | 否 |

**注意 Phase 顺序**：\`frames\`（原 Phase 6）要跑在 \`chapters\`（原 Phase 4）**之前**——
幻灯片的 OCR 结果是自动切章的输入之一。\`bbook run\` 已按这个顺序编排。

其他已实现、规范里未展开的能力：

- **断点续跑**：每阶段完成写 \`state.json\`，中断后重跑自动跳过
- **灵活降级**：没有 pandoc → 用内置零依赖 EPUB 构建器；没有 ffmpeg → 跳过配图；
  没有 faster-whisper → 给出安装命令而不是崩溃
- **发布前检查**：\`python tools/preflight_scan.py .\` 拦下凭据 / 大文件 / 版权风险

---

## 0. 铁律（违反任一条即失败）

1. **单智能体串行执行**。禁止 AgentTeams / 多智能体协作：消息交叉会产生确认循环，直接烧钱。本流水线是线性的。
2. **确定性操作用脚本，不用 LLM 试错**。下载、抽帧、OCR、EPUB 构建、校验全部脚本化，一次跑通。LLM 只负责：读、改写、切章、起标题、解释、审计。
3. **改写不得增删事实**。口语转书面只允许：断句、补标点、去口头禅、合并重复、顺语序。**不得添加视频里没说过的内容，不得编造数据**。改写后的每一句都要能在原字幕里找到出处。
4. **不伪造素材**。拿不到清晰画面就如实标注【低清证据图】或干脆不放图，绝不画假图、不生成假截图。
5. **上下文纪律（最省钱也最保命）**：字幕正文、日志、中间产物**一律落盘**，用 read 按需分段读。**绝不把整份逐字稿贴回对话**。历史里堆大段原文和抓取日志的会话，会被模型服务端风控判为风险，整段会话直接报废，连"你好"都发不出去。
6. **凭据不入对话**。cookies 文件只在脚本里按路径引用，**不要把 cookie 内容打印、粘贴或写进任何 markdown**。
7. **版权红线**：电子书仅供个人学习，首页必须有来源声明与原作者署名；不得商用、不得二次分发。

---

## 1. 输入与产出

### 1.1 输入
| 类型 | 形式 | 处理方式 |
|---|---|---|
| 单个视频 | https://www.bilibili.com/video/BVxxxxxxxxxx/ | 一本小册子（3–8 章） |
| 多 P / 合集 | 同上，页面上有分 P | **一个 P 一章**，合成一本书 |
| UP 主系列 | 主页 / 合集页 | 每个视频一章，先出目录再分批做 |
| 仅字幕文本 | 用户手工导出的 .txt/.srt | 直接跳到 Phase 3 |

### 1.2 产出
**主交付**：1) 书名.epub —— EPUB3，含封面、目录、章节分页、元数据
**辅助交付**：2) 书名.docx（便于二次编辑/打印）3) 书名.md（主稿源文件）4) 章节结构.csv（章号/标题/起始时间/分P/字数）5) 术语表.md、金句集.md 6) 字幕清洗稿.txt 7) EBOOK_AUDIT.md

**电子书内部结构（固定顺序）**
封面 → 版权与来源页 → 前言（标题/UP主/时长/链接/整理日期）→ 目录（自动）→ 正文各章 → 附录A 术语表 → 附录B 金句集 → 附录C 时间轴索引（章节 ↔ 视频时间点）。

---

## 2. 环境（本机已实测，2026-09-11）

| 组件 | 状态 | 路径 / 版本 |
|---|---|---|
| yt-dlp | ✅ | 本机 Python312 Scripts 下，版本 2026.08.19 |
| ffmpeg / ffprobe | ✅ | C:\Users\86131\AppData\Local\ffmpeg\ffmpeg-8.1-essentials_build\bin\ |
| pandoc | ✅ | D:\anaconda3\Scripts\pandoc.exe，**2.12**（注意版本坑，见 §6） |
| python | ✅ | 3.12，已装 PIL / onnxruntime / torch / requests / rapidocr_onnxruntime |
| deno | ✅ | C:\deno\deno.exe（不在 PATH，用绝对路径） |
| 中文字体 | ✅ | C:\Windows\Fonts\msyh.ttc（生成封面用） |
| calibre（ebook-convert） | ❌ 未安装 | 不需要；pandoc 足够 |
| xelatex | ❌ 未安装 | **pandoc 直接出 PDF 不可用**，要 PDF 走 Word 另存 |
| faster-whisper / FunASR | ❌ 未安装 | 仅当需要 ASR 兜底时才装（见 Phase 2） |

---

## 3. 字幕获取：三条路（按优先级）

### 路 A｜登录 cookies 取官方字幕（首选：质量最高、零 ASR 成本）
B 站的 CC 字幕 / AI 字幕**必须登录才能取**。不登录时 yt-dlp 只会列出 danmaku（弹幕），**列不出任何字幕轨**——这是实测结论，不要反复重试。

```powershell
# 1) 先关闭 Chrome（Chrome 运行时 Cookie 数据库被锁）
# 2) 列出字幕轨
yt-dlp --cookies-from-browser chrome --list-subs "https://www.bilibili.com/video/BV.../"
# 3) 或用已导出的 Netscape 格式 cookies 文件
yt-dlp --cookies "D:\商业知识库\Stanford-MSE435\_assets\bilibili_cookies_clean.txt" --list-subs "URL"
# 4) 下载字幕
yt-dlp --cookies <cookies文件> --skip-download --write-subs --sub-langs "ai-zh,zh-CN,zh-Hans" -o "%(title)s.%(ext)s" "URL"
```

**本机已有的 cookie 提取脚本**：_assets\extract_bilibili_cookies.py（解密 Chrome v10/v20 AES-GCM cookie，导出 bilibili / bilivideo / hdslb / biliapi 域的 Netscape 文件到 _assets\bilibili_cookies_clean.txt）。直接用即可，**不要打开这个 txt 看内容**。

**⚠️ 先验证 cookies 是否过期（30 秒，必做）**：实测 SESSDATA 会在十几天内失效，失效表现就是"字幕轨凭空消失"。判定脚本：

```python
# code:-101 且 isLogin:False  => cookies 已过期，必须让用户重新登录 B 站后重新导出
import json, http.cookiejar, urllib.request
jar = http.cookiejar.MozillaCookieJar(r"<cookies文件路径>")
jar.load(ignore_discard=True, ignore_expires=True)
req = urllib.request.Request("https://api.bilibili.com/x/web-interface/nav",
    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})
d = json.load(urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)).open(req, timeout=20))
print(d.get("code"), d.get("data", {}).get("isLogin"), d.get("data", {}).get("uname"))
```

> 实测记录：_assets\bilibili_cookies_clean.txt（2026-08-31 导出）在 2026-09-11 已返回 **-101 / isLogin:False**，即**已失效**。要走路 A，必须让用户重新登录并重新导出。

### 路 B｜无登录：音频下载 + 本地 ASR（兜底，**已验证可行**）
不登录也能拿到音频流（实测该视频有 30216 / 30232 / 30280 三条 m4a，最高 122k、约 16 MB / 18.5 分钟）与 720p 以下视频流。所以**没有 cookies 也能做**，只是把"取字幕"换成"本地转写"。

```powershell
# 1) 只下音频（体积小、速度快）
yt-dlp -f 30280 -x --audio-format m4a -o "audio.%(ext)s" "URL"
# 2) 安装转写引擎（一次性，CPU 可跑）
python -m pip install faster-whisper
# 3) 中文转写
python -c "from faster_whisper import WhisperModel; m=WhisperModel('small'); segs,info=m.transcribe('audio.m4a', language='zh', vad_filter=True); open('asr.txt','w',encoding='utf-8').write('\n'.join(s.text.strip() for s in segs))"
```

- 模型档位：small 够用且快；术语密集的技术视频用 medium；有 GPU 或要求更准用 large-v3。
- 中文技术视频的英文术语必被听错（实测把 "DeepSeek Harness" 听成 "deep sink honeys"），**Phase 3 必须做术语归正**。
- funasr（Paraformer-zh）对中文口播更准，但依赖更重；本机未装，属 ⚠️ 未实测选项。

### 路 C｜用户手工提供字幕（最省事，卡住就优先选它）
用户在 B 站播放器导出 SRT/VTT，或直接给文本，跳过 Phase 1–2 直接进 Phase 3。

---

## 4. 流水线 Phase 1–8

### Phase 1｜元数据与分 P 清单
```powershell
yt-dlp --no-warnings --skip-download -J "URL" | Out-File -Encoding utf8 meta.json
```
提取：标题 / UP 主 / 时长 / 简介（**简介里的章节时间点是切章的黄金线索**）/ 分 P 列表 / 封面 URL / 发布日期。
> 实测：**无需登录即可取到全部元数据**（标题、UP 主、时长 1112.9s 一次成功）。
产出 meta_summary.md（只留标题/UP/时长/链接，别把整个 JSON 贴回对话）。

### Phase 2｜字幕 / 音频获取
按 §3 选路。产物统一规范化为**带时间戳的行式文本**：
```text
[00:00:12] 大家好
[00:00:15] 今天我们来讲一下……
```
时间戳是后面做"时间轴索引"和"章节配图"的锚点，**必须保留**。

### Phase 3｜字幕清洗（质量分水岭）
1. **合并短句**：B 站字幕多为 8–15 字一行，需按标点与语义合并成 80–220 字的自然段。
2. **去噪**：删除 [音乐] [掌声]、纯语气词行、重复滚动的同一句。
3. **ASR 术语归正**：建立术语映射表（deep sink honeys → DeepSeek Harness 等），脚本全局替换；**只改明显的听写错误，不改原意**。
4. **ASR 校注**：无法确定的专有名词用【疑似：XXX】标注，**不静默篡改**。
5. **段落化**：一段一个话题点，超过 260 字必须拆。
产出：字幕清洗稿.txt + 术语表.md（术语首现格式：原词（中文，缩写））。

### Phase 4-A｜合集模式：一章 = 一个分 P（免人工切章）

当输入是**多 P / 合集**时，不需要人工判断章节边界——**一个 P 天然就是一章**。

```bash
python -m bbook series "<合集URL>" --limit 3 --interval 15
```

- **分 P 标题必须走 B 站 `view` 接口的 `pages[].part`**：
  yt-dlp 对合集里每个 P 都返回同一个合集标题，直接用它会导致所有章同名（已实测）。
- 分 P 名需清洗：去编号前缀（`1-1.`）、去画质后缀（`-1080P 高清-AVC`）。
- 每个分 P 独立一个工作目录，各自跑完 Phase 1–6 后合并；索引统一换算为全局段落号。
- **时间轴必须带 P 号**（`P1 00:00:00`）：各 P 时间都从 00:00 起，不带 P 号会误导读者。
- 模型缓存放全局目录（`~/.cache/bbook/models`），否则每个 P 都会重新下载 460MB。

### Phase 4-B｜单视频：章节切分（优先级从高到低）
1. **视频简介里的章节时间点**（UP 主多数会写，最权威）；
2. **多 P / 合集**：一个 P 一章，天然正确；
3. **语义转折检测**：找"接下来""然后我们看""最后总结一下"这类引导词；
4. **纯时长兜底**：每章 2000–4000 字（约 8–15 分钟口播）。
**章标题必须重写**，不能直接用"大家好今天我们来聊一个在 agent 领域的"这种截断句。标题要求：≤16 字、说清这一章讲什么、动词或名词短语开头。

### Phase 5｜口语 → 书面改写（保真红线 §0.3）

| 允许 | 禁止 |
|---|---|
| 补标点、断长句 | 添加视频没说的事实、数据、结论 |
| 删口头禅（"对吧""就是说""这个这个"） | 改变原意、立场、语气强弱 |
| 合并重复表述 | 把"我不确定"改写成"可以确定" |
| 顺语序、加小标题 | 编造案例、人名、数字 |
| 术语统一 | 把推测写成断言 |

改写后逐章自检：随机抽 5 段，回原文核对语义一致。

### Phase 6｜配图（**已实现**：bbook frames）

命令：
```bash
python -m bbook frames <workdir> --interval 10 --per-chapter 3 --min-chars 20
```

算法（对"口播 + PPT"型中文长视频实测有效）：
1. **抽帧**：ffmpeg `fps=1/10`，缩放到 960 宽（46 分钟视频 → 275 张，几十秒完成）；
2. **丢弃底部字幕带**：OCR 出的文本框若中心落在画面高度 78% 以下，一律丢弃。
   这一步是分水岭——不丢的话每帧都有字幕文字，人脸镜头和幻灯片无法区分；
3. **聚类**：相邻帧按"汉字集合 + 英文词"的 Jaccard 相似度 ≥ 0.5 合并为同一段幻灯片；
4. **选代表帧**：取该段中 OCR 字数最多的一帧；
5. **过滤**：段落跨度 < 5 秒、或代表帧字数 < 20 的整段丢掉（多为转场/人脸）；
6. **分配**：按时间戳落到所属章节，章内均匀取点（默认每章 3 张），
   并定位到时间上最近的段落，构建时插图到该段之后。

产物 `figures.json` + `frames_ocr.json`；图注格式 `图 X-Y　视频 HH:MM:SS 处画面`，**时间点必须真实**。

实测（46 分钟纯 PPT 视频）：275 帧 → 识别 69 段候选幻灯片 → 每章 3 张共 33 张，
EPUB 1.74 MB，正文覆盖仍为 100%。

> ⚠️ **pandoc 解析相对图片路径用的是 cwd，不是输入文件所在目录**。
> 若在别处执行 `pandoc book/book.md`，插图会变成指向 EPUB 外部（`../frames/x.jpg`）的死链，
> 且 pandoc **不报错**。必须在工作目录下执行（`cwd=工作目录`），构建后务必核对 EPUB 内图片数。

### Phase 7｜电子书构建（pandoc，一次到位）
**封面生成**（字体用 C:\Windows\Fonts\msyh.ttc）：
```python
from PIL import Image, ImageDraw, ImageFont
img = Image.new("RGB", (1200, 1600), (24, 28, 38)); d = ImageDraw.Draw(img)
f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 84)
d.text((120, 420), "书名第一行", font=f, fill=(255, 255, 255))
d.text((120, 530), "书名第二行", font=f, fill=(255, 255, 255))
img.save("cover.png")
```
**构建**（✅ 已实测通过）：
```powershell
pandoc book.md -o book.epub --toc --toc-depth=2 --epub-cover-image=cover.png --metadata lang=zh-CN
```
主稿 md 的 YAML 头：
```yaml
---
title: "书名"
subtitle: "副标题"
author: "视频作者：B站 @UP主名"
lang: zh-CN
rights: "内容版权归原作者所有，本电子书仅供个人学习使用"
---
```
- **一级标题（#）= 章**，pandoc 自动为每章生成独立 xhtml 与目录项。
- 转 DOCX：pandoc book.md -o book.docx --toc；要 PDF 再用 Word 另存（本机无 xelatex）。
- 想要 AZW3 / Kindle：EPUB 直接用「Send to Kindle」即可，无需 calibre。

### Phase 8｜审计与交付
EBOOK_AUDIT.md 必含：
1. **覆盖对账**：清洗稿字数 vs 电子书正文字数（差异 >2% 需解释：是删了语气词还是漏段）；
2. **章节完整性**：章数 = 计划章数；每章非空；目录项数 = 章数；
3. **EPUB 结构校验**（脚本）：
```python
import zipfile
z = zipfile.ZipFile("book.epub")
assert z.read("mimetype").decode() == "application/epub+zip"
print([n for n in z.namelist() if "/text/" in n])   # 应含 cover / title_page / ch001…chNNN
```
4. **抽查**：随机 5 段与原文核对；术语首现格式；图片时间点真实；版权声明在位。
5. **PASS 条件**：结构校验通过 + 覆盖 ≥98% + 无编造内容 + 版权声明在位。

---

## 5. 实测结论表（2026-09-11，本机命令行实测）

| 环节 | 结论 | 证据 |
|---|---|---|
| 元数据（标题/UP/时长/分P） | ✅ **无需登录可获取** | 测试视频返回 title / uploader / duration=1112.9s |
| 字幕轨（CC / AI 字幕） | ❌ **未登录取不到**，只列出 danmaku | --list-subs 输出仅 danmaku |
| 旧 cookies 是否可用 | ❌ **已过期** -101 / isLogin:False | nav 接口实测 |
| 弹幕下载 | ✅ 无需登录 | 成功得到 danmaku.xml |
| 音频流下载 | ✅ 无需登录（m4a 66k / 91k / 122k） | -F 列出 30216 / 30232 / 30280 |
| 视频流 | ✅ 720p 及以下无需登录；1080P 以上需会员 | -F 提示缺会员 |
| pandoc EPUB3 构建 | ✅ 通过（含封面、目录、9 个 xhtml） | mimetype 与 namelist 校验 |
| 中文文件名 | ⚠️ PowerShell→python 传参会乱码 | 用 **ASCII 中间文件名**，最后再重命名 |
| pandoc 2.12 | ⚠️ **不支持 --split-level** | 报 Unknown option，去掉即可 |
| PDF 直出 | ❌ 无 xelatex | 改走 Word |

---

## 6. 已知坑（照此规避）

1. **别再试"不登录拿 B 站 CC 字幕"**。列不出就是列不出，重试只烧时间；直接问用户要 cookies 或走 ASR。
2. **cookies 会过期**。开工先跑 §3 的 nav 检测，1 个请求定生死。
3. **bilisearch 搜索接口不可靠**（实测 412 / JSON 解析失败，风控）。**让用户直接给 BV 号或链接**，不要靠搜索找视频。
4. **Chrome 开着时 cookie 数据库被锁**，取 cookie 前让用户关掉 Chrome。
5. **中文文件名 + PowerShell + python 组合会乱码**：中间产物一律 ASCII 名（book.md / cover.png），最终交付前再改中文名。
6. **pandoc 2.12 没有 --split-level**；--toc / --toc-depth / --epub-cover-image / --metadata 均可用。
7. **不要把字幕正文贴回对话**（§0.5）。贴了 = 上下文爆炸 + 会话可能被风控整体报废。
8. **自动章标题很难看**（截断句）。必须 LLM 重写标题，这是"电子书"和"字幕堆"的分界线。
9. **术语归正不能用 \b**（实测踩坑）：中文与拉丁字符之间**不存在词边界**（Python 的 \w 包含汉字），所以 \bjason\b、\breg\b、\bpinecoin\b 这类正则在"A的Jason""reg要解决""Pinecoin在B轮"中**一律匹配不到**。必须改用 lookaround：`(?<![A-Za-z0-9])jason(?![A-Za-z0-9])`。第一轮修完务必再扫一遍残余 token。
10. **huggingface_hub 下载模型可能失败**（实测 LocalEntryNotFoundError，而同一网络下 requests 直连返回 200）。绕过办法：用 requests 直接拉 `{ENDPOINT}/{repo}/resolve/main/{file}`，把 config.json / model.bin / tokenizer.json / vocabulary.txt 存到本地目录，再用 `WhisperModel(本地目录)` 加载。small 模型约 461 MB，留存可复用，第二次做视频不用再下。

---

## 7. 参考实现（本机已跑通，可直接抄）

| 文件 | 作用 |
|---|---|
| _work_bilibili\build_demo_book.py | 字幕行 → 合并段落 → 切章 → 生成带 YAML 头的 book.md |
| _work_bilibili\make_cover.py | PIL 生成 1200×1600 中文封面 |
| _work_bilibili\validate_epub.py | EPUB 结构 + 元数据 + 目录校验 |
| _work_bilibili\check_cookies.py | cookies 有效性（isLogin）检测 |
| _work_bilibili\demo_agent_longtask_ebook.epub | **成品样本**：由 B 站字幕文本自动生成的 6 章电子书（含封面与目录） |

反例（自动切章的失败样态，务必人工重写标题）：
第1章 · 大家好今天我们来聊一个在agen  ← 必须改写成 →  第1章 · 长任务 Agent 要解决什么问题

---

## 8. 成本与上下文控制

| 环节 | 成本 | 说明 |
|---|---|---|
| 下载 / 抽帧 / OCR / 构建 / 校验 | ≈0 | 全脚本化，不花 token |
| 清洗 + 切章 + 写标题 + 改写 | 主体成本 | 20 分钟视频约 5000–8000 字，成本很低 |
| 把原文贴进对话 | **禁止** | 真正的成本黑洞 |

**省钱三招**：① 中间产物落盘、read 分段读；② 一章一次处理，不一次性喂全稿；③ 构建只跑最终版，别反复重建。

---

## 9. 交付物清单（单个视频）

1. 书名.epub（主交付）
2. 书名.docx
3. 书名.md
4. 章节结构.csv（章号 / 标题 / 起始时间 / 分P / 字数）
5. 术语表.md、金句集.md
6. 字幕清洗稿.txt
7. EBOOK_AUDIT.md
8. （支撑）meta.json、cover.png、配图帧

---

## 10. 给执行模型的一句启动指令（可直接复制）

```text
请阅读 SKILL_BILIBILI_TO_EBOOK.md 全文，然后按 Phase 1–8 把下面这个 B 站视频做成 EPUB 电子书。
铁律：单智能体串行、脚本化、不得编造、字幕正文不要贴回对话（落盘后分段 read）。
视频链接：<粘贴 BV 链接>
先执行 Phase 1（元数据）与 §3 的 cookies 有效性检测，把结果告诉我，再继续。
```
