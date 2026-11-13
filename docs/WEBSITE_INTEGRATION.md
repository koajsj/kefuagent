# 可信网站 Widget 接入

专项 A 当前协议（2026-11-09）。旧的仅 `data-agent` 脚本、独立 `/chat/UUID` 和无凭证 `POST /sessions` 已停止接待正式访客。客户登录身份与网站来源身份分离：本协议不接受 `tenant_id` / `customer_id`，不会自动关联客户档案。

## 配置与域名验证

1. 部署者配置 HTTPS `WEB_ORIGIN`、固定且每个部署独立的 `WIDGET_INSTANCE_ID`（UUID）、受保护的 `PUBLIC_RATE_KEY`、凭证加密 Keyring。生产环境同时启用 PostgreSQL 入口限流和边缘防护。
2. 管理员创建并发布 Agent 入口，在「可信网站」登记该发布 ID 和精确 HTTPS origin；不支持通配符、IP、路径或自定义端口。
3. 登记返回一次性的 `server_secret`、公开 `challenge` 和 `verification_url`。密钥仅放入**网站后端**的密钥配置，不能写入 HTML、浏览器环境变量或日志。
4. 在 `https://网站/.well-known/kefuagent-site-verification` 返回 challenge 纯文本（可有首尾空白）；24 小时内点击验证。平台仅访问此固定 HTTPS 路径，拒绝重定向及任意私网 DNS 答案，使用验证 TLS 的隔离进程，整个子进程最多 10 秒。
5. 验证有效期 30 天，随后显式启用网站。**启用之后**获取 `/api/v1/security/widget-sites/{site_id}/integration` 的真实版本绑定配置；这是管理员接口，不供浏览器或网站后端匿名查询。

重新验证/轮换会停用网站、更换后端密钥和 challenge，并递增版本。启停、重新验证、轮换、重新发布、Agent/发布者撤权均会使旧授权失效。完成变更后重新获取签名配置；不要继续使用登记回执中的旧版本。轮换平台 `PUBLIC_RATE_KEY` 或 `WIDGET_INSTANCE_ID` 也会撤销旧凭证；所有实例应使用相同配置。

## 网站后端签发契约

网站需要实现自己的同源 POST 签发接口。它必须先执行本站可信登录/访客会话、CSRF 和限流策略，按服务器保存的配置选择站点，不能信任请求体自行指定的企业、客户、站点或发布版本。这个端点若对任意自动化客户端开放，攻击者也能获得合法断言；签名证明网站后端签发，不能凭空证明浏览器、真人或客户登录身份。

签名字节是以下 **9 个字段**组成的 JSON 对象：`aud`、`instance_id`、`publication_id`、`publication_version`、`site_id`、`site_version`、`origin`、`nonce`、`expires_at`。前 7 项来自管理接口保存的配置；UUID 使用标准小写字符串，版本为整数。`nonce` 每次使用新的 UUID，`expires_at` 为整数 UTC Unix 秒，平台接收时必须大于当前时间且不超过 60 秒。建议签发 45 秒并同步服务器时钟。

规范化规则：键按字典顺序排列、分隔符为 `,` / `:`（无空白）、字符串采用 JSON ASCII 转义，再编码 UTF-8。HMAC-SHA256 的 key 为 `server_secret` 字符串的 UTF-8 字节，**不做 Base64 解码**；结果为小写十六进制。`algorithm`、`max_assertion_seconds` 和 `signing_secret_exposed` 仅是说明，不能加入签名对象。

网站后端可使用以下标准库函数（不是可匿名开放的完整 HTTP 接口；调用前的本站授权由网站实现）：

```python
import hashlib
import hmac
import json
import time
import uuid


def issue_widget_assertion(config, server_secret):
    payload = {
        key: config[key]
        for key in (
            "aud",
            "instance_id",
            "publication_id",
            "publication_version",
            "site_id",
            "site_version",
            "origin",
        )
    }
    payload["nonce"] = str(uuid.uuid4())
    payload["expires_at"] = int(time.time()) + 45
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    signature = hmac.new(server_secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return {
        "site_id": payload["site_id"],
        "nonce": payload["nonce"],
        "expires_at": payload["expires_at"],
        "signature": signature,
    }
```

签发接口返回以上四字段 JSON，设置 `Cache-Control: no-store`。不能记录断言、签名密钥、Bootstrap 或 Visitor 凭证；不得把私有配置接口的管理凭据转交浏览器。网站后端代码/域名部署及真实时钟未在本轮执行验证。

## 嵌入与凭证链

在已登记的网站中加载一次，替换真实公开 ID、站点 ID 和**已经实现**的同源签发接口路径：

```html
<script src="https://support.example.com/widget.js"
  data-agent="PUBLICATION_UUID" data-site="SITE_UUID"
  data-bootstrap-url="/api/support/bootstrap" defer></script>
```

HTML / React / Vue / WordPress 均在受信任的页面入口加载；不要在每次路由切换重复注入。宿主 CSP 精确允许客服服务的 `script-src` / `frame-src`。平台 iframe 的 `frame-ancestors` 仅为该站点 origin；不提供通配 CORS，访客 API 在平台 iframe 同源调用。独立打开、后台无签名预览、直接无签名 iframe 均不能创建正式会话。

iframe 与宿主用 `postMessage` 握手：平台只接受父窗口、请求 ID 和指定站点；宿主只接受本 iframe 和平台 origin。宿主向自己的签发接口 POST，返回断言后以精确平台 origin 发送；iframe 再交换 `/public/{pid}/bootstrap`，核对签名绑定的网站 origin 与实际消息 origin。给父窗口的启动请求使用 `*`，只包含公开 ID 和随机请求 ID，不含断言或凭证。

平台同时验证网站、发布、部署实例、签名和时效，持久化唯一 nonce，再签发短期、签名且数据库绑定的 Bootstrap。`POST /public/{pid}/sessions` 接收 `{"bootstrap_token":"…"}`，在同一事务内消费一次，创建 1 小时签名 Visitor bearer。重放 nonce 或 Bootstrap 均失败；响应丢失时由网站后端发放新断言，不重新使用旧值。会话请求继续使用 `Authorization: Visitor …`，每次复查签名、网站/发布版本、有效期、撤权和会话归属。SSE/文件 I/O 后也重新验证；凭证不放在 URL、Referrer 或 DOM 属性。

浏览器会话和草稿按发布+站点隔离；不可用的浏览器存储仅使用当前页面内状态。iframe sandbox 仅开放 scripts/same-origin/forms/downloads，附件强制下载不内联执行。匿名准入仍受原有限流、会话次数和模型预算限制；网站签名不替代边缘防滥用。

## 验收边界

FIXED：平台源码、管理 API、版本撤销、签名/单次消费与加载协议。NEEDS_RUNTIME_VERIFICATION：真实域名 HTTPS/DNS/TLS、网站后端授权、CSP/跨站存储、并发重放、撤权、附件下载和 SSE；本轮均 NOT_RUN。

静态 Demo 使用独立 `widget-demo.js` 构建资产，仅承载标明虚构的离线会话；不支持或模拟可信网站、审批和金额授权。正式构建使用受信 loader，两者不互换。参见[部署](DEPLOYMENT.md)与[实施矩阵](PRODUCTIZATION.md)。
