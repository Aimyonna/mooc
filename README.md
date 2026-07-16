# MOOC 课程信息采集系统


---

## 一、项目定位与业务价值

### 1.1 项目目标

从 **中国大学 MOOC 平台「一流课程」频道** 自动采集 **「正在进行」** 的全部课程元信息，包含课程名称、所属院校、主讲教师、教师团队、参加人数、课程简介等 8 个字段，结构化存入 MySQL，为课程分析、检索和可视化提供数据基础。

### 1.2 业务价值

| 维度 | 说明 |
|------|------|
| **数据血缘** | 全量数据来源于 icourse163.org 官方页面，字段一一对应页面 DOM，可溯源、可校验 |
| **时效性** | 支持一键重跑，`TRUNCATE + 全量重采` 模式保证数据与平台同步，无增量脏数据风险 |
| **可维护性** | 三脚本流水线（登录→采集→入库），职责单一；选择器集中管理，改版可快速定位修复 |
| **可扩展性** | `CHANNELS` 列表驱动，新增频道/学科方向仅需一行配置；多频道并行架构已就绪 |

---

## 二、系统架构与爬取链路

### 2.1 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 语言 | Python 3.13 | — |
| 浏览器自动化 | Selenium 4.x + ChromeDriver | 页面交互 / DOM 提取 / 模拟点击 |
| 驱动管理 | 自研 `chrome_service()` | 优先本地离线缓存，兜底 webdriver-manager |
| 并发框架 | `concurrent.futures.ThreadPoolExecutor` | 多频道并行（各频道独立 WebDriver） |
| 数据库 | MySQL | pymysql 驱动 |
| 配置管理 | python-dotenv | `.env` 加载敏感信息 |
| 日志 | logging + RotatingFileHandler | 双通道：控制台 ERROR only / 文件 INFO 全量轮转（10MB × 5） |

### 2.2 项目结构

```
mooc4_2/
├── .env                 # 敏感配置（DB密码/浏览器模式）
├── .env.example         # 配置模板
├── .gitignore           # GitHub Python 标准 + .recall/ .claude/ CLAUDE.md
├── requirements.txt     # selenium, pymysql, python-dotenv, webdriver-manager, requests
│
├── config.py            # 统一配置中心：.env 加载 | 日志工厂 get_logger() | chrome_service()
├── cookie.py            # 登录凭证生成器：扫码 → 自动检测登录 → cookies.json
├── discover.py          # 课程发现器：纯 Selenium 采集全字段 → courses.json
├── main.py              # 数据库加载器：读 courses.json → TRUNCATE → 批量 INSERT
│
├── cookies.json         # 登录凭证（不入 git）
├── courses.json         # 完整课程元数据（discover 输出 → main 输入）
├── courses.txt          # 可读 URL 列表（discover 输出）
│
└── logs/crawler.log     # 运行时日志（10MB × 5 轮转，不入 git）
```

### 2.3 完整数据流

```
                 扫码登录
                 ┌──────────┐
                 │ cookie.py│
                 └────┬─────┘
                      │ cookies.json
                      ▼
┌──────────────────────────────────────────────────────────────┐
│  discover.py（纯 Selenium · 多频道并行）                       │
│                                                              │
│  频道页 ─→ 点「全部课程」─→ 点「正在进行」筛选                  │
│     │                                                        │
│     │  每页 20 张卡片（#channel-course-list）                    │
│     ▼                                                        │
│  ┌─────────────────┐  点 h3 开新 tab  ┌─────────────────────┐ │
│  │  卡片 DOM        │ ──────────────→ │  详情页 DOM          │ │
│  │  cCourse (h3)    │                 │  url/courseId       │ │
│  │  cCollege (p)    │                 │  cTeam (教师滑块)     │ │
│  │  cTeacher (div)  │                 │  cCount (正则 人参加) │ │
│  │  status (状态校验)│                 │  cBrief (meta desc)  │ │
│  └─────────────────┘                 └──────────┬──────────┘ │
│                                                 │            │
│  关 tab → 回频道页 → 下一张卡 → 翻页（下一页）      │            │
│  末页：首卡名不变 → timeout → 自动停               │            │
└─────────────────────────────────────┬─────────────┘
                                      │ courses.json (courseId 去重)
                                      ▼
                  ┌──────────┐
                  │ main.py  │
                  │ TRUNCATE │
                  │ INSERT   │
                  └────┬─────┘
                       ▼
              MySQL course_info 表
```

### 2.4 字段提取方式

| 字段 | 来源 | 方法 | 备注 |
|------|------|------|------|
| `courseId` | 详情页 URL | 正则 `/course/[^/]+-(\d+)` | 平台全局唯一数字 ID，varchar 存储 |
| `url` | 详情页地址栏 | `driver.current_url`，去 query | 形如 `https://www.icourse163.org/course/NUDT-17002` |
| `cCourse` | 卡片 DOM | `card.querySelector('h3').innerText` | 课程全名 |
| `cCollege` | 卡片 DOM | h3 的下一个 `<p>` 元素 | 院校名 |
| `cTeacher` | 卡片 DOM | `<p>` 的下一个 `<div>` 元素 | 主讲教师 |
| `cTeam` | 详情页 DOM | `.m-teachers_teacher-list` 内所有 `img[alt]` | 中顿号「，」拼接 |
| `cCount` | 详情页 innerText | 正则 `(\d[\d,]*)\s*人参加` | 逗号去除后 INT |
| `cBrief` | 详情页 `<meta name=description>` | 截取 `spContent=` 之后内容，去尾缀 | ~5% 课程 spContent 不存在，值为空 |

### 2.5 运行步骤

```bash
pip install -r requirements.txt

# 1. 扫码登录，生成 cookies.json
python cookie.py

# 2. 采集全部课程 → courses.json（约 12-15 分钟 / 频道）
python discover.py

# 3. 入库 MySQL
python main.py
```

---

## 三、核心难点与攻关方案

### 3.1 API 路线被截断：从 `requests` → CDP 被动监听 → 纯 Selenium DOM

**第一次尝试：requests 库模拟 API**

最初方案是直接调 `mocSearchBean.searchCourseCardByChannelAndCategoryId.rpc` 等 RPC 接口。运行即返回 `code=-1002, message=非法跨域请求`，即使 `cookie.py` 重新登录刷新凭证也无效。

**问题本质**：icourse163 服务端做 TLS 指纹（JA3）校验 + 请求头完整性检查。requests 库发出的请求与浏览器原生请求指纹不同——缺少完整的浏览器级 TLS 握手特征和 `Sec-*`/`X-Requested-With` 等请求头。

**第二次尝试：CDP 被动监听**

思路转向"让浏览器自己发请求，只监听不干预"：开 Chrome DevTools Protocol 性能日志 → 拦截 `Network.responseReceived` 事件 → `Network.getResponseBody` 抢读响应 JSON → 解析课程列表。

**新问题**：Chrome 网络缓冲极小，`Network.getResponseBody` 必须在响应返回后**秒级**抢读——超过 6 秒缓冲即被清空，调用静默失败。初版等全部请求完成再批量 dump，结果全部返回空。

**CDP 方案的最终收敛**：改为 0.5s 间隔轮询性能日志，匹配到目标 URL 立刻抢读，抢到即停，10s 超时。这个方案**能拿到数据**——但在进频道列表页时，`commonBean.obtain.rpc`（发现终点）返回的非课程列表数据、而真正课程列表在 `mocSearchBean.searchCourseCardByChannelAndCategoryId.rpc`（搜索端点），且 CDP 依赖 `csrfKey` 有效性，路由逻辑复杂。

**最终方案：纯 Selenium DOM 爬取**

用户决策放弃 API/CDP，改用纯 Selenium——频道页点筛选 → 翻页 → 读卡片 DOM → 点 h3 进详情页 → 读详情 DOM。**零 API 调用，零 JS 注入，零网络请求前置条件**。

> **结论**：在服务端做 TLS 指纹校验的平台，绕过 API 的成本（CDP 抢缓冲 + csrfKey 维护 + 端点路由追踪）高于直接模拟用户操作。**让浏览器就是浏览器**，是该平台的最优爬取策略。

### 3.2 React SPA 卡片：无 `<a href>`，URL 藏在点击行为里

icourse163 频道页是 React SPA，课程卡是 `<div>` 组件，卡片内**没有 `<a href="/course/...">` 链接、没有 `data-courseid` 属性、没有内嵌 JSON**。`schoolSN` 和 `courseId` 只存在于 React 组件 state 中——要拿到它们，必须触发导航事件。

**攻关过程**：

| 尝试 | 结果 |
|------|------|
| 搜 `a[href*='/course/']` | 0 命中（无标准链接） |
| 搜 `data-*` / onclick 属性 | 不存在（React 事件委托） |
| 搜 innerText 中的 URL 模式 | 不存在（URL 不在文本里） |
| 点卡根 `div.commonCourseCardItem` | 无反应（onClick 绑在子元素） |
| **点卡内 `h3`** | ✅ **新标签页跳 `/course/{schoolSN}-{courseId}`** |

**最终方案**：每张卡点 h3 → 开新标签页 → 读 `driver.current_url` → 正则解析 `schoolSN` 与 `courseId`（末尾数字，平台全局唯一）。新 tab 模式不扰动频道页的筛选状态和分页位置，读完即关，干净回切。

### 3.3 CSS-Modules 哈希类名：选择器一碰即碎

页面大量使用 CSS-Modules 编译出的哈希类名（如 `_2mbYw`、`_1Zkj9`、`_3DcLu`），每次前端发版都会变化。若选择器依赖哈希类，发版即挂。

**解决方案**：只用两类选择器——

| 类别 | 示例 | 原因 |
|------|------|------|
| **读类名** | `commonCourseCardItem` | 开发者保留的非哈希稳定标识 |
| **结构化** | h3 → `nextElementSibling` → p → div | 相对兄弟位置，不依赖类名 |
| **ID** | `#channel-course-list` | DOM id，通常稳定 |
| **关键词文本** | XPath `//*[normalize-space(text())="下一页"]` | 控件文字标签，改版不改词 |
| **属性前缀** | `[class*='course-title']` | 部分匹配，容忍版本变化 |

### 3.4 翻页检测：不靠 class 判末页

页码上的"活动页"标识也是哈希类（`_6jBq`），不能用。上一页/下一页禁用态同样靠 class。

**解决方案**：**"首卡名变化法"**——每页开始前记录第 1 张卡的课程名（`h3.innerText`），点"下一页"后轮询等待首卡名更新；若 8 秒内首卡名不变，说明已到末页（下一页按钮未生效或无下一页）。不依赖任何 class。

### 3.5 环境级拦路：webdriver_manager 在国内到 googleapis 被 reset

`webdriver_manager` 每次调用 `install()` 都会联网查最新 ChromeDriver 版本号。国内网络到 `googleapis` 的连接不稳定，频繁被 reset（WinError 10054），导致**所有 Selenium 脚本直接起不来**，而非爬虫逻辑问题。

**解决方案**：`config.py` 自研 `chrome_service()`——

```python
def chrome_service():
    # 优先查本地缓存 .wdm/ 和 .cache/selenium/ 中的 chromedriver.exe
    # 按四段版本号排序取最高 → 完全离线启动
    # 缓存不存在才退回 webdriver_manager（联网兜底）
```

Windows 下缓存路径为 `%USERPROFILE%\.wdm\drivers\chromedriver\win64\<version>\chromedriver-win32\chromedriver.exe`。Chrome 升级后需要新版本缓存到位，否则回退仍可能失败（需运行一次 `cookie.py` 触发 webdriver_manager 下载）。

---

## 四、数据库设计与清洗规范

> *此部分涉及表结构 DDL 与清洗逻辑，若不清楚可留白，由用户根据实际 MySQL 部署补充。*

### 4.1 表结构

```sql
CREATE TABLE IF NOT EXISTS course_info (
    courseid VARCHAR(50)  NOT NULL PRIMARY KEY,    -- 从URL解析的课程ID（数字字符串，平台全局唯一）
    url      VARCHAR(255) UNIQUE,                  -- 课程详情页完整URL
    cCourse  VARCHAR(255),                         -- 课程名称
    cCollege VARCHAR(255),                         -- 所属院校
    cTeacher VARCHAR(255),                         -- 主讲教师
    cTeam    TEXT,                                 -- 教师团队
    cCount   INT UNSIGNED DEFAULT 0,               -- 参加人数
    cBrief   TEXT                                  -- 课程简介
);
```

### 4.2 主键策略

| 对比项 | 自增 `id` | `courseid`（采用） |
|--------|----------|-------------------|
| 重跑幂等性 | 需额外 UNIQUE 列去重 | 天然按主键 `ON DUPLICATE KEY UPDATE` |
| 跨表关联（未来） | 无意义数字，需 JOIN 查课程 | courseid 本身是 FK，见键知课 |
| 存储体积 | INT UNSIGNED 4 字节 | VARCHAR(50) 最多 50 字节 |
| 跨平台扩展 | 通用，可多平台数据并表 | 锁定 icourse163 课程 ID 语义 |

> **决策**：单平台爬虫用自然主键 `courseid VARCHAR(50)` 最干净。url 保留 UNIQUE 作二级约束。

### 4.3 数据清洗规范

| 字段 | 清洗操作 |
|------|---------|
| `courseId` | 正则提取末尾数字；空值/非数字跳过整行；全局去重 |
| `url` | `split('?')[0]` 去 query；去首尾空白 |
| `cCourse` / `cCollege` / `cTeacher` | `.trim()` 去空白；空字符串入库（非 NULL） |
| `cTeam` | 中顿号「，」拼接 `img[alt]`；排除 `alt="图片"` 占位符 |
| `cCount` | 正则去逗号 `parseInt`；0 兜底 |
| `cBrief` | 去 `spContent=` 前缀偏移；去 `,中国大学MOOC(慕课)` 尾缀；空字符串兜底 |

### 4.4 入库策略

```
TRUNCATE TABLE course_info           -- 清旧数据（保证表内只有本次采集结果）
  ↓
循环 INSERT ... ON DUPLICATE KEY UPDATE     -- 按 courseid 去重，重叠行更新
  ↓
COMMIT + SELECT COUNT(*) 校验
```

> **为什么 TRUNCATE？** 若只靠 `ON DUPLICATE KEY UPDATE`，上次爬的非目标筛选旧行（如"已结束"课程）不会自动删除，残留混杂。每次全量重采 + 清表，数据一致性最强。

---

## 五、性能指标与采集成果

### 5.1 单频道实测（一流课程 id=2001）

| 指标 | 值 |
|------|-----|
| 目标数据源 | icourse163.org「一流课程」→ 全部课程 → 筛选"正在进行" |
| 总页数 | 8 页（每页 20 门，末页 16 门） |
| **采集课程数** | **156 门** |
| 采集耗时 | ~12 分钟（含详情页导航 waiting） |
| 成功率 | **100%（156 / 156，零失败）** |
| 数据质量 | 见 5.3 质量评估 |

### 5.2 多频道并行效率预估

当前架构已支持多频道并行（`ThreadPoolExecutor`），每频道独立 WebDriver，互不阻塞。以一流课程频道 12 分钟 / 156 门为基准：

| 频道数 | 预计总耗时 | 单频道平均 | 并行加速比 |
|--------|-----------|-----------|-----------|
| 1 | ~12 min | 12 min | 1×（基线） |
| 3 | ~14 min | 4.7 min | **2.6×** |
| 5 | ~15 min | 3.0 min | **4.0×** |
| 10 | ~18 min | 1.8 min | **6.7×** |

> 估算假设：浏览器启动 ~2s / 实例，各频道课程量相近，网络波动均摊。主要瓶颈为各频道详情页数量差异和并发 Chrome 内存开销（单实例 ~300-500MB），建议不超过 5-8 频道同跑。

**启用方式**：`discover.py` 中 `CHANNELS` 列表加条目即可，无需改任何逻辑：

```python
CHANNELS = [
    {"id": 2001, "name": "一流课程"},
    {"id": 2002, "name": "学科方向A"},   # 新增
    {"id": 2003, "name": "学科方向B"},   # 新增
]
```

### 5.3 采集成果质量评估

#### 5.3.1 筛选有效性
日志中抽取全部 156 门课程的卡片状态标记，全部为 `进行至第N周`（N 分布在 1~21 周），**无"已结束"、"即将开课"混入**。筛选准确率 **100%**。

#### 5.3.2 字段完整率

| 字段 | 非空率 | 说明 |
|------|--------|------|
| courseId | 100% | 详情页 URL 均包含合法 courseId |
| url | 100% | 每次详情页跳转均成功读取地址栏 |
| cCourse | 100% | 卡片 h3 始终存在 |
| cCollege | 100% | h3 后 p 始终存在 |
| cTeacher | 100% | p 后 div 始终存在 |
| cTeam | 100% | 滑块翻页取全部页老师 |
| cCount | 100% | innerText 正则始终命中 `N人参加` 模式 |
| cBrief | **~95%** | 约 8 门课程 `<meta description>` 无 `spContent=` 段，为空 |

> **cBrief 空值详情**：少数课程（如"国际金融学"、"测量学"）的 meta description 仅为 `,中国大学MOOC(慕课)` 不含正文。可加兜底（取详情页另一简介元素或 `meta description` 全文），暂未实施。

#### 5.3.3 去重验证

`courses.json` 按 `courseId` 全局去重后 156 门，`course_info` 入库后 `SELECT COUNT(*)` = 156，**零重复**。

#### 5.3.4 courseId 唯一性校验

156 门课程来自 60+ 所不同院校，courseId 跨度从 `24002`（古文字学）到 `1205990801`（技术经济学），无跨校冲突，验证了"courseId 平台全局唯一"假设。

### 5.4 已知局限

| 风险点 | 影响 | 缓解措施 |
|--------|------|---------|
| 站点 DOM 改版（类名/结构变更） | `commonCourseCardItem` 或 `.m-teachers_teacher-list` 失效 | 所有选择器集中在 `discover.py`，单点修复 |
| 翻页误判（同名课程相邻） | 首卡名相同 → 误判末页提前停 | 概率极低（156 门无一同名），可加 `courseId` 双重校验 |
| Chrome 升级 Chromedriver 未缓存 | `chrome_service()` 回退不联网仍失败 | 跑一次 `cookie.py` 触发一次联网下载即可 |
| cBrief 空值 | 约 5% 课程缺少简介 | 可加兜底（见上） |

---

## 六、变更日志

| 日期 | 会话 | 关键变更 |
|------|------|---------|
| 2026-07-14 | — | cookie.py 自动检测登录（替代手动回车），.gitignore 补全 |
| 2026-07-15 上 | CDP 重构 | discover.py：JS 注入 → CDP 被动监听（`_poll_rpc_courses` 轮询抢缓冲） |
| 2026-07-15 下 | **全量重写** | discover.py：CDP 监听 → **纯 Selenium DOM**（频道筛选 + 翻页 + 卡片 + 详情页）。main.py：纯 DB 加载器 + TRUNCATE。config.py 新增 `chrome_service()` 离线驱动。**首发 156 门「正在进行」全量入库** |
