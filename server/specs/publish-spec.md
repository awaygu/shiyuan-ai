# 一键发布 Spec

> 版本：1.0  
> 日期：2026-06-03  
> 状态：待实施

## 一、背景与约束

| 约束 | 说明 |
|------|------|
| 个人自媒体账号 | 无企业认证 |
| 微信公众号 | 已认证服务号，具备草稿箱 API 权限 |
| 小红书 / 抖音 | 无官方发布 API，只能浏览器自动化 |
| 运行环境 | 本地 Windows 桌面，可弹浏览器窗口扫码 |
| 流程统一 | 知识库生成文章 + 新闻生成文章 共用同一发布入口和接口 |

## 二、方案概览

| 平台 | 发布方式 | 登录方式 | 目标 |
|------|---------|---------|------|
| 微信公众号 | 官方 API（草稿箱） | appID + appSecret → access_token | 保存到草稿箱 |
| 小红书 | Playwright 浏览器自动化 | 扫码登录，cookies 持久化 | 直接发布 |
| 抖音 | Playwright 浏览器自动化 | 扫码登录，cookies 持久化 | 直接发布 |

## 三、后端改动

### 3.1 新增依赖

```
playwright==1.49.0
```

安装后需执行 `playwright install chromium`。

更新 `requirements.txt` 添加 `playwright>=1.49.0`。

### 3.2 新增配置项 (`config.py`)

```python
# 微信公众号
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")

# 浏览器自动化
COOKIES_DIR = os.getenv("COOKIES_DIR", str(Path(__file__).parent / "cookies"))
PUBLISH_HEADLESS = os.getenv("PUBLISH_HEADLESS", "true").lower() == "true"
PUBLISH_TIMEOUT = int(os.getenv("PUBLISH_TIMEOUT", "120"))
```

### 3.3 微信公众号 Publisher — 官方 API 实现

**文件：** `publishers/wechat_mp.py`

**流程：**

1. appID + appSecret → 请求 access_token（缓存2小时，过期自动刷新）
2. 上传正文中的图片到微信素材库（`/cgi-bin/media/uploadimg`）获取微信图片 URL
3. 调用 `POST /cgi-bin/draft/add` 保存草稿
4. 返回 `media_id`

**草稿接口请求格式：**

```json
{
  "articles": [{
    "title": "文章标题",
    "content": "<p>HTML正文</p>",
    "thumb_media_id": "封面图素材ID（可选）",
    "digest": "摘要（可选）"
  }]
}
```

**关键实现点：**

- access_token 缓存到内存，过期前 5 分钟自动刷新
- Markdown 正文需转为微信兼容 HTML（`<p>`, `<strong>`, `<h2>` 等基础标签）
- 正文中的外链图片需先上传到微信素材库替换为微信图片 URL
- HTTP 请求使用 `httpx`（已有依赖）
- API 基础 URL：`https://api.weixin.qq.com`

**access_token 管理器：**

```python
class WechatTokenManager:
    _token: str = ""
    _expires_at: float = 0

    async def get_token(self) -> str
    async def refresh_token(self) -> str
    async def upload_image(self, image_url: str) -> str
```

**Publisher 实现：**

```python
class WechatMpPublisher(BasePublisher):
    async def publish(self, title: str, content: str) -> PublishResult:
        # 1. 获取 access_token
        # 2. 转换 Markdown → HTML
        # 3. 上传正文图片
        # 4. 调用草稿箱新增接口
        # 5. 返回 PublishResult(success=True, url=草稿编辑页URL)
```

### 3.4 小红书 Publisher — Playwright 实现

**文件：** `publishers/xiaohongshu.py`

**自动化步骤：**

1. 加载 cookies（`cookies/xiaohongshu.json`）→ 检查是否有效
2. 无效 → 打开 `https://creator.xiaohongshu.com` 登录页（headless=False）→ 等待用户扫码
3. 有效 → 打开发布页 `https://creator.xiaohongshu.com/publish/publish`
4. 填入标题 → 填入正文 → 点击发布
5. 等待发布成功提示 → 返回结果
6. 保存 cookies

**关键选择器（需首次运行时验证并适配）：**

| 元素 | 选择器 |
|------|--------|
| 标题输入 | `input[placeholder='填写标题']` 或 `.c-input_inner` |
| 正文编辑 | `.ql-editor` (Quill 富文本编辑器) |
| 发布按钮 | `button:has-text('发布')` |

**注意事项：**

- 操作间添加随机延迟 2-5 秒，模拟人类节奏
- 正文填入使用 `page.evaluate()` 直接操作编辑器 DOM
- 发布后检测是否出现成功提示或文章链接

### 3.5 抖音 Publisher — Playwright 实现

**文件：** `publishers/douyin_pub.py`

**自动化步骤：**

1. 加载 cookies（`cookies/douyin.json`）→ 检查是否有效
2. 无效 → 打开 `https://creator.douyin.com` 登录页 → 等待用户扫码
3. 有效 → 打开 `https://creator.douyin.com/creator-micro/content/upload`
4. 填入标题 → 填入正文/视频描述 → 点击发布
5. 保存 cookies

**注意：** 抖音更偏视频发布，文字内容填入"视频描述"字段，作为图文/口播文案的入口。

### 3.6 Cookies 管理基类

**文件：** `publishers/base.py` 扩展

```python
class BrowserPublisher(BasePublisher):
    """Playwright 浏览器自动化发布基类"""
    cookies_path: Path  # cookies/{platform}.json
    login_url: str
    publish_url: str

    async def load_cookies(self) -> dict | None
    async def save_cookies(self, storage_state: dict) -> None
    async def check_login(self, page) -> bool   # 访问首页判断登录态
    async def wait_for_login(self, page) -> None # 等待扫码，轮询检测
    async def publish(self, title: str, content: str) -> PublishResult
```

**Cookies 存储格式：** Playwright `storage_state` JSON，包含 `cookies` 和 `origins`（localStorage）。

**Cookies 目录：** `server/cookies/`，gitignore 排除。

### 3.7 统一发布 API

**文件：** `api/publish.py` 改造

**请求模型：**

```python
class PublishRequest(BaseModel):
    article_id: str | None = None   # 新闻文章 ID（从内存 store 获取）
    title: str | None = None        # 直接传入标题
    content: str | None = None      # 直接传入内容（Markdown）
    platform: str                   # xiaohongshu | wechat_mp | douyin
```

**获取内容逻辑：**

```
if article_id:
    article = find_article(article_id)
    title = article["title"]
    content = article["content"]
else:
    title = req.title
    content = req.content
```

**响应格式：**

```json
{
  "success": true,
  "platform": "wechat_mp",
  "article_title": "文章标题",
  "url": "https://mp.weixin.qq.com/...",
  "need_login": false,
  "error_message": ""
}
```

当 cookies 过期或 access_token 无效时：

```json
{
  "success": false,
  "need_login": true,
  "error_message": "登录态已过期，请重新扫码登录"
}
```

**新增接口：**

```
POST /api/publish/{platform}/login   # 触发扫码登录流程
GET  /api/publish/{platform}/status  # 检查登录状态
```

**登录流程 API：**

```python
@router.post("/publish/{platform}/login")
async def login_platform(platform: str):
    publisher = PUBLISHERS.get(platform)
    if not publisher:
        raise HTTPException(400, "Unknown platform")
    if not isinstance(publisher, BrowserPublisher):
        raise HTTPException(400, "This platform uses API, no login needed")
    # 启动浏览器，打开登录页（headless=False）
    # 等待用户扫码登录
    # 保存 cookies
    return {"success": True, "platform": platform}

@router.get("/publish/{platform}/status")
async def login_status(platform: str):
    # 微信：检查 access_token 是否有效
    # 浏览器平台：检查 cookies 文件是否存在且未过期
    return {"logged_in": bool, "platform": platform}
```

**并发控制：** 同一平台同一时间只允许一个发布任务（`asyncio.Lock` per platform）。

### 3.8 .env 新增项

```env
# 微信公众号（认证服务号）
WECHAT_APP_ID=your_app_id
WECHAT_APP_SECRET=your_app_secret

# 浏览器自动化
PUBLISH_HEADLESS=true
PUBLISH_TIMEOUT=120
```

## 四、前端改动

### 4.1 知识库文章发布入口

**文件：** `web/src/components/KBChatPanel.vue`

在 article 类型消息的 `msg-actions` 区域新增"发布到"下拉按钮：

```html
<div class="msg-actions">
  <button class="msg-action-btn" @click="copyContent(msg.content)">复制</button>
  <el-dropdown @command="(p) => onPublish(msg.content, p)">
    <button class="msg-action-btn">发布到 ▾</button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="xiaohongshu">小红书</el-dropdown-item>
        <el-dropdown-item command="wechat_mp">微信公众号</el-dropdown-item>
        <el-dropdown-item command="douyin">抖音</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</div>
```

**发布逻辑：**

```typescript
async function onPublish(content: string, platform: string) {
  // 从消息中提取标题（首行或前30字）
  const title = content.split('\n')[0].slice(0, 30)
  publishingIds.value.push(...)
  try {
    const res = await publishByContent(title, content, platform)
    if (res.need_login) {
      // 弹登录确认窗
      await ElMessageBox.confirm(
        `${platformLabels[platform]}需要重新登录，请在弹出的浏览器窗口中扫码。`,
        '需要登录',
        { confirmButtonText: '开始登录', cancelButtonText: '取消' }
      )
      await loginPlatform(platform)
      // 登录成功后重新发布
      const res2 = await publishByContent(title, content, platform)
      ...
    }
  } finally { ... }
}
```

### 4.2 新增 API 函数

**文件：** `web/src/api/index.ts`

```typescript
/** Publish by content (for KB articles). */
export async function publishByContent(
  title: string, content: string, platform: string
): Promise<PublishRecord & { need_login?: boolean }> {
  const res = await api.post('/publish', { title, content, platform }, { timeout: 120000 })
  return res.data
}

/** Trigger login for browser-based platform. */
export async function loginPlatform(platform: string): Promise<{ success: boolean }> {
  const res = await api.post(`/publish/${encodeURIComponent(platform)}/login`, {}, { timeout: 120000 })
  return res.data
}

/** Check login status. */
export async function getLoginStatus(platform: string): Promise<{ logged_in: boolean }> {
  const res = await api.get(`/publish/${encodeURIComponent(platform)}/status`)
  return res.data
}
```

### 4.3 发布进度反馈

- 点击发布 → 按钮 loading "发布中..."
- 微信 API 发布约 5-10 秒
- 浏览器自动化发布约 30-60 秒
- 发布完成后 ElMessage 提示成功/失败
- 成功后可点击查看发布链接

### 4.4 新闻文章发布统一

现有 `PublishPanel.vue` 的发布逻辑改为调用统一 `publishByContent` 接口（传入 article_id），保持 UI 不变。

## 五、安全与风险

| 风险 | 应对策略 |
|------|---------|
| 平台检测自动化 | 操作间随机延迟 2-5 秒，模拟人类节奏 |
| Cookies 过期 | 检测失效 → 返回 need_login → 提示重新扫码 |
| 平台改版 | 选择器使用稳定属性，失败时捕获异常并提示 |
| 并发发布冲突 | 同平台加 asyncio.Lock，一次只允许一个发布 |
| access_token 泄露 | .env 不入库，gitignore 排除 |
| Cookies 文件安全 | cookies/ 目录 gitignore 排除 |

## 六、目录结构变更

```
server/
├── cookies/                    # 新增，gitignore
│   ├── xiaohongshu.json
│   └── douyin.json
├── publishers/
│   ├── base.py                 # 扩展 BrowserPublisher 基类
│   ├── wechat_mp.py            # 重写：官方 API 实现
│   ├── xiaohongshu.py          # 重写：Playwright 实现
│   └── douyin_pub.py           # 重写：Playwright 实现
├── api/
│   └── publish.py              # 改造：统一来源 + 登录接口
├── config.py                   # 新增配置项
├── requirements.txt            # 新增 playwright
└── specs/
    └── publish-spec.md         # 本文档

web/src/
├── api/index.ts                # 新增发布 API
├── components/
│   ├── KBChatPanel.vue         # 新增发布按钮 + 登录交互
│   └── PublishPanel.vue        # 改造：统一发布接口
```

## 七、实施步骤

| # | 任务 | 预计工时 | 依赖 |
|---|------|---------|------|
| 1 | 安装 Playwright + chromium | 5min | - |
| 2 | 新增 config.py 配置项 + .env.example | 10min | - |
| 3 | 实现 WechatMpPublisher（API 草稿箱） | 1h | - |
| 4 | 实现 BrowserPublisher 基类（cookies 管理） | 1h | 1 |
| 5 | 实现 XiaohongshuPublisher（Playwright） | 1.5h | 4 |
| 6 | 实现 DouyinPublisher（Playwright） | 1.5h | 4 |
| 7 | 改造 publish.py（统一来源 + 登录接口） | 30min | 3,5,6 |
| 8 | 前端：KBChatPanel 发布按钮 | 30min | 7 |
| 9 | 前端：登录弹窗交互 | 30min | 8 |
| 10 | 前端：PublishPanel 统一接口 | 15min | 7 |
| 11 | 端到端测试 | 1h | 全部 |
