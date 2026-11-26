# 最终许可证合规复核（2026-11-25）

仅检查独立发布副本。项目自有代码保留 MIT，Copyright (c) 2026 xyx-712；本轮未更改第三方原文。检查了 8 个实际安装版本的元数据、安装记录内 LICENSE/NOTICE、原生包声明，并记录逐文件 SHA-256。未把上游主分支作为当前发行版完整合规证明。

## 逐项结果

| 依赖 | 实装版本 | 随包声明文件数 | 结果与剩余义务 |
| --- | --- | --- | --- |
| grpcio | 1.85.3 | 1 | 待审核。Apache-2.0 顶层；随包综合声明含 MIT/BSD/Mozilla 等。需逐项核对 Windows 原生组件与 NOTICE 对应关系。 [版本页](https://pypi.org/project/grpcio/1.85.3/) |
| numpy | 2.4.6 | 19 | 待审核。复合 SPDX 包含 BSD-3-Clause、0BSD、MIT、Zlib、CC0-1.0；LICENSE 含 Libgfortran GPL 及 GCC Runtime Library Exception 3.1。不得仅因 GPL 字样认定项目须改为 GPL；需核对实际链接组件、例外适用和通知。 [版本页](https://pypi.org/project/numpy/2.4.6/) |
| onnxruntime | 1.32.0 | 2 | 待审核。主 LICENSE 为 MIT，另有大型 ThirdPartyNotices.txt；需核对当前 wheel 原生库实际包含的第三方组件及义务。 [版本页](https://pypi.org/project/onnxruntime/1.32.0/) |
| orjson | 3.13.0 | 3 | 待审核。MPL-2.0 AND (Apache-2.0 OR MIT)，三份许可随包存在；不能忽略 AND 的 MPL 部分，二进制再分发需核对对应源码与告知。 [版本页](https://pypi.org/project/orjson/3.13.0/) |
| pillow | 13.0.0 | 1 | 待审核。顶层 MIT-CMU，综合声明包含 FreeType 的许可选择及 xz 多种许可证文本。出现 GPL/LGPL 文本不证明整个 wheel 或本项目采用 GPL；仍需文件级和实际构建映射。 [版本页](https://pypi.org/project/pillow/13.0.0/) |
| sqlite-vec | 0.1.9 | 0 | 待审核。安装记录未发现 LICENSE/NOTICE。元数据列 MIT/Apache，不能据此确定当前原生扩展的完整义务；需精确发行归档和构建清单。 [版本页](https://pypi.org/project/sqlite-vec/0.1.9/) |
| tokenizers | 0.23.3 | 0 | 待审核。安装记录未发现 LICENSE/NOTICE；上游 Apache-2.0 不能替代当前版本 wheel 的 Rust 组件与版权映射。 [版本页](https://pypi.org/project/tokenizers/0.23.3/) |
| lightningcss-win32-x64-msvc | 1.33.0 | 1 | 待审核。包元数据 MPL-2.0，LICENSE 和 .node 原生扩展同时存在；需核对源代码获得方式、MPL 告知和原生依赖。npm 官方版本页面本轮返回403，未用主分支替代验证。 [版本页](https://www.npmjs.com/package/lightningcss-win32-x64-msvc/v/1.33.0) |

## 发布范围与判断

源码依赖：requirements.txt 与 package-lock.json 指定安装关系；这不等于把依赖源码或二进制重新许可为 MIT。运行时依赖：本地 .venv 中的原生 wheel 和 npm 中的 .node 仅用于运行/构建，不进入发布清单。实际分发：项目源码、测试、文档、配置模板，以及保留声明的 Vite 素材；不分发 wheel、DLL、模型或构建产物。

八项均保留 pending_review，未发现足以认定项目整体许可证不兼容的证据，也没有完成全部原生组件法律义务认证。其余 142 项沿用历史分层审查，其中 13 项为有条件确认、129 项仅初审；本轮不是全供应链漏洞或许可证复审。许可证文本哈希证明本轮观察内容，不证明发行供应链可信或跨平台 wheel 相同。

已确认的发布措施：MIT 边界清楚；原始 Vite 许可保留；无第三方二进制入包。待人工确认：逐项原生组件映射、许可选择、源码提供/通知义务，特别是 MPL 部分和缺失随包声明的两个 wheel。风险：未来打包 Docker 镜像、exe、node_modules、dist 或模型将改变分发范围，须重新审查，当前结论不可直接复用。

[MPL 官方 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)说明文件级义务及库/可执行文件分发告知要求；不能把 MPL 简化成无条件 MIT。NumPy 本地文本含 GCC 运行库例外；[GCC 官方例外页面](https://www.gnu.org/licenses/gcc-exception-3.1.html)本轮读取超时，结论仅据当前随包声明，不作额外法律推定。

## 素材与模型

五份 Vite 模板图片/图标保留原文件与 third-party-licenses/vite-LICENSE.txt。未新增截图，不用私人聊天截图冒充演示；未分发字体文件，系统字体名称仅为回退配置。商标不属于 MIT 授权。

EmbeddingGemma 单独适用 [Gemma 条款](https://gemma.ai/resources/terms/)和[禁止用途政策](https://gemma.ai/resources/prohibited-use/)，不是 MIT；无权重入包不等于使用模型无需遵守条款。日后分发权重、衍生模型或提供模型服务须另核适用条件。实际 Ollama 模型构建的完整组件授权不在本次八项审查范围。

## 结论

可准备源代码公开展示，但只能作有条件发布判断，不能标记“全部第三方依赖合规通过”。若发布要求零未决许可证事项，应先完成八项人工签核，再发布。安装后的依赖二进制和模型另受其条款约束。

证据详情见 third-party-license-inventory.json 的 final_compliance_review 字段。未复制或修改第三方原始文本，也未删除依赖。
