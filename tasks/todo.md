# Todo List: Download File Lifecycle Indicator

## Phase 1: Core Logic

- [ ] **Task 1:** Modify `_start_download()` — 生成下载中文件路径
  - 文件以 `{原文件名}.{download_id}.downloading` 命名
  - `info.path` 含完整后缀，`info.filename` 存纯净名
  - 删除下载开始时的 `_get_unique_filepath()` 调用

- [ ] **Task 2:** Modify `_start_download()` — 下载完成时重命名到最终文件名
  - 下载成功完成后去掉 `.downloading` 后缀
  - 调用 `_get_unique_filepath()` 做重名检测
  - `os.rename()` 到最终文件名，更新 `info.path` 和 `info.relative_path`

### Checkpoint: Core Logic
- [ ] 下载中的文件在磁盘上可见 `.downloading` 后缀
- [ ] 下载完成自动去掉后缀并处理重名
- [ ] `/cancel` 能正确删除带后缀的残留文件
- [ ] 进度消息中显示的是纯净文件名（无后缀）

---

## Phase 2: Cleanup & Safety

- [ ] **Task 3:** 添加启动时残留检测（可选）
  - 扫描 DOWNLOAD_PATH 下所有 `.downloading` 文件
  - 日志输出警告信息

### Checkpoint: Cleanup
- [ ] 残留 `.downloading` 文件可被程序检测并警告

---

## Status: Pending Human Review

计划已制定，等待你确认后再开始实施。
