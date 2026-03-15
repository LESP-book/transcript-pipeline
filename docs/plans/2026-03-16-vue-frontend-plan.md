# 前端 Web UI —— Vue 3 + TypeScript + FastAPI

## 背景

当前项目的所有功能都通过 CLI 脚本调用。用户希望提供一个本地 Web UI，通过浏览器选择参数并提交任务，替代手动拼命令行。

## 整体架构

```
┌─────────────────────┐        HTTP        ┌─────────────────────┐
│   Vue 3 前端        │  ─────────────────▶ │  FastAPI 后端 API   │
│   (Vite + TS)       │  ◀───────────────── │  (Python)           │
│   localhost:5173     │                    │  localhost:8000      │
└─────────────────────┘                    └──────────┬──────────┘
                                                      │ 调用
                                                      ▼
                                           ┌─────────────────────┐
                                           │  现有 pipeline 模块  │
                                           │  (src/*.py)          │
                                           └─────────────────────┘
```

- **前端**：Vue 3 + TypeScript + Vite，纯 SPA，运行在 `localhost:5173`
- **后端**：FastAPI 薄层 API，运行在 `localhost:8000`，直接调用现有 `src/` 模块
- 前端通过 HTTP 请求后端，后端负责调用 pipeline 逻辑并返回结果

---

## User Review Required

> [!IMPORTANT]
> **前端框架版本**：计划使用 Vue 3 (Composition API) + TypeScript + Vite。前端项目放在 `frontend/` 子目录，与 Python 代码分离。

> [!IMPORTANT]
> **后端新增依赖**：需要在 Python 环境中添加 `fastapi` 和 `uvicorn`。会更新 `requirements.txt`。

> [!WARNING]
> **长时间任务**：pipeline 的某些阶段（ASR 转录、LLM 精修）可能需要几分钟甚至更久。计划使用**后台任务 + 轮询**模式：提交后返回 job_id，前端定期查询状态。如果你更偏好 WebSocket 实时推送，请告知。

### Review Feedback (Approved with suggestions)

计划非常清晰！架构设计很合理。为了提升开发效率和最终用户体验，建议做以下补充：

1. **引入 UI 组件库**：强烈建议引入 **Naive UI** 或 **Element Plus** 等成熟的 Vue 3 组件库，避免纯手写组件，快速实现现代简洁的深色主题界面。
2. **状态管理与路由**：确保在前端依赖中加入 `vue-router` 处理页面切换，并引入 `pinia` 存储全局状态（如 profiles/backends 配置和可能的全局任务进度），避免跨页面重复请求。
3. **长任务通信**：MVP 阶段使用简单的**轮询 (Polling)** 是完全可以接受的。后期如果需要更精细的实时日志推流，建议考虑使用 **SSE (Server-Sent Events)** 替代 WebSocket，因为这更符合后端向前端单向推流的场景，且 FastAPI 原生支持。
4. **FileBrowser 细节优化**：
   - 增加显示/隐藏隐藏文件的 Toggle 功能。
   - 选择目录模式下，禁用对文件的选择。
   - 利用 `localStorage` 记住用户上次浏览的路径，提升高频使用体验。

### Final Decision

基于最终评审，计划按以下口径落地：

1. **前端依赖**：首版采用 **Naive UI** 作为组件库，并加入 `vue-router`。**MVP 不引入 `pinia`**，避免为当前规模过早增加全局状态层。
2. **长任务通信**：首版继续采用 **后台任务 + 轮询**。但轮询必须建立在**持久化状态文件**之上，不能只依赖进程内内存。
3. **文件浏览器**：首版纳入“目录模式禁用文件选择”和“记住上次路径”；“显示隐藏文件 Toggle”保留为增强项，不作为首版阻塞要求。
4. **单阶段运行页**：保留，但必须明确这是对**当前配置路径**执行阶段任务，不是单文件级的临时运行器。

---

## Proposed Changes

### 后端 API 层 (Python)

#### [NEW] [api_server.py](file:///home/kuma/programes/transcript-pipeline/api_server.py)

FastAPI 应用入口，提供以下 REST API：

| 端点 | 方法 | 功能 |
|------|------|------|
| `GET /api/config` | GET | 返回当前 `settings.yaml` 中的 profiles 列表、backends 列表 |
| `GET /api/fs/list?path=...&type=file\|dir\|all` | GET | 浏览服务器文件系统，返回指定目录下的文件/文件夹列表 |
| `POST /api/jobs` | POST | 提交单任务（对应 `08_run_job.py` 的参数） |
| `POST /api/batch-jobs` | POST | 提交批量任务（对应 `09_run_batch_jobs.py` 的三种模式） |
| `GET /api/jobs/{job_id}` | GET | 查询任务状态与结果 |
| `GET /api/jobs` | GET | 列出所有已有 job（扫描 `data/jobs/`） |
| `GET /api/batches/{batch_id}` | GET | 查询批量任务整体状态与各子任务进度 |
| `POST /api/stages/{stage_name}` | POST | 提交单阶段运行任务（对应 `run_pipeline.py --stage`） |
| `GET /api/stage-runs/{run_id}` | GET | 查询单阶段运行任务状态与结果 |

核心设计：
- 任务提交后在后台线程执行，立即返回 `job_id`
- 通过 `/api/jobs/{job_id}` 轮询状态（pending → running → success/failed）
- API 层必须将状态持久化到 JSON 文件，而不是只保存在进程内存中：
  - 单任务：`data/jobs/<job_id>/state.json`
  - 批量任务：`data/jobs/batches/<batch_id>/state.json`
  - 单阶段运行：`data/jobs/stage-runs/<run_id>/state.json`
- 状态文件最少包含：`id`、`kind`、`status`、`created_at`、`updated_at`、`current_stage`、`error_message`、`output_path`
- API 层在提交、开始执行、阶段切换、完成、失败时都要更新状态文件
- `GET /api/jobs`、`GET /api/jobs/{job_id}`、`GET /api/batches/{batch_id}`、`GET /api/stage-runs/{run_id}` 均读取持久化状态，而不是推断目录内容或依赖内存对象
- 优先复用现有 `src/job_runner.py` 与 `scripts/run_pipeline.py` 中的已有函数；若当前一把梭入口不利于状态落盘，可在 API 层按阶段编排或对 `src/job_runner.py` 做最小补充
- 保持现有中间产物目录结构兼容，不回改既有 job 输出格式

文件系统浏览 API (`GET /api/fs/list`)：
- 参数 `path`：要浏览的目录绝对路径，默认值为用户 HOME 目录
- 参数 `type`：过滤类型 `file`（仅文件）、`dir`（仅文件夹）、`all`（全部），默认 `all`
- 参数 `show_hidden`：是否显示隐藏文件，默认 `false`
- 返回：`{ current_path, parent_path, items: [{ name, path, is_dir, size }] }`
- 安全限制：
  - 仅允许浏览白名单根目录内的内容，首版白名单为“用户 HOME 目录”和“项目根目录”
  - 对请求路径先 `resolve()`，若越出白名单根目录则拒绝
  - 默认隐藏以 `.` 开头的文件
  - 选择目录模式下，前端必须禁用对文件的最终确认
  - 不提供任何写入、删除、重命名能力

前端 `FileBrowser.vue` 组件：
- 可配置模式：选文件 / 选文件夹
- 点击按钮弹出弹窗，显示当前目录内容列表
- 双击文件夹进入，点击面包屑或「上一级」返回
- 使用 `localStorage` 记住最近一次成功选择的路径
- 选中后将绝对路径回填到表单字段

#### [MODIFY] [requirements.txt](file:///home/kuma/programes/transcript-pipeline/requirements.txt)

新增：
```diff
+fastapi>=0.115,<1
+uvicorn>=0.34,<1
```

---

### 前端 (Vue 3 + TypeScript)

#### [NEW] `frontend/` 目录

使用 `npm create vite@latest ./ -- --template vue-ts` 创建，核心文件：

```
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts          # 配置 API 代理到 localhost:8000
├── index.html
├── src/
│   ├── main.ts
│   ├── App.vue             # 主布局
│   ├── router/
│   │   └── index.ts        # vue-router 路由定义
│   ├── api/
│   │   └── client.ts       # HTTP 请求封装 (fetch)
│   ├── views/
│   │   ├── SingleJobView.vue    # 单任务提交页
│   │   ├── BatchJobView.vue     # 批量任务提交页
│   │   ├── StageRunnerView.vue  # 单阶段运行页
│   │   └── JobListView.vue      # 任务列表/状态查看页
│   ├── components/
│   │   ├── ProfileSelector.vue  # profile 下拉选择
│   │   ├── BackendSelector.vue  # backend 下拉选择
│   │   ├── FileBrowser.vue      # 文件/文件夹浏览选择器（弹窗式）
│   │   ├── JobStatusCard.vue    # 任务状态卡片
│   │   └── NavBar.vue           # 顶部导航
│   └── styles/
│       └── main.css             # 全局样式
```

前端首版依赖：
- `naive-ui`：表单、弹窗、表格、通知等基础组件
- `vue-router`：页面路由
- 不引入 `pinia`；首版只使用页面级状态和少量共享 composable/cache

#### 页面说明

**1. 单任务页 (SingleJobView)**
- 对应 `08_run_job.py`，最常用的入口
- 表单字段：视频文件、参考源文件/URL、输出目录、profile 选择、backend 选择、书名(可选)、章节(可选)、术语词表(可选)
- 视频文件、参考源、输出目录、术语词表等路径字段通过**点击按钮弹出文件/文件夹浏览器**选择，无需手动输入路径
- 参考源额外支持直接输入 URL
- 提交后显示 job 状态，自动轮询直到完成

**2. 批量任务页 (BatchJobView)**
- 对应 `09_run_batch_jobs.py`，支持三种输入模式切换：
  - **Manifest 模式**：通过文件浏览器选择 manifest YAML 文件
  - **目录配对模式**：通过文件浏览器分别选择视频目录 + 参考目录 + 输出目录
  - **共享参考模式**：通过文件浏览器选择视频目录 + 共享参考文件/URL + 输出目录
- 所有路径字段均通过点击弹出浏览器选择
- 公共参数：profile、backend、远程并发度、书名(可选)、章节(可选)、术语词表(可选)
- 提交后展示 batch 整体进度和各子任务状态卡片列表
- 自动轮询 `/api/batches/{batch_id}` 直到全部完成

**3. 单阶段运行页 (StageRunnerView)**
- 对应 `run_pipeline.py --stage`
- 下拉选择阶段名（extract-audio、transcribe、prepare-reference、refine、export-markdown、align、classify）
- 选择 profile 和 backend（仅 refine 阶段可选）
- 页面文案必须明确：该页面运行的是**当前配置路径**对应的数据目录，不是针对单个临时选择文件执行
- 提交后返回 `run_id` 并轮询 `/api/stage-runs/{run_id}` 显示状态和结果

**4. 任务列表页 (JobListView)**
- 展示 `data/jobs/` 下所有已有任务
- 每个任务显示：job_id、状态、创建时间、输出路径
- 可查看任务详情

#### 样式设计
- 使用 Naive UI 主题定制 + 少量自定义 CSS
- 风格优先“清晰、稳定、中文表单友好”，不把深色主题设为硬性要求
- 使用 CSS 变量系统实现少量主题色覆盖
- 中文友好的字体栈
- 响应式布局

---

## Verification Plan

### 自动化测试

**1. 后端 API 测试**

```bash
.venv/bin/python -m pytest tests/test_api_server.py -v
```

新增 `tests/test_api_server.py`，使用 FastAPI 的 `TestClient`：
- `test_get_config_returns_profiles_and_backends` — 验证 `/api/config` 返回正确的 profiles 列表
- `test_post_job_returns_job_id` — 验证 `/api/jobs` 提交后返回 job_id（mock `run_single_job`）
- `test_get_job_status_returns_current_state` — 验证 `/api/jobs/{id}` 返回状态
- `test_get_job_list_reads_persisted_state` — 验证 `/api/jobs` 基于状态文件列出任务
- `test_get_batch_status_reads_persisted_state` — 验证 `/api/batches/{id}` 基于状态文件返回批量进度
- `test_post_stage_run_returns_run_id` — 验证单阶段运行接口返回 `run_id`

**2. 前端构建验证**

```bash
cd frontend && npm run build
```

确认 Vue 前端可以成功构建，避免出现仅后端测试通过、前端无法编译的情况。

**3. 现有 Python 测试不受影响**

```bash
.venv/bin/python -m pytest
```

确认所有现有测试仍然通过（不修改 `src/` 模块）。

### 浏览器手动验证

启动后端和前端后，在浏览器中验证：

1. 启动后端：`.venv/bin/python api_server.py`
2. 启动前端：`cd frontend && npm run dev`
3. 打开 `http://localhost:5173`
4. 验证以下操作：
   - 导航栏正常显示四个页面入口
   - 单任务页表单正常渲染，profile/backend 下拉菜单有正确选项
   - 点击「选择文件」/「选择文件夹」按钮弹出文件浏览器，可导航目录并选择
   - 文件浏览器默认不显示隐藏文件；目录模式下不能确认选择文件；刷新页面后能记住最近一次路径
   - 批量任务页三种输入模式切换正常，表单字段随模式变化
   - 单任务、批量任务、单阶段运行提交后，状态页能看到 pending/running/success/failed 的真实流转
   - 单阶段运行页下拉菜单包含所有可用阶段
   - 单阶段运行页文案明确提示其作用于当前配置目录
   - 任务列表页可以正常加载（即使为空）
