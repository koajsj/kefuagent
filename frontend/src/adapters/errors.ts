const errors: Record<string, string> = {
  http_limit_exceeded: "请求或连接过于频繁，请稍后重试。",
  ingress_unavailable: "请求准入暂不可用，请稍后重试。",
  public_rate_key_unavailable:
    "部署管理员尚未配置 PUBLIC_RATE_KEY，暂不能创建访客会话。",
  invalid_provider_url:
    "模型地址必须为批准白名单中的 HTTPS 主机，不允许私网、IP、查询参数或用户信息。",
  visitor_authentication_required: "访客会话已过期或无效，请重新开始会话。",
  visitor_limit_exceeded: "访客访问达到限制，请稍后再试。",
  public_tool_denied: "此工具未获公开使用授权。",
  publication_revoked: "入口已撤销，请创建新入口。",
  visitor_access_revoked: "公开访问授权已失效，请联系管理员检查并重新发布。",
  demo_modified:
    "演示资源已被修改或删除，系统不会覆盖现有数据；请检查现有资源。",
  agent_disabled: "关联 Agent 已停用，请先启用再发布。",
  model_configuration_unavailable:
    "模型配置不可用：请启用 Agent，并填写兼容服务地址与凭证引用。",
  credential_ref_immutable: "凭证引用不可改名，请创建新的凭证引用。",
  provider_unavailable: "模型服务暂不可用，请检查服务配置并稍后重试。",
  provider_busy: "模型服务繁忙，请稍后重试。",
  conversation_closed: "会话已结束，请重新开始。",
  base_url_not_allowed:
    "模型地址未被部署方批准。请检查 HTTPS 地址和主机白名单。",
  authentication_required: "登录已过期，请重新登录。",
  invalid_credentials: "账号或密码错误，或账号暂时被锁定。",
  permission_denied: "当前账号没有此操作权限。",
  origin_denied: "当前浏览器地址与 WEB_ORIGIN 不一致，请按部署配置的地址访问。",
  external_models_disabled:
    "外部模型调用已关闭。可使用离线演示 Agent；真实调用须另行授权。",
  credential_key_unavailable: "服务器未配置有效的凭证主密钥。",
  credential_unavailable: "凭证不可用，请由管理员检查。",
  version_conflict: "配置已被更新，请重新打开后保存。",
  conversation_busy: "该会话仍在执行，请等待后使用原请求重试。",
  human_handling_active: "当前会话正在等待或由人工处理，AI 回复已暂停。",
  token_budget_exceeded: "保守 Token 预算不足，请检查用量限制。",
  summary_source_too_large:
    "一条完整历史消息超出摘要输入预算，原文和待处理边界均已保留。请由企业管理员提高 Agent 的 max_input_tokens 后重试；系统不会截断该消息后假装已处理。",
  memory_access_revoked:
    "会话、模型或凭证授权已变化，摘要和回复已停止交付，请刷新配置。",
  request_limit_exceeded: "请求过于频繁，请稍后重试。",
  concurrency_limit_exceeded: "并发调用已达上限，请等待已有调用结束。",
  insufficient_evidence: "资料不足，无法确认答案。",
  conflicting_evidence: "资料存在冲突，请联系人工核实。",
  interrupted_result_unknown:
    "执行中断，结果未知。请检查记录，不要盲目创建新请求。",
  resource_conflict: "资源已存在或关联冲突，请刷新列表。",
};
export function explain(code: string, fallback = "") {
  return errors[code] || fallback || code || "请求失败，请检查服务状态。";
}
