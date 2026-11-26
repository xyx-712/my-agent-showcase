# 许可证逐项复核（2026-11-24）

项目 MIT 与第三方条款分开。LICENSE 已按作者指示填写 Copyright (c) 2026 xyx-712。本轮只复核上次 18 个待确认和 3 个未知项；其余 129 项保持初审，不宣称全部深度通过。

## 范围和证据

已逐项读取当前安装版本元数据、可用的随包 LICENSE/NOTICE，并查找官方来源。证据路径及 SHA-256 保存在 third-party-license-inventory.json。官方 main/master 页面仅证明上游条款，不等于已核验相同版本标签；版本由实际安装工件确认。没有改写任何第三方许可证。

“已确认兼容（有条件）”仅指当前不修改、不捆绑依赖的源码集成方式；依赖继续适用自身许可，未来发布二进制/容器须重新核对通知及源码提供义务。已确认不兼容项为 0，不代表零风险。

## 21 项结论

| 依赖 | 安装版本 | 分类 | 说明 | 来源 |
| --- | --- | --- | --- | --- |
| aiohttp | 3.14.5 | 已确认兼容（有条件） | Apache-2.0 + vendor llhttp MIT; preserve both notices. | [官方](https://github.com/aio-libs/aiohttp/blob/master/LICENSE.txt) |
| certifi | 2026.11.20 | 已确认兼容（有条件） | MPL-2.0; preserve CA bundle/file-level notices; do not relabel MIT. | [官方](https://github.com/certifi/python-certifi/blob/master/LICENSE) |
| chromadb | 1.5.9 | 已确认兼容（有条件） | Apache-2.0 confirmed from bundled text and official LICENSE. | [官方](https://github.com/chroma-core/chroma/blob/main/LICENSE) |
| colorama | 0.4.6 | 已确认兼容（有条件） | BSD-3-Clause confirmed from bundled and official text. | [官方](https://github.com/tartley/colorama/blob/master/LICENSE.txt) |
| grpcio | 1.85.3 | 需要人工确认 | Bundled LICENSE contains Apache, BSD and MPL components; native component attribution not fully mapped. | [官方](https://github.com/grpc/grpc/blob/master/LICENSE) |
| mmh3 | 5.3.1 | 已确认兼容（有条件） | MIT confirmed from full bundled text. | [官方](https://github.com/hajimes/mmh3/blob/master/LICENSE) |
| numpy | 2.4.6 | 需要人工确认 | BSD plus bundled native components, multiple licenses; binary redistribution requires full notice review. | [官方](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| onnxruntime | 1.32.0 | 需要人工确认 | Bundled MIT LICENSE and ThirdPartyNotices present; upstream guessed license URLs failed; native notices need manual mapping. | [官方](https://onnxruntime.ai) |
| orjson | 3.13.0 | 需要人工确认 | MPL-2.0 AND (Apache-2.0 OR MIT); mapping covered components requires manual confirmation. | [官方](https://github.com/ijl/orjson) |
| ormsgpack | 1.13.1 | 已确认兼容（有条件） | Apache-2.0 OR MIT; preserve chosen applicable notices, no upstream modification. | [官方](https://github.com/ormsgpack/ormsgpack/blob/master/LICENSE-MIT) |
| packaging | 26.4 | 已确认兼容（有条件） | Apache-2.0 OR BSD-2-Clause. | [官方](https://github.com/pypa/packaging/blob/main/LICENSE) |
| pillow | 13.0.0 | 需要人工确认 | MIT-CMU plus bundled third-party notices; native image libraries need manual review. | [官方](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| pip | 23.1.2 | 已确认兼容（有条件） | MIT build/install tool; not an application runtime requirement. | [官方](https://github.com/pypa/pip/blob/main/LICENSE.txt) |
| python-dateutil | 2.9.0.post0 | 已确认兼容（有条件） | Apache-2.0 and historical BSD contributions; preserve both sections. | [官方](https://github.com/dateutil/dateutil/blob/master/LICENSE) |
| setuptools | 65.5.0 | 已确认兼容（有条件） | MIT build tool; bundled vendor notices require review if redistributed. | [官方](https://github.com/pypa/setuptools/blob/main/LICENSE) |
| sniffio | 1.3.1 | 已确认兼容（有条件） | Apache-2.0 OR MIT. | [官方](https://github.com/python-trio/sniffio/blob/master/LICENSE) |
| sqlite-vec | 0.1.9 | 需要人工确认 | Official MIT option found, installed wheel has no license file; exact wheel notice scope pending. | [官方](https://github.com/asg017/sqlite-vec/blob/main/LICENSE-MIT) |
| tokenizers | 0.23.3 | 需要人工确认 | Official Apache-2.0; installed wheel lacks license file, manual release artifact/notice confirmation. | [官方](https://github.com/huggingface/tokenizers/blob/main/LICENSE) |
| tqdm | 4.70.1 | 已确认兼容（有条件） | MPL-2.0 AND MIT with per-file/contributor exceptions; preserve license scope. | [官方](https://github.com/tqdm/tqdm/blob/master/LICENCE) |
| lightningcss | 1.33.0 | 已确认兼容（有条件） | MPL-2.0; file-level obligations retained, not MIT. | [官方](https://github.com/parcel-bundler/lightningcss/blob/master/LICENSE) |
| lightningcss-win32-x64-msvc | 1.33.0 | 需要人工确认 | Native MPL-2.0 binding; bundled Rust components/notices not exhaustively reviewed. | [官方](https://github.com/parcel-bundler/lightningcss/blob/master/LICENSE) |

汇总：13 项有条件兼容，8 项人工确认。MPL 文件级义务不能因项目 MIT 被移除，也不能仅因使用 MPL 依赖就断言项目不兼容。参考 [Mozilla FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)。onnxruntime 官方猜测 LICENSE 路径返回 404，明确采用随安装包的许可证和通知作为当前证据，不伪造在线验证成功。

## 图片、图标与字体

以下五份文件与 Vite 官方 React 模板当前文件的 SHA-256 完全一致：frontend/src/assets/hero.png、react.svg、vite.svg，以及 frontend/public/icons.svg、favicon.svg。来源为 https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react ，上游许可 https://github.com/vitejs/vite/blob/main/LICENSE 为 MIT。

来源已确认，但模板版权/许可声明应在发布时保留，不能只用本项目 MIT 声明覆盖第三方素材。React/Vite 及社交图标的标志、商标或暗示官方背书不因 MIT 自动获授权，具体品牌使用仍需作者确认。本轮不更换图标或擅自写入商标授权结论。

未发现前端 src/public 下捆绑 woff/woff2/ttf/otf/eot；CSS 声明 Inter、Segoe UI、Microsoft YaHei 和系统回退，未发现随包字体。未来加入字体文件或外链字体需另行检查，不能把系统字体打包分发。

## EmbeddingGemma：独立条款，非 MIT

官方模型卡 https://huggingface.co/google/embeddinggemma-300m 标注 Gemma 许可；条款 https://gemma.ai/resources/terms/ ，禁止用途 https://gemma.ai/resources/prohibited-use/ 。

- 使用前需核对并接受相应模型条款，不得把权重或衍生模型改标 MIT。
- 分发模型/衍生模型需按条款传递协议和使用限制、标示修改；非托管方式分发还涉及 Notice 文件。具体适用范围以所用模型版本及当时协议为准。
- 禁止用途包含侵权、非法或危险活动、诈骗/恶意软件及规避安全约束等；它不是无条件的 MIT 式使用许可。
- 使用限制是否适用于服务及分发不能仅以“不捆绑权重”推断豁免；上线前需核对 hosted service 等定义。
- 本源码包没有权重。Ollama embeddinggemma 标签的具体构建与上游协议对应关系仍待确认，本轮不下载或重新分发模型。

## 存在风险及作者待确认

1. 项目版权持有人已按指示确认为 xyx-712，年份 2026。
2. 确认仅发布源码，还是将来分发依赖二进制、容器和模型；后者需要额外许可/NOTICE核对。
3. 对 8 项人工确认依赖，核对缺失通知、复合许可和原生捆绑组件。
4. 确认保留 Vite 模板归属说明，以及当前 favicon/标志的使用目的；不宣称品牌授权。
5. 确认实际 EmbeddingGemma 构建及使用场景符合独立条款。

没有发现已证实必须删除的依赖；上述未完成义务属于合规风险，不表示已证实侵权。旧 ZIP 是此前快照，本轮没有重新打包；当前文档更新后须另行生成新包。

## 本轮源码发布范围确认

用户明确限定只分发源代码，不打包模型权重、第三方二进制、.venv、node_modules 或运行数据库。Vite 图片/图标文件不改动；原始 Vite MIT 声明已逐字节保存在 third-party-licenses/vite-LICENSE.txt，并补 THIRD-PARTY-NOTICES.md。依赖本身的声明没有修改。

### 八项重新核查

| 依赖 | 版本 | 当前许可证证据 | 状态 | 来源 |
| --- | --- | --- | --- | --- |
| grpcio | 1.85.3 | Apache-2.0 | 待审核 | [官方依据](https://github.com/grpc/grpc/blob/master/LICENSE) |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 待审核 | [官方依据](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| onnxruntime | 1.32.0 | MIT License | 待审核 | [官方依据](https://onnxruntime.ai) |
| orjson | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | 待审核 | [官方依据](https://github.com/ijl/orjson) |
| pillow | 13.0.0 | MIT-CMU | 待审核 | [官方依据](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| sqlite-vec | 0.1.9 | MIT License, Apache License, Version 2.0 | 待审核 | [官方依据](https://github.com/asg017/sqlite-vec/blob/main/LICENSE-MIT) |
| tokenizers | 0.23.3 | see bundled license / upstream Apache-2.0 | 待审核 | [官方依据](https://github.com/huggingface/tokenizers/blob/main/LICENSE) |
| lightningcss-win32-x64-msvc | 1.33.0 | MPL-2.0 | 待审核 | [官方依据](https://github.com/parcel-bundler/lightningcss/blob/master/LICENSE) |

八项均保守保留待审核，没有因缩小分发范围自动改为兼容。grpcio/NumPy/ONNX Runtime/Pillow 的原生附带组件与通知未完成逐项映射；orjson 的组合条款需按文件核对；sqlite-vec/tokenizers 当前 wheel 缺少许可证文件，官方主分支不代替确切版本工件核验；lightningcss Windows 绑定还需核对原生组件通知。ONNX Runtime 猜测的上游 LICENSE 地址仍返回 404，使用随安装包 LICENSE 和 ThirdPartyNotices.txt 作为本机证据，不冒充在线核验通过。

EmbeddingGemma 继续保留独立 Gemma 条款与禁止用途链接，模型未进入包；未来运行服务或分发模型仍须按实际模型版本核对条款。
