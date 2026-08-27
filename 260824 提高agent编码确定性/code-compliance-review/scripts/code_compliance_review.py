#!/usr/bin/env python3
"""Review git changes against configured local rules with Codex CLI."""

from __future__ import annotations

import concurrent.futures
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 is not expected here.
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None


@dataclass(frozen=True)
class RuleSource:
    label: str
    path: Path
    kind: str


@dataclass(frozen=True)
class TargetPath:
    label: str
    path: Path
    kind: str


@dataclass(frozen=True)
class ReviewResult:
    index: int
    rule: str
    conclusion: str
    output: str
    returncode: int
    error: str


def load_config(skill_root: Path) -> dict[str, Any]:
    config_path = skill_root / "config.toml"
    if not config_path.is_file():
        raise RuntimeError(f"missing config.toml: {config_path}")
    if tomllib is None:
        return parse_simple_toml(config_path)
    with config_path.open("rb") as fh:
        return tomllib.load(fh)


def parse_simple_toml(config_path: Path) -> dict[str, Any]:
    config: dict[str, Any] = {}
    pending_key: str | None = None
    pending_value: list[str] = []

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if pending_key is not None:
            pending_value.append(line)
            if line.endswith("]"):
                config[pending_key] = parse_simple_toml_value(" ".join(pending_value))
                pending_key = None
                pending_value = []
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if value.startswith("[") and not value.endswith("]"):
            pending_key = key
            pending_value = [value]
            continue
        config[key] = parse_simple_toml_value(value)

    if pending_key is not None:
        raise RuntimeError(f"unterminated array in config.toml for key: {pending_key}")
    return config


def parse_simple_toml_value(value: str) -> Any:
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    if value.startswith("["):
        return ast.literal_eval(value)
    if value.startswith('"') or value.startswith("'"):
        return ast.literal_eval(value)
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def config_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def split_csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    values: list[str] = []
    for chunk in value.split(","):
        item = chunk.strip()
        if item:
            values.append(item)
    return values


def split_skill_names(value: str | None) -> list[str]:
    return split_csv_values(value)


def read_text_file(path: Path, max_chars: int | None = None) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars] + "\n\n[TRUNCATED]\n"
    return text


def collect_md_source(repo_root: Path, relative_path: str, ignored: list[str]) -> RuleSource | None:
    path = repo_root / relative_path
    if not path.is_file():
        ignored.append(f"missing md file: {relative_path}")
        return None
    if not os.access(path, os.R_OK):
        ignored.append(f"unreadable md file: {relative_path}")
        return None
    return RuleSource(label=relative_path, path=path.resolve(), kind="md_file")


def collect_skill_sources(
    repo_root: Path,
    skills_root: str,
    skill_name: str,
    ignored: list[str],
) -> list[RuleSource]:
    skill_dir = repo_root / skills_root / skill_name
    if not skill_dir.is_dir():
        ignored.append(f"missing skill: {skill_name}")
        return []
    if not os.access(skill_dir, os.R_OK | os.X_OK):
        ignored.append(f"unreadable skill directory: {skill_name}")
        return []
    return [RuleSource(label=f"{skills_root}/{skill_name}", path=skill_dir.resolve(), kind="skill_dir")]


def dedupe_sources(sources: list[RuleSource]) -> list[RuleSource]:
    seen: set[Path] = set()
    deduped: list[RuleSource] = []
    for source in sources:
        resolved = source.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(source)
    return deduped


def run_command(args: list[str], cwd: Path, timeout: int = 60) -> str:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout.strip()
    if completed.stderr.strip():
        output = f"{output}\n[stderr]\n{completed.stderr.strip()}".strip()
    return output


def git_status_entries(repo_root: Path) -> list[tuple[str, str]]:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        cwd=str(repo_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        return []

    entries: list[tuple[str, str]] = []
    parts = completed.stdout.split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry or len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        entries.append((status, path))
        if "R" in status or "C" in status:
            index += 1
    return entries


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED]\n"


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def normalize_relative_path(value: str) -> str:
    return value.strip().lstrip("/").rstrip("/")


def resolve_ignored_roots(repo_root: Path, ignored_paths: list[str], evidence_dir_name: str) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw_path in [*ignored_paths, evidence_dir_name]:
        normalized = normalize_relative_path(str(raw_path))
        if not normalized:
            continue
        path = (repo_root / normalized).resolve()
        if path in seen:
            continue
        seen.add(path)
        roots.append(path)
    return roots


def should_ignore_path(path: Path, ignored_roots: list[Path]) -> bool:
    return any(path.resolve() == root or is_under(path, root) for root in ignored_roots)


def repo_relative_label(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def collect_target_paths(repo_root: Path, raw_targets: list[str], ignored_roots: list[Path]) -> tuple[list[TargetPath], list[str]]:
    targets: list[TargetPath] = []
    ignored: list[str] = []
    seen: set[Path] = set()
    repo_resolved = repo_root.resolve()

    for raw_target in raw_targets:
        raw_target = raw_target.strip()
        if not raw_target:
            continue

        supplied = Path(raw_target).expanduser()
        if supplied.is_absolute():
            candidate = supplied.resolve()
        else:
            normalized = normalize_relative_path(raw_target)
            if not normalized:
                ignored.append(f"empty target path: {raw_target}")
                continue
            candidate = (repo_root / normalized).resolve()

        try:
            candidate.relative_to(repo_resolved)
        except ValueError:
            ignored.append(f"target path outside repo: {raw_target}")
            continue

        label = repo_relative_label(candidate, repo_root)
        if should_ignore_path(candidate, ignored_roots):
            ignored.append(f"ignored target path: {label}")
            continue
        if not candidate.exists():
            ignored.append(f"missing target path: {label}")
            continue
        if not (candidate.is_file() or candidate.is_dir()):
            ignored.append(f"unsupported target path type: {label}")
            continue
        access_mode = os.R_OK | (os.X_OK if candidate.is_dir() else 0)
        if not os.access(candidate, access_mode):
            ignored.append(f"unreadable target path: {label}")
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        targets.append(TargetPath(label=label, path=candidate, kind="directory" if candidate.is_dir() else "file"))

    return targets, ignored


def relative_paths_for_git(paths: list[Path], repo_root: Path) -> list[str]:
    names: list[str] = []
    for path in paths:
        try:
            names.append(path.relative_to(repo_root).as_posix())
        except ValueError:
            continue
    return names


def changed_file_paths(repo_root: Path, ignored_roots: list[Path]) -> list[Path]:
    names = set()
    diff_names = run_command(["git", "diff", "HEAD", "--name-only"], repo_root)
    for line in diff_names.splitlines():
        line = line.strip()
        if line and not line.startswith("[stderr]"):
            names.add(line)

    for _status, name in git_status_entries(repo_root):
        names.add(name)

    paths = []
    for name in sorted(names):
        path = repo_root / name
        if should_ignore_path(path, ignored_roots):
            continue
        if path.is_file():
            paths.append(path)
    return paths


def numbered_text(path: Path, repo_root: Path, max_chars: int) -> str:
    text = read_text_file(path, max_chars)
    if text is None:
        return f"### {path.relative_to(repo_root)}\n[unreadable]\n"
    lines = text.splitlines()
    numbered = "\n".join(f"{idx:5d}: {line}" for idx, line in enumerate(lines, start=1))
    return f"### {path.relative_to(repo_root)}\n{numbered}\n"


def collect_git_context(
    repo_root: Path,
    max_diff_chars: int,
    max_context_chars: int,
    ignored_roots: list[Path],
) -> str:
    changed_paths = changed_file_paths(repo_root, ignored_roots)
    changed_names = relative_paths_for_git(changed_paths, repo_root)
    if changed_names:
        status_lines = []
        for entry_status, name in git_status_entries(repo_root):
            path = repo_root / name
            if should_ignore_path(path, ignored_roots):
                continue
            status_lines.append(f"{entry_status} {name}")
        status = "\n".join(status_lines)
        diff_stat = run_command(["git", "diff", "HEAD", "--stat", "--", *changed_names], repo_root)
        diff = run_command(
            ["git", "diff", "HEAD", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "--", *changed_names],
            repo_root,
        )
    else:
        status = ""
        diff_stat = ""
        diff = ""

    context_parts = []
    remaining = max_context_chars
    for path in changed_paths:
        if remaining <= 0:
            break
        part = numbered_text(path, repo_root, min(remaining, 40000))
        context_parts.append(part)
        remaining -= len(part)

    changed_context = truncate("\n".join(context_parts), max_context_chars) or "[empty]"
    return textwrap.dedent(
        f"""
        ## Git Status
        {status or "[clean]"}

        ## Git Diff Stat
        {diff_stat or "[empty]"}

        ## Git Diff
        {truncate(diff, max_diff_chars) or "[empty]"}

        ## Changed File Context
        {changed_context}
        """
    ).strip()


def run_codex(codex_command: str, repo_root: Path, prompt: str, timeout: int) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as tmp:
        output_path = Path(tmp.name)
    try:
        args = [
            codex_command,
            "--ask-for-approval",
            "never",
            "--sandbox",
            "danger-full-access",
            "exec",
            "--cd",
            str(repo_root),
            "--ignore-rules",
            "--color",
            "never",
            "--ephemeral",
            "--output-last-message",
            str(output_path),
            "-",
        ]
        completed = subprocess.run(
            args,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        final_message = read_text_file(output_path) or completed.stdout
        return completed.returncode, final_message.strip(), completed.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return 124, stdout.strip(), f"timeout after {timeout}s\n{stderr}".strip()
    except OSError as exc:
        return 127, "", str(exc)
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def build_rule_extraction_prompt(sources: list[RuleSource]) -> str:
    md_paths = [str(source.path) for source in sources if source.kind == "md_file"]
    skill_paths = [str(source.path) for source in sources if source.kind == "skill_dir"]
    return textwrap.dedent(
        f"""
        你是规范抽取器，只负责从本地规范源路径中读取内容并提取代码审查规则。

        本次只抽取“有效生产代码实现规范”：包括生产代码结构、函数/类设计、Java/其他语言编码、DB/JPA/SQL 使用、Redis/缓存/锁、RPC/HTTP/SDK/Web3/中间件访问边界等。
        完全不要抽取单测、测试代码、测试覆盖率、测试证据、测试执行方式、设计文档写作、发布材料、研发流程、proposal/openspec 流程、调度规则、沟通风格、归档步骤等非生产代码实现规范。
        如果规范源中存在“测试必须覆盖”“单测应验证”“Maven 测试证据”“测试代码质量”等要求，本次必须视为不适用并且不要输出。

        你必须自己读取下面列出的本地路径，不要要求调用方提供文件正文。

        Markdown 规范文件路径：
        {format_path_list(md_paths)}

        Skill 目录路径：
        {format_path_list(skill_paths)}

        读取规则：
        - 对 Markdown 规范文件路径，直接读取文件内容。
        - 对 Skill 目录路径，读取该目录下的 `SKILL.md` 以识别该 skill 的规范要求。
        - 对 Skill 目录中的其他文件，按理解规范所需自行决定是否读取。
        - 如果某个已给出的路径内部存在缺失或不可读文件，忽略该文件并继续处理其他可读内容。
        - 不要修改任何文件。

        要求：
        - 不要删除有效的生产代码实现规范内容。
        - 对非生产代码实现规范、单测规范、测试规范，直接不输出。
        - 不要合并导致语义丢失。
        - 一行只输出一条规范。
        - 每行必须是可用于代码审查的明确要求。
        - 不输出解释、标题、总结、Markdown 表格或代码块。
        - 如果某条规范只适用于特定语言、阶段或场景，也保留它，让后续审查用“忽略”判断不适用。

        只输出抽取后的规范行。
        """
    ).strip()


def format_path_list(paths: list[str]) -> str:
    if not paths:
        return "- 无"
    return "\n".join(f"- {path}" for path in paths)


def parse_rules(raw: str) -> list[str]:
    rules: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        rule = line.strip()
        if not rule:
            continue
        rule = re.sub(r"^[-*]\s+", "", rule)
        rule = re.sub(r"^\d+[.)]\s+", "", rule)
        rule = rule.strip()
        if not rule or rule in seen:
            continue
        seen.add(rule)
        rules.append(rule)
    return rules


def format_target_path_list(target_paths: list[TargetPath]) -> str:
    if not target_paths:
        return "- 无"
    return "\n".join(f"- {target.label} ({target.kind}): {target.path}" for target in target_paths)


def build_review_batch_prompt(
    rule_items: list[tuple[int, str]],
    git_context: str,
    ignored_labels: list[str],
    target_paths: list[TargetPath],
) -> str:
    rules_text = "\n".join(f"{index}. {rule}" for index, rule in rule_items)
    return textwrap.dedent(
        f"""
        你是只读代码规范审查器。不要修改文件，不要运行会改变工作区的命令。

        本次审查只关注有效生产代码实现问题，包括生产代码结构、函数/类设计、Java/其他语言编码、DB/JPA/SQL 使用、Redis/缓存/锁、RPC/HTTP/SDK/Web3/中间件访问边界等。
        不要审查单测、测试代码、测试覆盖率、测试证据、测试执行方式、设计文档、发布材料、研发流程、proposal/openspec 流程、调度规则、沟通风格或归档步骤。
        不得把 `src/test/`、`*Test.java`、`*Tests.java` 或其他单测文件作为阻塞证据；如果某条规范只能针对单测或测试证据判断，结论必须为“忽略”。

        以下仓库相对路径已配置为忽略范围；即使它们出现在 git 状态或上下文里，也不得作为阻塞证据：
        {format_path_list(ignored_labels)}

        本次额外指定的 target paths 如下：
        {format_target_path_list(target_paths)}

        target paths 读取规则：
        - 如果 target path 为目录，你必须按当前规范需要自行读取该目录下相关代码实现文件。
        - 如果 target path 为文件，你必须按当前规范需要自行读取该文件。
        - 不要要求调用方提供 target path 的文件正文。
        - 不要读取 ignored paths 范围内的文件。
        - target paths 只用于有效生产代码实现审查，不用于审查单测、测试代码、文档、发布材料、流程材料或 evidence。

        请检查当前未被忽略的 git 代码变更，以及 target paths 指定范围内的代码实现，是否遵守下面这组规范。每一条规范必须单独给出结论。

        规范列表：
        {rules_text}

        当前 git 变更和相关上下文：
        {git_context}

        对每条规范都必须严格输出一个独立块，格式如下：
        规则编号：<规范编号>
        规范：<原始规范>
        结论：通过|阻塞|忽略
        证据：<文件路径:行号 或 diff 依据；没有则写“无”>
        问题：<仅阻塞填写；否则写“无”>
        修改建议：<仅阻塞填写；否则写“无”>
        忽略原因：<仅忽略填写；否则写“无”>
        ---END---

        结论含义：
        - 通过：当前 git 变更符合该规范。
        - 阻塞：当前 git 变更违反该规范，必须给出文件、行号、问题和修改建议。
        - 忽略：该规范与当前 git 变更不相关，例如语言、模块、阶段或技术栈不适用。

        不要输出上述独立块之外的总结或解释。
        """
    ).strip()


def parse_batch_results(output: str, rule_items: list[tuple[int, str]]) -> list[ReviewResult]:
    parsed: dict[int, str] = {}
    matches = list(re.finditer(r"规则编号[:：]\s*(\d+)", output))
    for position, match in enumerate(matches):
        index = int(match.group(1))
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(output)
        block = output[start:end].strip()
        parsed[index] = block

    results: list[ReviewResult] = []
    for index, rule in rule_items:
        block = parsed.get(index, "")
        if not block:
            block = textwrap.dedent(
                f"""
                规则编号：{index}
                规范：{rule}
                结论：忽略
                证据：批量审查输出中缺少该规则结果
                问题：无
                修改建议：无
                忽略原因：该规则审查输出缺失，按容错策略忽略
                ---END---
                """
            ).strip()
        conclusion_match = re.search(r"结论[:：]\s*(通过|阻塞|忽略)", block)
        conclusion = conclusion_match.group(1) if conclusion_match else "忽略"
        results.append(ReviewResult(index=index, rule=rule, conclusion=conclusion, output=block, returncode=0, error=""))
    return results


def review_rule_batch(
    rule_items: list[tuple[int, str]],
    git_context: str,
    ignored_labels: list[str],
    target_paths: list[TargetPath],
    codex_command: str,
    repo_root: Path,
    timeout: int,
    record_codex_stderr: bool,
) -> list[ReviewResult]:
    returncode, output, stderr = run_codex(
        codex_command,
        repo_root,
        build_review_batch_prompt(rule_items, git_context, ignored_labels, target_paths),
        timeout,
    )
    if returncode != 0:
        if record_codex_stderr:
            error = stderr or output or f"Codex CLI returned {returncode}"
        else:
            error = f"Codex CLI returned {returncode}; stderr omitted by record_codex_stderr=false"
        return [
            ReviewResult(
                index=index,
                rule=rule,
                conclusion="忽略",
                output=textwrap.dedent(
                    f"""
                    规则编号：{index}
                    规范：{rule}
                    结论：忽略
                    证据：Codex batch review failed
                    问题：无
                    修改建议：无
                    忽略原因：批量审查任务执行失败，按容错策略忽略；Codex CLI returned {returncode}
                    ---END---
                    """
                ).strip(),
                returncode=returncode,
                error=error,
            )
            for index, rule in rule_items
        ]
    return parse_batch_results(output, rule_items)


def chunk_rule_items(rules: list[str], match_round: int) -> list[list[tuple[int, str]]]:
    items = list(enumerate(rules, start=1))
    if not items:
        return []
    batch_count = min(max(1, match_round), len(items))
    batch_size = (len(items) + batch_count - 1) // batch_count
    return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]


def append_evidence_header(
    evidence_path: Path,
    repo_root: Path,
    sources: list[RuleSource],
    ignored: list[str],
    extra_skills: list[str],
    raw_target_paths: list[str],
    target_paths: list[TargetPath],
    ignored_target_paths: list[str],
    ignored_review_paths: list[str],
    record_codex_stderr: bool,
) -> None:
    with evidence_path.open("a", encoding="utf-8") as fh:
        fh.write(f"# Code Compliance Review Evidence\n\n")
        fh.write(f"- generated_at: {datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"- repo_root: {repo_root}\n")
        fh.write(f"- extra_skills: {', '.join(extra_skills) if extra_skills else 'none'}\n\n")
        fh.write("## Review Scope\n\n")
        fh.write("- focus: code implementation only\n")
        fh.write(f"- record_codex_stderr: {str(record_codex_stderr).lower()}\n")
        fh.write("- ignored_paths:\n")
        for path in ignored_review_paths:
            fh.write(f"  - {path}\n")
        fh.write("- raw_target_paths:\n")
        if raw_target_paths:
            for path in raw_target_paths:
                fh.write(f"  - {path}\n")
        else:
            fh.write("  - none\n")
        fh.write("- effective_target_paths:\n")
        if target_paths:
            for target in target_paths:
                fh.write(f"  - {target.label} ({target.kind}): {target.path}\n")
        else:
            fh.write("  - none\n")
        if ignored_target_paths:
            fh.write("- ignored_target_paths:\n")
            for item in ignored_target_paths:
                fh.write(f"  - {item}\n")
        fh.write("\n")
        fh.write("## Rule Sources\n\n")
        for source in sources:
            fh.write(f"- {source.label}\n")
        if ignored:
            fh.write("\n## Ignored Sources\n\n")
            for item in ignored:
                fh.write(f"- {item}\n")
        fh.write("\n")


def append_rule_result(evidence_path: Path, result: ReviewResult) -> None:
    with evidence_path.open("a", encoding="utf-8") as fh:
        fh.write(f"## Rule {result.index}: {result.conclusion}\n\n")
        fh.write(result.output.strip() or "[empty codex output]")
        if result.error:
            fh.write("\n\nCodex stderr:\n\n")
            fh.write(result.error.strip())
        fh.write("\n\n")


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str]) -> int:
    skill_root = Path(__file__).resolve().parents[1]
    try:
        config = load_config(skill_root)
    except RuntimeError as exc:
        print_json({"status": "ERROR", "error": str(exc)})
        return 2

    if len(argv) < 2:
        print_json(
            {
                "status": "ERROR",
                "error": "usage: code_compliance_review.py <repo_root> [extra_skill_names_csv] [target_paths_csv]",
            }
        )
        return 2

    repo_root = Path(argv[1]).expanduser().resolve()
    if not repo_root.is_dir():
        print_json({"status": "ERROR", "error": f"repo_root is not a directory: {repo_root}"})
        return 2

    extra_skills = split_skill_names(argv[2] if len(argv) >= 3 else None)
    raw_target_paths = split_csv_values(argv[3] if len(argv) >= 4 else None)
    default_md_files = list(config.get("default_md_files", []))
    default_skills = list(config.get("default_skills", []))
    skills_root = str(config.get("skills_root", ".codex/skills"))
    evidence_dir_name = str(config.get("evidence_dir", "review_evidences"))
    evidence_dir = repo_root / evidence_dir_name
    ignored_review_paths = [str(item) for item in list(config.get("ignored_paths", []))]
    ignored_roots = resolve_ignored_roots(repo_root, ignored_review_paths, evidence_dir_name)
    ignored_review_labels = sorted(
        {
            normalize_relative_path(path)
            for path in [*ignored_review_paths, evidence_dir_name]
            if normalize_relative_path(str(path))
        }
    )
    concurrency = max(1, int(config.get("concurrency", 5)))
    match_round = max(1, int(config.get("match_round", 10)))
    max_diff_chars = int(config.get("max_diff_chars", 120000))
    max_context_chars = int(config.get("max_context_chars", 120000))
    codex_command = str(config.get("codex_command", "codex"))
    codex_timeout = int(config.get("codex_timeout_seconds", 1200))
    record_codex_stderr = config_bool(config, "record_codex_stderr", False)

    ignored: list[str] = []
    sources: list[RuleSource] = []
    for relative_path in default_md_files:
        source = collect_md_source(repo_root, str(relative_path), ignored)
        if source:
            sources.append(source)
    for skill_name in [*default_skills, *extra_skills]:
        sources.extend(collect_skill_sources(repo_root, skills_root, str(skill_name), ignored))
    sources = dedupe_sources(sources)
    target_paths, ignored_target_paths = collect_target_paths(repo_root, raw_target_paths, ignored_roots)

    evidence_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_path = (evidence_dir / f"{timestamp}_code_compliance_review.md").resolve()
    append_evidence_header(
        evidence_path,
        repo_root,
        sources,
        ignored,
        extra_skills,
        raw_target_paths,
        target_paths,
        ignored_target_paths,
        ignored_review_labels,
        record_codex_stderr,
    )

    if not sources:
        with evidence_path.open("a", encoding="utf-8") as fh:
            fh.write("## Result\n\nNo usable rule sources were found.\n")
        print_json(
            {
                "status": "NO_RULES",
                "total": 0,
                "passed": 0,
                "blocked": 0,
                "ignored": 0,
                "evidence": str(evidence_path),
                "target_paths": [target.label for target in target_paths],
            }
        )
        return 0

    returncode, raw_rules, stderr = run_codex(
        codex_command,
        repo_root,
        build_rule_extraction_prompt(sources),
        codex_timeout,
    )
    if returncode != 0:
        with evidence_path.open("a", encoding="utf-8") as fh:
            fh.write("## Rule Extraction Failed\n\n")
            fh.write(f"- returncode: {returncode}\n")
            if raw_rules:
                fh.write("\n### final_message\n\n")
                fh.write(raw_rules)
            if record_codex_stderr and stderr:
                fh.write("\n\n### stderr\n\n")
                fh.write(stderr)
            elif stderr:
                fh.write("\n\n### stderr\n\n")
                fh.write("[omitted because record_codex_stderr=false]\n")
            fh.write("\n")
        print_json(
            {
                "status": "ERROR",
                "error": "Codex rule extraction failed",
                "evidence": str(evidence_path),
                "target_paths": [target.label for target in target_paths],
            }
        )
        return 1

    rules = parse_rules(raw_rules)
    with evidence_path.open("a", encoding="utf-8") as fh:
        fh.write("## Extracted Rules\n\n")
        for index, rule in enumerate(rules, start=1):
            fh.write(f"{index}. {rule}\n")
        fh.write("\n")

    if not rules:
        with evidence_path.open("a", encoding="utf-8") as fh:
            fh.write("## Result\n\nNo rule lines were extracted.\n")
        print_json(
            {
                "status": "NO_RULES",
                "total": 0,
                "passed": 0,
                "blocked": 0,
                "ignored": 0,
                "evidence": str(evidence_path),
                "target_paths": [target.label for target in target_paths],
            }
        )
        return 0

    git_context = collect_git_context(repo_root, max_diff_chars, max_context_chars, ignored_roots)
    rule_batches = chunk_rule_items(rules, match_round)

    counts = {"passed": 0, "blocked": 0, "ignored": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_batch = {
            executor.submit(
                review_rule_batch,
                batch,
                git_context,
                ignored_review_labels,
                target_paths,
                codex_command,
                repo_root,
                codex_timeout,
                record_codex_stderr,
            ): batch
            for batch in rule_batches
        }
        for future in concurrent.futures.as_completed(future_to_batch):
            try:
                results = future.result()
            except Exception as exc:  # pragma: no cover - defensive guard for worker failures.
                results = [
                    ReviewResult(
                        index=index,
                        rule=rule,
                        conclusion="忽略",
                        output=textwrap.dedent(
                            f"""
                            规则编号：{index}
                            规范：{rule}
                            结论：忽略
                            证据：worker exception
                            问题：无
                            修改建议：无
                            忽略原因：批量审查 worker 异常，按容错策略忽略；{exc}
                            ---END---
                            """
                        ).strip(),
                        returncode=1,
                        error=str(exc),
                    )
                    for index, rule in future_to_batch[future]
                ]

            for result in sorted(results, key=lambda item: item.index):
                if result.conclusion == "通过":
                    counts["passed"] += 1
                elif result.conclusion == "阻塞":
                    counts["blocked"] += 1
                else:
                    counts["ignored"] += 1
                append_rule_result(evidence_path, result)

    status = "BLOCKED" if counts["blocked"] else "PASSED"
    with evidence_path.open("a", encoding="utf-8") as fh:
        fh.write("## Summary\n\n")
        fh.write(f"- status: {status}\n")
        fh.write(f"- total: {len(rules)}\n")
        fh.write(f"- passed: {counts['passed']}\n")
        fh.write(f"- blocked: {counts['blocked']}\n")
        fh.write(f"- ignored: {counts['ignored']}\n")

    print_json(
        {
            "status": status,
            "total": len(rules),
            "passed": counts["passed"],
            "blocked": counts["blocked"],
            "ignored": counts["ignored"],
            "evidence": str(evidence_path),
            "ignored_paths": ignored_review_labels,
            "target_paths": [target.label for target in target_paths],
            "ignored_target_paths": ignored_target_paths,
            "record_codex_stderr": record_codex_stderr,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
