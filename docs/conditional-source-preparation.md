# 有条件源码展示准备记录

```json
{
  "date": "2026-11-25",
  "source_zip": "my-agent-source-20261125-public-candidate-r1.zip",
  "source_zip_sha256": "3bba8e66c59ba696ab1cac2da96319860f16cf01ed6a437b836d45f55ba69f21",
  "source_count": 193,
  "core_unchanged": 141,
  "excluded_from_source_zip": [],
  "excluded_by_scope": [
    "original .git/history",
    "installed environments",
    "runtime/user data",
    "model weights",
    "third-party binaries",
    "build/cache"
  ],
  "note": "Excluded categories absent in input ZIP; not copied from working directories. Synthetic test credentials remain fixtures, not deployed accounts. Pattern scanning does not prove absence of all secrets.",
  "document_changes": [
    {
      "file": "docs/abstract-reference-fix.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/architecture-stage1.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/architecture-stage3.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/architecture-stage4-1.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/architecture-stage4-2.md",
      "reason": "historical machine path redaction",
      "replacements": 3
    },
    {
      "file": "docs/architecture-stage4-4.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/architecture-stage4-final.md",
      "reason": "historical machine path redaction",
      "replacements": 4
    },
    {
      "file": "docs/final-acceptance.md",
      "reason": "historical machine path redaction",
      "replacements": 2
    },
    {
      "file": "docs/final-stage7-2.md",
      "reason": "historical machine path redaction",
      "replacements": 3
    },
    {
      "file": "docs/memory-stage5-1.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/memory-stage5-2.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/memory-stage5-3.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/memory-stage5-4.md",
      "reason": "historical machine path redaction",
      "replacements": 2
    },
    {
      "file": "docs/memory-stage5-final.md",
      "reason": "historical machine path redaction",
      "replacements": 2
    },
    {
      "file": "docs/planner-repair-acceptance.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/rag-closure-acceptance.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "docs/readme-history-through-stage6.md",
      "reason": "historical machine path redaction",
      "replacements": 8
    },
    {
      "file": "docs/stability-stage6.md",
      "reason": "historical machine path redaction",
      "replacements": 1
    },
    {
      "file": "README.md",
      "reason": "conditional source scope and pending-license disclosure"
    }
  ],
  "common_secret_pattern_hits": [],
  "original_license_files_unchanged": true,
  "pending_license_count": 8,
  "business_tests_rerun": false
}
```

剩余风险：八项许可证人工审核未闭合；历史报告保留测试结论仅作原环境记录；未知格式敏感信息不能由模式扫描穷尽排除；公网限速、配额与部署环境仍待验收。机器路径已仅在本副本历史文档中脱敏。未初始化Git、发布、提交或推送。
