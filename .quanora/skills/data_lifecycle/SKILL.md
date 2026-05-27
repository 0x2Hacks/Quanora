---
name: "data_lifecycle"
description: "管理项目数据的创建、使用、清理全生命周期，防止冗余堆积和误删"
triggers:
  - "下载数据"
  - "删除数据"
  - "清理数据"
  - "data_manifest"
  - "数据冗余"
  - "数据清理"
  - "数据下载"
---

# Data Lifecycle Skill

## 目的
管理项目数据的完整生命周期：创建、使用、归档、删除。防止冗余数据堆积，杜绝误删关键数据。

## 强制规则

### 1. 下载数据前 — 检查清单
在下载任何数据文件之前，**必须**：
- 读取项目根目录的 `data_manifest.json`，确认是否已有可复用的数据
- 如果已有数据覆盖所需范围，优先使用现有数据
- 如果必须下载新数据，先在 `data_manifest.json` 中登记

### 2. 创建数据后 — 登记清单
每次创建新数据文件后，**必须**：
- 在 `data_manifest.json` 中添加条目，包含：
  - `description`: 数据描述
  - `source`: 数据来源
  - `producer`: 生成脚本路径
  - `consumers`: 消费者代码路径列表
  - `date_range`: 日期范围
  - `reproducible`: 是否可再生（true/false）
  - `reproducibility_note`: 如何再生
  - `lifecycle`: "active" | "candidate_cleanup" | "archived"
- 如果 `data_manifest.json` 不存在，创建它

### 3. 删除数据前 — 双重确认
**绝对禁止**直接 `rm` 删除数据文件。删除前**必须**：
1. 在 `data_manifest.json` 中检查该数据的 `consumers` 列表
2. 用 `grep` 在项目代码中搜索对该文件路径的引用
3. 确认 `reproducible=true`（可再生数据才可安全删除）
4. 向用户说明删除理由，等待确认
5. 删除后将条目移到 `data_manifest.json` 的 `deleted` 段

### 4. 临时/测试数据 — 及时清理
- 测试下载的数据文件，标注 `lifecycle: "candidate_cleanup"`
- 测试完成后，主动建议用户清理
- 优先使用项目级临时目录（如 `data/tmp/`）而非散落在各处

### 5. 数据格式选择
- 优先使用 Parquet 格式（压缩好、读取快）
- 避免 CSV 与 Parquet 同时保存相同数据
- 如果两者共存，在清单中标注关系，后续清理冗余格式

## 模板

### data_manifest.json 结构
```json
{
  "version": 1,
  "project": "项目名",
  "generated_at": "ISO日期",
  "datasets": {
    "相对路径": {
      "description": "",
      "source": "",
      "producer": "",
      "consumers": [],
      "date_range": "",
      "rows": 0,
      "reproducible": true,
      "reproducibility_note": "",
      "lifecycle": "active"
    }
  },
  "deleted": {
    "路径": {
      "reason": "",
      "deleted_at": ""
    }
  }
}
```
