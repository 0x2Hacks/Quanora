"""文件操作工具定义"""
from pathlib import Path
import re

from agent.domain import tool_error, tool_ok

_SKIP_DIRS = frozenset({
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".tox",
    ".hg", ".svn", "site-packages",
})
_GREP_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_READ_LARGE_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_READ_MAX_LIMIT = 2000
_MAX_LINE_CHARS = 2000


def _is_skipped_path(path: Path) -> bool:
    return bool(_SKIP_DIRS & set(path.parts))


def _relative_path(file_path: Path, root: Path) -> str:
    base = root if root.is_dir() else root.parent
    try:
        return file_path.relative_to(base).as_posix()
    except ValueError:
        return file_path.name


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _clip_text(text: str, limit: int = _MAX_LINE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...(truncated:{len(text)})"


def read_file(file_path: str, offset: int = 1, limit: int = 1000) -> str:
    """
    读取文件内容，支持分页和行号显示。
    :param file_path: 文件路径
    :param offset: 起始行号 (默认 1)
    :param limit: 读取最大行数 (默认 1000)
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return tool_error("read_file", f"文件不存在: {file_path}", "NotFound")
        if not path.is_file():
            return tool_error("read_file", f"路径不是文件: {file_path}", "NotAFile")
        offset = int(offset)
        requested_limit = int(limit)
        if offset < 1:
            return tool_error("read_file", "offset 必须 >= 1。", "InvalidOffset")
        if requested_limit < 1:
            return tool_error("read_file", "limit 必须 >= 1。", "InvalidLimit")

        effective_limit = min(requested_limit, _READ_MAX_LIMIT)
        limit_clamped = requested_limit != effective_limit
        file_size = path.stat().st_size
        large_file = file_size > _READ_LARGE_FILE_SIZE

        selected: list[tuple[int, str]] = []
        end_line = offset + effective_limit - 1
        total_lines = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                total_lines = line_no
                if offset <= line_no <= end_line:
                    selected.append((line_no, _clip_text(line.rstrip("\n").rstrip("\r"))))

        if offset > total_lines:
            return tool_error(
                "read_file",
                f"起始行 {offset} 超出文件总行数 ({total_lines} 行)。",
                "OffsetOutOfRange",
                meta={"file_path": str(path), "offset": offset, "total_lines": total_lines},
            )

        shown_start = selected[0][0] if selected else offset
        shown_end = selected[-1][0] if selected else offset - 1
        truncated = shown_end < total_lines
        next_offset = shown_end + 1 if truncated else None
        output = [f"Showing lines {shown_start} to {shown_end} of {total_lines}:"]
        for line_no, line in selected:
            output.append(f"{line_no:4d} | {line}")

        return tool_ok(
            "read_file",
            "\n".join(output),
            meta={
                "file_path": str(path),
                "size_bytes": file_size,
                "large_file": large_file,
                "offset": offset,
                "limit": effective_limit,
                "requested_limit": requested_limit,
                "limit_clamped": limit_clamped,
                "shown_start": shown_start,
                "shown_end": shown_end,
                "total_lines": total_lines,
                "truncated": truncated,
                "next_offset": next_offset,
            },
        )
    except Exception as e:
        return tool_error("read_file", f"读取错误: {e}", type(e).__name__)

def write_file(file_path: str, content: str) -> str:
    try:
        path = Path(file_path).expanduser().resolve()

        is_overwrite = path.exists()
        action = "覆盖" if is_overwrite else "新建"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        msg = f"成功{action}文件: {path} ({len(content)} 字符)"
        if is_overwrite:
            msg += "\n[警告] 原文件已被完全覆盖。如果这不是你的本意，请使用 edit_file 进行局部修改。"

        return tool_ok("write_file", msg, meta={"file_path": str(path), "action": action, "chars": len(content)})
    except Exception as e:
        return tool_error("write_file", f"写入错误: {e}", type(e).__name__)

def edit_file(file_path: str, old_str: str, new_str: str) -> str:
    """
    精确替换文件中的某一段文本 (Search and Replace)。
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return tool_error("edit_file", f"文件不存在: {file_path}", "NotFound")
        if not path.is_file():
            return tool_error("edit_file", f"路径不是文件: {file_path}", "NotAFile")

        if path.stat().st_size > 10 * 1024 * 1024:
            return tool_error("edit_file", "文件过大（>10MB），无法进行全量读取编辑。请考虑使用 Bash 命令或其他方式处理。", "FileTooLarge")

        content = path.read_text(encoding="utf-8")

        if old_str not in content:
            return tool_error("edit_file", "编辑失败：在文件中找不到指定的 old_str (搜索文本)。请确保完全匹配（包括空格、缩进和换行符）。建议先使用 read_file 查看确切的内容。", "OldStrNotFound")

        count = content.count(old_str)
        if count > 1:
            return tool_error(
                "edit_file",
                f"编辑失败：找到 {count} 处匹配的 old_str。为了安全起见，old_str 必须在文件中唯一存在。请在 old_str 中包含更多的上下文行（比如上一行和下一行）以确保唯一性。",
                "OldStrNotUnique",
                meta={"count": count},
            )

        new_content = content.replace(old_str, new_str)
        path.write_text(new_content, encoding="utf-8")
        return tool_ok("edit_file", f"成功：在 {file_path} 中完成了文本替换。", meta={"file_path": str(path)})
    except Exception as e:
        return tool_error("edit_file", f"编辑错误: {e}", type(e).__name__)

def glob(pattern: str, path: str = ".", max_results: int = 100, offset: int = 0) -> str:
    """
    Find files by glob pattern and return compact file entries with sizes.
    """
    try:
        search_path = Path(path).expanduser().resolve()
        if not search_path.exists():
            return tool_error("glob", f"Directory does not exist: {path}", "NotFound")
        if not search_path.is_dir():
            return tool_error("glob", f"Path is not a directory: {path}", "NotADirectory")

        offset = max(0, int(offset))
        max_results = max(0, int(max_results))
        results: list[dict[str, object]] = []
        seen = 0
        truncated = False

        for file_path in sorted(search_path.rglob(pattern), key=lambda item: item.as_posix().lower()):
            if not file_path.is_file() or _is_skipped_path(file_path):
                continue
            try:
                stat = file_path.stat()
            except Exception:
                continue

            if seen < offset:
                seen += 1
                continue
            if len(results) >= max_results:
                truncated = True
                break
            size = int(stat.st_size)
            results.append(
                {
                    "path": _relative_path(file_path, search_path),
                    "size_bytes": size,
                    "size_label": _format_size(size),
                }
            )
            seen += 1

        return tool_ok(
            "glob",
            results,
            meta={
                "path": str(search_path),
                "pattern": pattern,
                "count": len(results),
                "offset": offset,
                "max_results": max_results,
                "truncated": truncated,
                "next_offset": offset + len(results) if truncated else None,
            },
        )
    except Exception as e:
        return tool_error("glob", f"Glob error: {e}", type(e).__name__)


def grep(
    pattern: str,
    path: str = ".",
    glob_pattern: str = "**/*",
    case_sensitive: bool = False,
    max_results: int = 50,
    output_mode: str = "files_with_matches",
    offset: int = 0,
    context: int = 0,
) -> str:
    """
    Search for a regex pattern in files.
    """
    try:
        if output_mode not in {"files_with_matches", "content", "count"}:
            return tool_error("grep", f"Invalid output_mode: {output_mode}", "InvalidOutputMode")

        search_path = Path(path).expanduser().resolve()
        if not search_path.exists():
            return tool_error("grep", f"Path does not exist: {path}", "NotFound")

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return tool_error("grep", f"Invalid regex pattern: {e}", "InvalidRegex")

        max_results = max(0, int(max_results))
        offset = max(0, int(offset))
        context = max(0, int(context))
        results: list[object] = []
        seen = 0
        truncated = False
        skipped_large_files = 0

        if search_path.is_file():
            files_to_search = [search_path]
        else:
            files_to_search = sorted(search_path.rglob(glob_pattern), key=lambda item: item.as_posix().lower())

        for file_path in files_to_search:
            if truncated:
                break

            if not file_path.is_file():
                continue

            if _is_skipped_path(file_path):
                continue

            try:
                if file_path.stat().st_size > _GREP_MAX_FILE_SIZE:
                    skipped_large_files += 1
                    continue

                rel_path = _relative_path(file_path, search_path)
                if output_mode == "files_with_matches":
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        if any(regex.search(line) for line in f):
                            seen, truncated = _append_paged(results, rel_path, seen, offset, max_results)
                    continue

                if output_mode == "count":
                    count = 0
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if regex.search(line):
                                count += 1
                    if count:
                        seen, truncated = _append_paged(results, {"file": rel_path, "count": count}, seen, offset, max_results)
                    continue

                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                for index, line in enumerate(lines):
                    if not regex.search(line):
                        continue
                    record: dict[str, object] = {
                        "file": rel_path,
                        "line": index + 1,
                        "text": _clip_text(line.strip(), 500),
                    }
                    if context:
                        start = max(0, index - context)
                        end = min(len(lines), index + context + 1)
                        record["context"] = [
                            {
                                "line": line_index + 1,
                                "text": _clip_text(lines[line_index].strip(), 500),
                                "match": line_index == index,
                            }
                            for line_index in range(start, end)
                        ]
                    seen, truncated = _append_paged(results, record, seen, offset, max_results)
                    if truncated:
                        break
            except Exception:
                continue

        return tool_ok(
            "grep",
            results,
            meta={
                "pattern": pattern,
                "path": str(search_path),
                "glob_pattern": glob_pattern,
                "output_mode": output_mode,
                "matches": len(results),
                "offset": offset,
                "max_results": max_results,
                "truncated": truncated,
                "next_offset": offset + len(results) if truncated else None,
                "skipped_large_files": skipped_large_files,
            },
        )
    except Exception as e:
        return tool_error("grep", f"Grep error: {e}", type(e).__name__)


def _append_paged(results: list, item: object, seen: int, offset: int, max_results: int) -> tuple[int, bool]:
    seen += 1
    if seen <= offset:
        return seen, False
    if len(results) >= max_results:
        return seen, True
    results.append(item)
    return seen, False

def _build_tree(path: Path, prefix: str = "", depth: int = 0, max_depth: int = 2) -> tuple:
    try:
        items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError:
        return [f"{prefix}└── [权限拒绝]"], 0, 0
    lines, files, dirs = [], 0, 0
    for i, item in enumerate(items):
        if item.name.startswith('.'): continue
        is_last = i == len(items) - 1
        conn = "└── " if is_last else "├── "
        ext = "    " if is_last else "│   "
        if item.is_dir():
            lines.append(f"{prefix}{conn}📁 {item.name}/")
            if depth < max_depth - 1:
                sub, f, d = _build_tree(item, prefix + ext, depth + 1, max_depth)
                lines.extend(sub)
                dirs += 1 + d
                files += f
            else:
                dirs += 1
        else:
            lines.append(f"{prefix}{conn}📄 {item.name} ({_format_size(item.stat().st_size)})")
            files += 1
    return lines, files, dirs

def list_files(directory: str = ".", pattern: str = "*", recursive: bool = True, max_depth: int = 2) -> str:
    try:
        path = Path(directory).resolve()
        if not path.exists():
            return tool_error("list_files", f"目录不存在: {directory}", "NotFound")
        if not path.is_dir():
            return tool_error("list_files", f"不是目录: {directory}", "NotADirectory")
        if not recursive:
            result = []
            for f in sorted(path.glob(pattern)):
                if f.name.startswith('.'): continue
                if f.is_file(): result.append(f"📄 {f.name} ({_format_size(f.stat().st_size)})")
                else: result.append(f"📁 {f.name}/")
            return tool_ok("list_files", "\n".join(result) or "没有找到文件", meta={"directory": str(path), "recursive": False, "pattern": pattern})
        lines, f, d = _build_tree(path, max_depth=max_depth)
        return tool_ok(
            "list_files",
            "\n".join([f"📁 {path}/"] + lines + ["", f"总计: {d} 个文件夹, {f} 个文件"]),
            meta={"directory": str(path), "recursive": True, "pattern": pattern},
        )
    except Exception as e:
        return tool_error("list_files", f"错误: {e}", type(e).__name__)
