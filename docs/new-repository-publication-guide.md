# 全新仓库初始化与公开操作（尚未执行）

先人工确认八项许可证与历史文档机器路径披露；不要使用原仓库历史。此目录无 .git，仅显式清单源码。GitHub 选择创建空仓库，仓库名与公开性由作者决定，不导入原仓库。

作者批准后，在本目录手动执行以下命令；本轮未执行：

```powershell
git init -b main
git config user.name "xyx-712"
git config user.email "填写本人已验证或GitHub提供的noreply邮箱"
git add --pathspec-from-file=RELEASE-FILES.txt
git diff --cached --stat
git diff --cached --name-only
# 人工检查暂存文件与敏感信息后再提交
# git commit -m "Initial source release"
# git remote add origin 填写新仓库地址
# git push -u origin main
```

不得直接 git add . 或复制原 .git。先核对 LICENSE、第三方声明、README，再批准公开；不要上传本地环境、模型或数据库。此包为候选，不代表许可证全部签核，不代表公网生产验收完成。
