# 网站集成

以企业管理员登录，在“公开客服入口”创建并启用入口，复制界面提供的代码和链接。代码中的地址使用部署配置的 `WEB_ORIGIN`，ID 是实际公开入口 UUID；以下占位值必须替换。不要在网页中放管理账号、模型密钥或访客令牌。

## HTML

在页面 `</body>` 前加入一次：

```html
<script src="https://support.example.com/widget.js" data-agent="PUBLICATION_UUID" defer></script>
```

脚本会添加客服按钮和 iframe；公开页面也可直接访问 `https://support.example.com/chat/PUBLICATION_UUID`。配置 `PUBLIC_RATE_KEY` 后才能创建访客会话。

## Vue / React

单页应用应在客户端挂载后、整个应用生命周期内只加载一次。下例放在应用根组件；替换域名和 UUID，勿在每次路由切换时重复插入。

```js
// Vue: 在 onMounted(() => { ... }) 中执行
// React: 在根组件 useEffect(() => { ... }, []) 中执行
if (!document.getElementById("support-widget-script")) {
  const script = document.createElement("script");
  script.id = "support-widget-script";
  script.src = "https://support.example.com/widget.js";
  script.dataset.agent = "PUBLICATION_UUID";
  document.body.appendChild(script);
}
```

小组件自行创建 DOM，当前没有销毁 API；卸载组件时只删除 script 标签不会移除已经创建的按钮和 iframe。保留根组件和脚本直至页面卸载，避免重复加载；若需要按路由销毁，应先自行管理生成的节点生命周期并验证，不能假定移除 script 即完成清理。

## WordPress

由可信站点管理员在允许脚本的 Custom HTML 区块中加入上述 HTML。站点的内容过滤、主题或安全插件可能移除脚本；按站点权限审查，不要赋予不可信编辑者插入任意脚本的权限。

## 直接 iframe 和部署注意事项

```html
<iframe title="在线客服" src="https://support.example.com/chat/PUBLICATION_UUID"
  sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>
```

宿主页面 CSP 须允许客服服务域名的 `script-src` 和 `frame-src`；直接 iframe 只需相应 `frame-src`。生产环境使用 HTTPS，并正确配置 `WEB_ORIGIN`、代理及公开入口。跨站 iframe 的存储可能受浏览器隐私策略限制；不可用时提供独立公开链接。管理员页面不可嵌入。详见[部署与恢复](DEPLOYMENT.md)和[生产检查清单](PRODUCTION_CHECKLIST.md)。实际站点、浏览器和 WordPress 的兼容性尚未验收。
