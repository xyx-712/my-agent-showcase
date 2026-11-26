# Protected Quick Tunnel 注册/登录诊断 · 2026-11-26

## 结论

公网认证故障未宣称修复。现有截图和上游同版本实现表明，失效发生在cloudflared前置授权层；具体是短期会话到期、Cookie未保存/未发送或二者叠加，本轮没有新鲜浏览器认证数据证明唯一原因。

本机cloudflared --version为2026.11.0（built 2026-11-12）。读取官方2026.11.0标签代码；没有验证本机二进制与该标签构建逐字节一致。现有进程未重启，未查看包含邮箱/令牌的完整命令行。Win32_Process只读查询被拒绝，未提升权限绕过。HKCU Edge policy查询未取得明确阻止值，不代表用户首选项允许Cookie。

## 可核对证据

1. 用户网络面板显示注册401纯文本Unauthorized；GET /auth/me 302到Cloudflare认证站，随后fetch跨站CORS报错。后端截图未见对应注册请求，但截图并非完整日志，不能将缺失单独当作证明。
2. 应用require_user的401经FastAPI返回JSON detail；前端原fetch已credentials:include，使用相对路径。不是缺失credentials，不应放宽应用CORS。
3. 官方handler.go在进入origin前校验会话：无有效会话时GET/HEAD发302，其他方法直接纯文本401。与现象吻合。
4. 官方session.go实际Cookie名为__Host-cloudflared-qt-auth-session，而非此前让用户查找的CF_Authorization/CF_AppSession。Path=/，无Domain，Secure/HttpOnly，SameSite=Lax。签名密钥进程级，重启失效；过期取identity_exp与now+4小时最小值。
5. 官方assertion.go严格验证断言过期、签名、audience、host和state。旧日志断言过期与此前电脑快约36秒相关；校时不代表后续会话寿命问题自动消失。
6. 截图的CF_AppSession/CF_Session属于认证代理相关Cookie；浏览器确有用户首选项阻止提示，但没有本轮凭证元数据，不能断言这是注册失败唯一原因。
7. 官方仓库Issue1752目前Open，报告短期身份过期导致GET302、POST401；有Windows cloudflared2026.11.0相近复现。它是相关外部报告，不是本机identity_exp已被测得的证明，也没有据此宣称已有验证修复版本。

## 官方来源

- https://github.com/cloudflare/cloudflared/blob/2026.11.0/quicktunnelauth/handler.go
- https://github.com/cloudflare/cloudflared/blob/2026.11.0/quicktunnelauth/session.go
- https://github.com/cloudflare/cloudflared/blob/2026.11.0/quicktunnelauth/assertion.go
- https://github.com/cloudflare/cloudflared/issues/1752

## 已实施的独立前端修复

App.jsx仅将request抽为request.js；保留credentials、请求参数及服务端JSON错误status行为。非JSON拒绝响应给出访问层诊断，使用gatewayStatus而非应用status401，避免误清应用身份。网络/CORS错误明确不代表密码错误；保留AbortError。不回显任意代理正文，不保存认证凭据，不自动重试POST、不自动跳转或放宽安全规则。返回非JSON的其他代理也会使用通用访问层提示，不伪装成已确定Cloudflare。

测试：node --test tests/frontend_request.test.mjs 8/8；生产build通过（21模块，189ms）。npm lint默认扫描因上级release-candidates忽略规则未发现文件，不能算通过；另外使用oxlint --no-ignore显式检查3个修改文件，结果见本轮命令输出。没有运行无关后端完整套件。

## 未完成与授权边界

未重新完成真实邮箱OTP→注册→登录→聊天→刷新。未访问运行数据库、未创建测试账号、未读取Cookie值、未重启隧道、未改隧道参数/浏览器隐私/Origin/Secure或数据库。没有启动测试服务需要清理。

前端构建更新frontend/dist，静态资源由在运行的FastAPI提供，但没有强制刷新用户页面；新提示不等于外层认证修复。

最小下一步建议：只采集实际__Host-cloudflared-qt-auth-session是否存在、Path/SameSite/Secure与剩余有效秒数（不采集值），以及一次新OTP后0秒/10秒/60秒GET状态；不发密码POST。若确认仅数秒寿命，应走上游修复或命名Tunnel+Access方案。任何升级cloudflared、调整Cookie设置或更换隧道方案须作者先确认；不延长/伪造上游令牌、不关闭邮箱保护。已有截图凭据不再写入报告。
