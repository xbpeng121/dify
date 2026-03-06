# 孤立文件自动清理功能

## 需求背景

Dify 系统中存在文件上传后产生垃圾文件的问题。用户通过 `/files/upload` 接口上传文件后，某些场景下这些文件只使用一次就不再被引用，但系统没有自动清理机制，导致大量无用文件堆积。

**典型场景：**
- Workflow 文件输入：用户上传图片用于单次 workflow 执行，执行完成后文件不再需要
- 知识库检索测试：用户上传图片测试检索功能，测试完成后文件无用
- 图标替换：用户更换 App/Site/Dataset 图标时，旧图标文件成为垃圾

## 解决方案

实现基于后端自动识别的文件生命周期管理系统，通过分析文件关联关系，自动识别并清理孤立文件。

**核心策略：**
1. 统一等待窗口：所有文件等待 7 天（168小时）
2. 多重验证：检查 10 个关联点确保文件未被使用
3. 定时清理：每天凌晨 3 点自动执行
4. 部署保护：只清理部署后创建的文件，历史文件由管理员手动清理

## 核心实现

### 1. 清理任务逻辑

**文件：** `api/tasks/clean_orphaned_files_task.py`

```python
def clean_orphaned_files_task():
    """
    清理孤立文件

    策略：
    1. 等待 7 天（168小时）
    2. 检查 used=False
    3. 验证 10 个关联点
    4. 只清理部署后的文件
    """
    hours_threshold = dify_config.ORPHANED_FILE_CLEANUP_THRESHOLD_HOURS
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)

    query = db.session.query(UploadFile).filter(
        UploadFile.created_at < cutoff_time,
        UploadFile.used == False,
    )

    # 部署边界保护
    start_time_str = _get_boundary_time()
    if start_time_str:
        start_time = datetime.fromisoformat(start_time_str)
        query = query.filter(UploadFile.created_at >= start_time)
    else:
        # 首次运行：自动设置边界时间并保存
        current_time = datetime.utcnow().isoformat()
        _set_boundary_time(current_time)
        return {'checked': 0, 'cleaned': 0, 'boundary_set': current_time}

    # 查找候选文件
    candidate_files = query.limit(batch_size).all()

    for file in candidate_files:
        if _is_file_orphaned(file):
            FileService.delete_file_by_id(file.id)
```

### 2. 关联检查（10个检查点）

```python
def _is_file_orphaned(file: UploadFile) -> bool:
    """验证文件是否孤立"""

    # 1. Document 表
    if db.session.query(DatasetDocument.id).filter(
        DatasetDocument.data_source_type == "upload_file",
        cast(DatasetDocument.data_source_info, String).contains(file.id)
    ).first():
        return False

    # 2. WorkflowDraftVariableFile 表
    if db.session.query(WorkflowDraftVariableFile.id).filter(
        WorkflowDraftVariableFile.upload_file_id == file.id
    ).first():
        return False

    # 3. ToolFile 表
    if db.session.query(ToolFile.id).filter(
        ToolFile.file_key.contains(file.id)
    ).first():
        return False

    # 4. SegmentAttachmentBinding 表
    if db.session.query(SegmentAttachmentBinding.id).filter(
        SegmentAttachmentBinding.attachment_id == file.id
    ).first():
        return False

    # 5. Account.avatar 字段
    if db.session.query(Account.id).filter(
        Account.avatar == file.id
    ).first():
        return False

    # 6. App.icon 字段
    if db.session.query(App.id).filter(
        App.icon_type == "image",
        App.icon == file.id
    ).first():
        return False

    # 7. Site.icon 字段
    if db.session.query(Site.id).filter(
        Site.icon_type == "image",
        Site.icon == file.id
    ).first():
        return False

    # 8. Tenant.custom_config 字段（Workspace logo）
    if db.session.query(Tenant.id).filter(
        cast(Tenant.custom_config, String).contains(file.id)
    ).first():
        return False

    # 9. DocumentSegment.content 字段（文档解析提取的图片）
    if db.session.query(DocumentSegment.id).filter(
        DocumentSegment.content.contains(file.id)
    ).first():
        return False

    # 10. Dataset.icon_info 字段
    if db.session.query(Dataset.id).filter(
        cast(Dataset.icon_info, String).contains(file.id)
    ).first():
        return False

    return True
```

### 3. 定时任务调度

**文件：** `api/schedule/clean_orphaned_files_schedule.py`

```python
@app.celery.task(queue="dataset")
def clean_orphaned_files():
    """每天凌晨3点执行清理任务"""
    from tasks.clean_orphaned_files_task import clean_orphaned_files_task

    logger.info("Starting scheduled orphaned files cleanup")
    result = clean_orphaned_files_task()
    logger.info(
        "Scheduled orphaned files cleanup completed: checked=%d, cleaned=%d",
        result.get('checked', 0),
        result.get('cleaned', 0)
    )
    return result
```

**Celery Beat 配置：** `api/extensions/ext_celery.py`

```python
if dify_config.ENABLE_ORPHANED_FILE_CLEANUP_TASK:
    imports.append("schedule.clean_orphaned_files_schedule")
    beat_schedule["clean_orphaned_files"] = {
        "task": "schedule.clean_orphaned_files_schedule.clean_orphaned_files",
        "schedule": crontab(minute="0", hour="3"),  # 每天凌晨3点
    }
```

### 4. 边界时间自动持久化

**文件：** `api/storage/orphaned_file_cleanup_boundary.txt`

首次运行时自动创建，存储部署边界时间：

```python
def _get_boundary_time() -> str | None:
    """获取边界时间：优先级 ENV > 文件"""
    if dify_config.ORPHANED_FILE_CLEANUP_START_TIME:
        return dify_config.ORPHANED_FILE_CLEANUP_START_TIME

    if BOUNDARY_TIME_FILE.exists():
        return BOUNDARY_TIME_FILE.read_text().strip()

    return None

def _set_boundary_time(boundary_time: str) -> bool:
    """保存边界时间到文件"""
    BOUNDARY_TIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOUNDARY_TIME_FILE.write_text(boundary_time)
    return True
```

## 配置说明

### 环境变量配置

**文件：** `api/.env`

```bash
# 孤立文件清理任务开关
ENABLE_ORPHANED_FILE_CLEANUP_TASK=true

# 清理阈值（小时）- 默认 168 小时（7天）
ORPHANED_FILE_CLEANUP_THRESHOLD_HOURS=168

# 单次处理批量大小
ORPHANED_FILE_CLEANUP_BATCH_SIZE=1000

# 清理开始时间（可选）- 只清理此时间之后创建的文件
# 如果不设置，首次运行时自动设置为当前时间并保存到文件
ORPHANED_FILE_CLEANUP_START_TIME=

# 告警阈值 - 单次清理超过此数量时记录 WARNING 日志
ORPHANED_FILE_CLEANUP_ALERT_THRESHOLD_CLEANED=5000

# 时区配置 - 影响所有定时任务
LOG_TZ=Asia/Shanghai
```

### 功能配置

**文件：** `api/configs/feature/__init__.py`

```python
ENABLE_ORPHANED_FILE_CLEANUP_TASK: bool = Field(
    description="Enable orphaned file cleanup task",
    default=True,
)
```

## 使用方法

### 自动清理（推荐）

任务会在每天凌晨 3 点（中国时区）自动执行，无需手动干预。

### 手动触发测试

```bash
# 方法1：通过 Celery 队列发送任务
uv run --project api python -c "
from app import celery
result = celery.send_task(
    'schedule.clean_orphaned_files_schedule.clean_orphaned_files',
    queue='dataset'
)
print(f'任务已发送: {result.id}')
"

# 方法2：直接执行函数（绕过队列）
uv run --project api python -c "
from schedule.clean_orphaned_files_schedule import clean_orphaned_files
result = clean_orphaned_files()
print(f'执行结果: {result}')
"
```

### 手动清理历史文件

```bash
# 预览模式 - 查看会删除哪些文件
uv run --project api flask clean-orphaned-files-manual --dry-run

# 清理 7 天前的文件
uv run --project api flask clean-orphaned-files-manual --hours 168

# 分批清理（每次 5000 个）
uv run --project api flask clean-orphaned-files-manual --hours 168 --limit 5000
```

## 修改文件列表

### 新增文件

1. `api/tasks/clean_orphaned_files_task.py` - 核心清理逻辑
2. `api/schedule/clean_orphaned_files_schedule.py` - 定时任务调度
3. `api/configs/feature/orphaned_file_cleanup.py` - 配置类定义
4. `api/storage/orphaned_file_cleanup_boundary.txt` - 边界时间存储（首次运行自动创建）

### 修改文件

1. `api/extensions/ext_celery.py` - 添加定时任务到 beat schedule
2. `api/configs/feature/__init__.py` - 添加功能开关配置
3. `api/.env` - 修改时区配置为 Asia/Shanghai
4. `api/.env.example` - 添加配置说明文档

## 技术要点

### 1. JSON 字段查询

PostgreSQL 中查询 JSON 字段需要使用 `cast(field, String).contains()`：

```python
# 正确方式
cast(Document.data_source_info, String).contains(file.id)

# 错误方式（会报错）
Document.data_source_info.contains(file.id)
```

### 2. 队列选择

使用 `dataset` 队列与其他清理任务保持一致：
- `clean_embedding_cache_task` → dataset
- `clean_messages` → dataset
- `clean_unused_datasets_task` → dataset
- `clean_workflow_runlogs_precise` → dataset

### 3. 时区配置

Celery 时区通过 `LOG_TZ` 环境变量配置：
- UTC：定时任务按 UTC 时间执行
- Asia/Shanghai：定时任务按中国时区执行

### 4. 任务结果

Celery 配置了 `task_ignore_result=True`，任务结果不会保存到 Redis，AsyncResult 永远显示 PENDING 状态。需要通过日志查看执行结果。

## 测试验证

### 功能测试

1. ✓ 任务已在 worker 中注册
2. ✓ 手动触发任务成功执行
3. ✓ 关联检查逻辑正确（10个检查点）
4. ✓ 边界时间自动持久化
5. ✓ 时区配置正确（Asia/Shanghai）

### 执行日志示例

```
[INFO] Starting scheduled orphaned files cleanup
[INFO] Loaded boundary time from file: 2026-03-05T12:39:45.728125
[INFO] Only cleaning files created after 2026-03-05T12:39:45.728125
[INFO] Found 0 candidate files older than 168 hours
[INFO] Orphaned files cleanup completed: checked=0, cleaned=0
```

## 注意事项

1. **首次运行**：会自动设置边界时间，不会清理任何文件
2. **历史文件**：需要使用 CLI 命令手动清理
3. **时区影响**：修改时区后需要重启 Celery beat 和 worker
4. **队列配置**：确保 worker 监听 dataset 队列
5. **日志监控**：单次清理超过 5000 个文件时会记录 WARNING 日志

## 部署检查清单

- [ ] 确认 `ENABLE_ORPHANED_FILE_CLEANUP_TASK=true`
- [ ] 确认 `LOG_TZ=Asia/Shanghai`
- [ ] 重启 Celery beat 和 worker
- [ ] 手动触发任务测试
- [ ] 查看 worker 日志确认执行成功
- [ ] 确认边界时间文件已创建：`api/storage/orphaned_file_cleanup_boundary.txt`
