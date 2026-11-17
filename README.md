# 分布式网页抓取调度平台

面向分布式网页抓取任务调度、节点协同、请求分配、反爬策略编排、数据校验入库与抓取质量大盘的采集工程管理平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集节点 | `worker` | 工作节点 | 节点编号、主机地址、并发槽位数 |
| 请求分配 | `dispatch` | 分配策略 | 策略编号、目标域名、分配算法 |
| 抓取作业 | `crawljob` | 作业定义 | 作业编号、目标站点、起始URL |
| URL过滤 | `urlfilter` | 过滤规则 | 规则编号、包含模式、排除模式 |
| DNS解析 | `dnsresolver` | 解析配置 | 配置编号、域名模式、DNS服务器 |
| 内容提取 | `contentextract` | 提取器 | 提取器编号、内容类型、正文选择器 |
| 存储策略 | `storagestrategy` | 存储方案 | 方案编号、存储类型、连接参数 |
| 渲染任务 | `rendertask` | 渲染作业 | 作业编号、目标URL、浏览器版本 |
| 采集质量 | `qualityreport` | 质量结论/报告快照 | 报告编号、作业编号、总URL数、成功/失败URL数、内容完整率、字段覆盖率 |
| 带宽控制 | `bandwidth` | 带宽策略 | 策略编号、节点标识、下载带宽上限 |
| 重试队列 | `retryqueue` | 重试条目 | 条目编号、失败URL、失败原因码 |
| 翻页管理 | `pagemarker` | 翻页规则 | 规则编号、目标站点、翻页类型 |
| 增量标记 | `incrementmark` | 增量水位 | 水位编号、目标源、增量字段名 |
| 配置同步 | `configsync` | 同步任务 | 任务编号、源节点、目标节点 |
| 采集API | `scrapeapi` | API定义 | API编号、API名称、请求路径 |
| 数据抽样 | `datasample` | 抽样方案 | 方案编号、数据源、抽样方式 |
| 采集告警 | `alertpolicy` | 告警策略 | 策略编号、监控指标、触发条件 |

## 采集质量：结论与报告快照

采集质量不再人工填写指标。指标一律由「抓取URL结果 + 字段核验清单」计算：

- **数据来源**：`app/seed_quality.py` 提供每个作业的 URL 结果（状态、失败原因码、各结构化字段值）
  与字段核验清单（结构化字段数、抽检URL数、申报的结构化字段完整率）。
  计算内核在 `app/services/qualitycore.py`，服务与接口在 `app/services/qualityreport.py`。
- **口径**：`成功URL数 + 失败URL数 ≡ 总URL数` 恒等校验；失败URL按零覆盖计入全量分母，
  同时单独给出「成功页完整率」；字段核验侧申报的完整率会与重算值核对。
- **结论边界**：零URL、全部失败、部分失败、字段缺失、提取版本冲突、字段核验缺失、
  完整率核对不一致、计数不一致、状态无法识别都会写进快照并给出可读说明。
  其中零URL / 版本冲突 / 字段核验缺失 / 完整率不一致属于不可确认边界。
- **版本**：每次生成写入一条新结论与一份不可变快照，快照带 SHA-256 校验和；
  重算只追加版本，历史快照不改写。同一作业任意时刻至多一个「已确认」版本。
- **幂等与并发**：生成以输入摘要（作业 + 提取版本 + URL结果 + 字段核验）去重，
  同一份输入连续或并发提交只生效一次；确认同样支持请求编号去重。
- **回写**：确认后把结论编号、快照编号、版本号、结论等级回写到字段核验清单，
  质量报告清单同步更新状态与指标。
- **对外呈现**：报告视图默认读取已确认快照（指标概览、字段覆盖分布、失败URL对照、
  URL结果追溯、版本历史），并逐项对照「已确认值 / 当前源数据重算值」。

主要接口（前缀 `/api/qualityreport`）：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /sources` | 读取URL结果与字段核验来源，含成功+失败合计一致性 |
| `GET /field-verifications` | 字段核验侧清单与最近一次回写 |
| `POST /generate` | 计算指标、固化快照、生成结论（幂等） |
| `POST /conclusions/{id}/confirm` | 确认版本、取代旧版本、回写字段核验清单 |
| `GET /dashboard?job=` | 质量报告视图数据（默认已确认快照） |
| `GET /dashboard?job=&snapshot_id=` | 追溯指定历史已确认快照 |
| `GET /conclusions`、`GET /snapshots` | 版本与快照清单（快照含校验和） |
| `POST /{id}/actions` | 归档报告（已取代版本可归档） |

运行约束测试：

```bash
cd backend && .venv/bin/python -m unittest tests.test_quality -v
```

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.tsx`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
