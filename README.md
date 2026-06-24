# Diet Delushan 初始化项目

## 项目说明

本项目当前已调整为免登录直接进入主页的 Multi-Agent AI 数字营养健康决策系统：

- 后端目录：`backend`
- 前端目录：`frontend`
- 后端框架：FastAPI
- 前端框架：Vue 3（JavaScript）
- 已集成：Vue Router 4、SCSS、axios、ESLint、Pinia
- 已实现：多 Agent 健康助手主页、左侧对话历史、右侧对话界面、体检报告上传、统一状态展示
- 数据库：MySQL
- 请求方式：统一使用 axios 封装，不使用 fetch

## 目录结构

```text
backend/   FastAPI 后端
frontend/  Vue 前端
sql/       MySQL 初始化脚本
```

## 一、创建数据库

先执行 SQL 脚本：`sql/init.sql`

```sql
SOURCE H:/pythonidea/xiangmu/work/diet-delushan/sql/init.sql;
```

如果你使用的是图形化工具，也可以直接导入该文件。

## 二、启动后端

1. 进入 `backend`
2. 创建虚拟环境并安装依赖
3. 复制 `.env.example` 为 `.env`
4. 根据你的 MySQL 账号密码修改 `.env`
5. 如需接入真正的大模型，再补充 DashScope 配置
6. 启动服务

```powershell
Set-Location "H:\pythonidea\xiangmu\work\diet-delushan\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

如果你要启用阿里云 DashScope 的 OpenAI 兼容模型，请在 `backend/.env` 中配置：

```dotenv
DASHSCOPE_API_KEY=replace_with_dashscope_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.6-plus
LLM_TEMPERATURE=0.4
LLM_MAX_TOKENS=1200
LLM_TIMEOUT_SECONDS=60
```

后端内部已经按如下方式封装：

```python
import os

from openai import OpenAI

client = OpenAI(
	api_key=os.getenv("DASHSCOPE_API_KEY"),
	base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
```

当没有配置 `DASHSCOPE_API_KEY` 或模型调用失败时，系统会自动回退到本地规则型回复，不会中断聊天流程。

后端默认地址：`http://127.0.0.1:8000`

接口文档：`http://127.0.0.1:8000/docs`

## 三、启动前端

```powershell
Set-Location "H:\pythonidea\xiangmu\work\diet-delushan\frontend"
npm install
npm run dev
```

前端默认地址：`http://127.0.0.1:5174`

说明：前端和后端现在是完全分离启动。

- 前端只负责页面展示，访问 `http://127.0.0.1:5174`
- 后端只负责 API，访问 `http://127.0.0.1:8000`
- 后端不再托管前端页面

## 四、当前主页功能

- `/` 免登录直达 AI 饮食助手主页
- 左侧展示对话历史
- 右侧展示消息区、建议提示词、输入框
- 支持在问题输入框旁通过文件图标上传图片或 PDF
- 上传 PDF 时系统会自动按体检报告处理
- 上传图片时系统会按普通图片输入处理，不会当作体检报告
- 上传的体检报告 PDF 会持久化到 `backend/app/bodyreport/core_medical_report.pdf`
- 如果再次上传新的体检报告 PDF，系统会自动覆盖旧的核心体检报告文件
- 系统重启时会自动检查 `backend/app/bodyreport` 目录，若存在核心体检报告则直接加载，无需重新上传
- 支持展示 Guard、风险、画像、营养、食谱、推荐等多 Agent 状态

## 五、聊天接口

- `GET /api/chat/sessions` 获取会话列表
- `POST /api/chat/sessions` 创建新会话
- `GET /api/chat/sessions/{session_id}` 获取会话详情
- `POST /api/chat/sessions/{session_id}/messages` 发送消息并获取 AI 回复
- `POST /api/chat/sessions/{session_id}/messages/upload` 发送带文件的消息，由后端判断图片或 PDF
- `POST /api/chat/sessions/{session_id}/medical-report` 上传体检报告并初始化多 Agent 工作流

## 六、认证接口（暂时保留但当前主流程不使用）

- `POST /api/auth/register` 用户注册
- `POST /api/auth/login` 用户登录
- `GET /api/auth/me` 获取当前登录用户信息

## 七、默认说明

- 当前访问首页无需登录
- 当前系统已具备 Master Agent、Guard Agent、Report Parser Agent、User Profile Agent、Health Risk Agent、Nutrition Analysis Agent、Recipe Generation Agent、Recommendation Agent、Meal Record Agent 的可运行骨架
- Guard Agent 会在未上传体检报告时阻止进入画像、风险、食谱、推荐等关键流程
- 前端请求统一在 `frontend/src/utils/request.js` 中封装
- 如果后端地址变化，请修改 `frontend/.env.development`
- 如果你修改了前端端口，请同步更新 `backend/.env` 里的 `CORS_ORIGINS`
- 如果前端能打开但聊天接口报 404，请先确认后端是否已启动在 `frontend/.env.development` 对应端口



