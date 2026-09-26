"""
文件处理模块 — 优雅地读取多种文件格式供 LLM 理解

支持: ppt, pptx, doc, docx, xls, xlsx, pdf, txt, md, 常见代码文件
输出格式: (文件名, 文件类型, 纯文本内容, 截断标记)

用法:
    handler = FileHandler()
    results = handler.read_files(["path/to/a.pptx", "path/to/b.pdf"])
    for name, ftype, content, truncated in results:
        print(f"[{ftype}] {name}: {len(content)} chars")
"""

import io
import os
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger("DesktopPet.FileHandler")

# ── 支持的文件类型 ──
SUPPORTED_EXTENSIONS = {
    # 办公文档
    ".pdf":     "PDF文档",
    ".doc":     "Word文档",
    ".docx":    "Word文档",
    ".xls":     "Excel表格",
    ".xlsx":    "Excel表格",
    ".ppt":     "PPT演示",
    ".pptx":    "PPT演示",
    # 纯文本
    ".txt":     "文本文件",
    ".md":      "Markdown",
    ".csv":     "CSV表格",
    # 代码
    ".py":      "Python",  ".js": "JavaScript",   ".ts": "TypeScript",
    ".jsx":     "React JSX",  ".tsx": "React TSX",
    ".java":    "Java",   ".kt": "Kotlin",        ".scala": "Scala",
    ".c":       "C语言",  ".cpp": "C++",          ".h": "C头文件",
    ".hpp":     "C++头文件", ".cs": "C#",
    ".go":      "Go",     ".rs": "Rust",
    ".rb":      "Ruby",   ".php": "PHP",          ".pl": "Perl",
    ".swift":   "Swift",  ".m": "Objective-C",
    ".r":       "R语言",
    ".lua":     "Lua",    ".sql": "SQL",
    # 数据/配置
    ".json":    "JSON",   ".yaml": "YAML",        ".yml": "YAML",
    ".xml":     "XML",    ".toml": "TOML",
    ".ini":     "INI配置", ".cfg": "配置文件",     ".conf": "配置文件",
    ".env":     "环境变量",
    # Web
    ".html":    "HTML",   ".htm": "HTML",
    ".css":     "CSS",    ".sass": "SASS",        ".scss": "SCSS",
    ".vue":     "Vue",    ".svelte": "Svelte",
    # Shell
    ".sh":      "Shell",  ".bash": "Bash",        ".zsh": "Zsh",
    ".bat":     "批处理", ".ps1": "PowerShell",
    # 其他
    ".tex":     "LaTeX",
    ".log":     "日志",
    ".gitignore": "Git忽略规则",
    ".dockerfile": "Dockerfile",
}

TEXT_LIKE_EXTENSIONS = {".txt", ".md", ".csv"} | {k for k in SUPPORTED_EXTENSIONS
    if SUPPORTED_EXTENSIONS[k] in {
        "Python","JavaScript","TypeScript","Java","Kotlin","Scala",
        "C语言","C++","C头文件","C++头文件","C#","Go","Rust",
        "Ruby","PHP","Perl","Swift","Objective-C","R语言","Lua","SQL",
        "JSON","YAML","XML","TOML","INI配置","配置文件","环境变量",
        "HTML","CSS","SASS","SCSS","Vue","Svelte",
        "Shell","Bash","Zsh","批处理","PowerShell",
        "LaTeX","日志","Git忽略规则","Dockerfile",
        "Markdown","CSV表格","文本文件",
    }}


class FileReader:
    """单一文件读取器 — 每种格式一个 reader"""

    @staticmethod
    def read_pdf(path: str) -> str:
        from PyPDF2 import PdfReader
        reader = PdfReader(path)
        return "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

    @staticmethod
    def read_docx(path: str) -> str:
        from docx import Document
        doc = Document(path)
        return "\n".join(
            p.text for p in doc.paragraphs
        )

    @staticmethod
    def read_xlsx(path: str) -> str:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        blocks = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append(" | ".join(
                    str(c) if c is not None else "" for c in row
                ))
            blocks.append(f"=== Sheet: {sheet_name} ===")
            blocks.extend(rows)
        return "\n".join(blocks)

    @staticmethod
    def read_pptx(path: str) -> str:
        from pptx import Presentation
        prs = Presentation(path)
        slides = []
        for i, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                texts.extend(FileReader._extract_shape_text(shape))
            try:
                if slide.has_notes_slide:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        texts.append(f"[备注]: {notes}")
            except Exception:
                pass
            slides.append(f"--- Slide {i} ---\n" + "\n".join(texts))
        return "\n".join(slides)

    @staticmethod
    def _extract_shape_text(shape) -> list:
        """递归提取形状中的文字"""
        texts = []
        try:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = para.text.strip()
                    if t:
                        texts.append(t)
        except Exception:
            pass
        try:
            if shape.has_table:
                for row in shape.table.rows:
                    texts.append(" | ".join(
                        cell.text.strip() for cell in row.cells
                    ))
        except Exception:
            pass
        try:
            # 组合图形（group shapes）
            if hasattr(shape, 'shapes'):
                for sub in shape.shapes:
                    texts.extend(FileReader._extract_shape_text(sub))
        except Exception:
            pass
        return texts

    @staticmethod
    def read_text(path: str, encoding: str = "utf-8") -> str:
        with open(path, encoding=encoding, errors="ignore") as f:
            return f.read()

    @staticmethod
    def read_fallback(path: str) -> None:
        """不支持格式 — 返回 None 表示无法读取内容"""
        return None


# ── 格式 → 读取器 路由表 ──
_ROUTER = {
    ".pdf":  FileReader.read_pdf,
    ".doc":  FileReader.read_docx,
    ".docx": FileReader.read_docx,
    ".xls":  FileReader.read_xlsx,
    ".xlsx": FileReader.read_xlsx,
    ".ppt":  FileReader.read_pptx,
    ".pptx": FileReader.read_pptx,
}


class FileHandler:
    """文件处理主入口 — 接收路径列表，返回解析结果"""

    MAX_CHARS = 15_000          # 单文件最大提取字符数
    MAX_TOTAL_CHARS = 60_000    # 一次调用总字符上限

    def __init__(self, max_chars: int = None, max_total: int = None):
        self.max_chars = max_chars or self.MAX_CHARS
        self.max_total = max_total or self.MAX_TOTAL_CHARS

    def read_files(self, paths: List[str]) -> List[dict]:
        """
        读取多个文件，返回结果列表。

        每条结果:
            { "name": str, "type": str, "content": str,
              "truncated": bool, "size_kb": float, "error": Optional[str] }
        """
        results = []
        total_chars = 0

        for path in paths:
            if total_chars >= self.max_total:
                results.append({
                    "name": os.path.basename(path),
                    "type": "—",
                    "content": "",
                    "truncated": False,
                    "size_kb": round(os.path.getsize(path) / 1024, 1),
                    "error": "已达总字符上限，跳过"
                })
                continue

            result = self._read_one(path)
            result["size_kb"] = round(os.path.getsize(path) / 1024, 1)

            if result["content"]:
                total_chars += len(result["content"])

            results.append(result)

        return results

    def _read_one(self, path: str) -> dict:
        """读取单个文件"""
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()

        # ── 1. 办公文档（需额外依赖） ──
        reader = _ROUTER.get(ext)
        if reader:
            return self._try_read(path, name, ext, reader)

        # ── 2. 纯文本/代码文件 ──
        if ext in TEXT_LIKE_EXTENSIONS or (ext == "" or ext in {".gitignore", ".dockerfile"}):
            return self._read_text_file(path, name, ext)

        # ── 3. 不支持格式 ──
        return {
            "name": name,
            "type": SUPPORTED_EXTENSIONS.get(ext, f"未知格式 ({ext})"),
            "content": "",
            "truncated": False,
            "error": None,  # 无错误，只是不支持
        }

    def _try_read(self, path: str, name: str, ext: str, reader) -> dict:
        """尝试用指定 reader 读取，捕获依赖缺失等异常"""
        try:
            content = reader(path)
            if not content or not content.strip():
                return {
                    "name": name,
                    "type": SUPPORTED_EXTENSIONS.get(ext, ext),
                    "content": "",
                    "truncated": False,
                    "error": "文件内容为空或无法提取文字",
                }
            truncated = len(content) > self.max_chars
            if truncated:
                content = content[:self.max_chars] + "\n\n…(截断，全文过长)"
            return {
                "name": name,
                "type": SUPPORTED_EXTENSIONS.get(ext, ext),
                "content": content,
                "truncated": truncated,
                "error": None,
            }
        except ImportError as e:
            missing = str(e).split("'")[1] if "'" in str(e) else "未知"
            return {
                "name": name,
                "type": SUPPORTED_EXTENSIONS.get(ext, ext),
                "content": "",
                "truncated": False,
                "error": f"缺少依赖库: {missing}（请运行: pip install {missing}）",
            }
        except Exception as e:
            return {
                "name": name,
                "type": SUPPORTED_EXTENSIONS.get(ext, ext),
                "content": "",
                "truncated": False,
                "error": str(e)[:200],
            }

    def _read_text_file(self, path: str, name: str, ext: str) -> dict:
        """读取纯文本/代码文件"""
        try:
            content = FileReader.read_text(path)
            truncated = len(content) > self.max_chars
            if truncated:
                content = content[:self.max_chars] + "\n\n…(截断，全文过长)"
            return {
                "name": name,
                "type": SUPPORTED_EXTENSIONS.get(ext, "文本文件"),
                "content": content,
                "truncated": truncated,
                "error": None,
            }
        except Exception as e:
            return {
                "name": name,
                "type": SUPPORTED_EXTENSIONS.get(ext, "文本文件"),
                "content": "",
                "truncated": False,
                "error": str(e)[:200],
            }

    # ── 便捷方法：生成 LLM 消息体 ──
    def build_message(self, user_text: str, paths: List[str]) -> str:
        """
        构建发给 LLM 的完整消息体：
        [用户输入] + [文件1内容] + [文件2内容] + ...
        """
        parts = [user_text] if user_text else []
        results = self.read_files(paths)

        for r in results:
            header = f"--- 文件: {r['name']} ({r['type']}, {r['size_kb']}KB)"
            if r["error"]:
                header += f" [错误: {r['error']}]"
                parts.append(header)
            elif r["content"]:
                truncated_mark = " (截断)" if r["truncated"] else ""
                header += truncated_mark
                parts.append(header)
                parts.append(r["content"])
            else:
                parts.append(f"{header} [不支持直接读取内容]")

        return "\n".join(parts)


# ── 快捷函数 ──
_handler = FileHandler()

def read_files(paths: List[str]) -> List[dict]:
    """快捷调用"""
    return _handler.read_files(paths)

def build_message(user_text: str, paths: List[str]) -> str:
    """快捷调用"""
    return _handler.build_message(user_text, paths)
