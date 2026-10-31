# 网站集成

以企业管理员登录，在“公开客服入口”创建并启用入口，复制界面提供的代码和链接。代码中的地址使用部署配置的 `WEB_ORIGIN`，ID 是实际公开入口 UUID；以下占位值必须替换。不要在网页中放管理账号、模型密钥或访客令牌。

## HTML

在页面 `</body>` 前加入一次：

```html
<script src="https://support.example.com/widget.js" data-agent="PUBLICATION_UUID" defer></script>
```

脚本会添加客服按钮和 iframe；公开页面也可直接访问 `https://support.example.com/chat/PUBLICATION_UUID`。配置 `PUBLIC_RATE_KEY` 后才能创建访客会话。

## Vue / React

在应用的 HTML 入口（Vue 的 `index.html` 或 React 的宿主 HTML）中加入上面的脚本一次，由整个页面共享，无需在路由组件中重复插入。同一客服服务 origin 和公开入口 UUID 的重复脚本加载会复用已有实例；不同 origin 或 UUID 会分别创建实例。UUID 应使用公开入口提供的小写标准格式。

需要销毁时，在应用卸载或自行管理的生命周期中移除对应宿主节点；仅移除 `<script>` 不会销毁小组件。以下代码可在 Vue 的 `onUnmounted` 或 React 的实际应用卸载逻辑中调用。之后若需重新显示，需重新插入并加载脚本。

```js
const origin = "https://support.example.com";
const publicationId = "PUBLICATION_UUID";
document.querySelectorAll("[data-support-widget-origin][data-support-widget-agent]")
  .forEach((host) => {
    if (host.dataset.supportWidgetOrigin === origin && host.dataset.supportWidgetAgent === publicationId) {
      host.remove();
    }
  });
```

这些属性只用于定位实例，不包含管理凭据。不要在 React 开发模式的效果函数清理中直接使用此全局销毁方式：严格模式可能重新执行效果，而静态脚本不会随之重新加载。

## WordPress

由可信站点管理员在允许脚本的 Custom HTML 区块中加入上述 HTML。站点的内容过滤、主题或安全插件可能移除脚本；按站点权限审查，不要赋予不可信编辑者插入任意脚本的权限。

## 直接 iframe 和部署注意事项

```html
<iframe title="在线客服" src="https://support.example.com/chat/PUBLICATION_UUID"
  sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>
```

宿主页面 CSP 须允许客服服务域名的 `script-src` 和 `frame-src`。小组件通过 JavaScript 的 `element.style` 属性直接设置样式；这与 HTML 内联 `style` 属性或 `setAttribute("style", ...)` 的 CSP 处理不同。请在站点实际 CSP 和目标浏览器下验证布局，不要仅为此假定必须放宽 `style-src-attr`。直接 iframe 不需要加载 widget 脚本或其内联样式，但仍须允许相应 `frame-src`。生产环境使用 HTTPS，并正确配置 `WEB_ORIGIN`、代理及公开入口。跨站 iframe 的存储可能受浏览器隐私策略限制；不可用时提供独立公开链接。管理员页面不可嵌入。详见[部署与恢复](DEPLOYMENT.md)和[生产检查清单](PRODUCTION_CHECKLIST.md)。实际站点、浏览器和 WordPress 的兼容性尚未验收。

## 手动验收（NOT_RUN）

- 在实际站点加载脚本，确认按钮可打开和关闭客服 iframe。
- 在文档 body 创建前以及重复加载同一脚本时，确认只出现一个实例；移除宿主后重新加载，确认可以重新出现。
- 检查站点 CSP、Vue 或 React 的卸载流程及 WordPress 内容过滤；验证受支持浏览器中的公开会话和独立链接。
