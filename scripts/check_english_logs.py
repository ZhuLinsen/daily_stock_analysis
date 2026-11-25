#!/usr/bin/env python3
"""Check that runtime Python logger calls do not contain CJK characters."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable, Iterator, List, Sequence

DEFAULT_TARGETS: tuple[str, ...] = (
    "main.py",
    "server.py",
    "src",
    "data_provider",
    "api",
    "bot",
)

IGNORED_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
    }
)

LOG_METHODS: frozenset[str] = frozenset(
    {
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "fatal",
        "log",
    }
)

CONTAINER_MUTATE_METHODS: frozenset[str] = frozenset({"append", "extend", "add", "update"})

NON_TEXT_BUILTIN_CALLS: frozenset[str] = frozenset(
    {"len", "bool", "isinstance", "issubclass", "hasattr", "callable"}
)

DEFAULT_CJK_ENUM_CLASSES: frozenset[str] = frozenset(
    {
        "TrendStatus",
        "VolumeStatus",
        "BuySignal",
        "MACDStatus",
        "RSIStatus",
    }
)

DEFAULT_CJK_ENUM_ATTRS: frozenset[str] = frozenset(
    {
        "trend_status",
        "volume_status",
        "buy_signal",
        "macd_status",
        "rsi_status",
    }
)

CJK_RE = re.compile(
    "["
    "\u1100-\u11ff"          # Hangul Jamo
    "\u2e80-\u2fdf"          # CJK Radicals Supplement & Kangxi Radicals
    "\u3000-\u303f"          # CJK Symbols and Punctuation
    "\u3040-\u309f"          # Hiragana
    "\u30a0-\u30ff"          # Katakana
    "\u3100-\u31ff"          # Bopomofo, Hangul Compat Jamo, Kanbun, CJK Strokes, Katakana Ext
    "\u3200-\u33ff"          # Enclosed CJK & CJK Compatibility
    "\u3400-\u4dbf"          # CJK Unified Ideographs Extension A
    "\u4e00-\u9fff"          # CJK Unified Ideographs
    "\ua960-\ua97f"          # Hangul Jamo Extended-A
    "\uac00-\ud7ff"          # Hangul Syllables & Hangul Jamo Extended-B
    "\uf900-\ufaff"          # CJK Compatibility Ideographs
    "\ufe30-\ufe4f"          # CJK Compatibility Forms
    "\uff00-\uffef"          # Halfwidth and Fullwidth Forms
    "\U00020000-\U0002ebef"  # CJK Unified Ideographs Extensions B-F (incl. 𠮷 U+20BB7)
    "\U0002f800-\U0002fa1f"  # CJK Compatibility Ideographs Supplement
    "\U00030000-\U000323af"  # CJK Unified Ideographs Extensions G-H
    "]"
)


@dataclass(frozen=True)
class LogViolation:
    """Represents a runtime logger call containing CJK text."""

    path: Path
    line: int
    method: str
    snippet: str


def _is_logger_call(node: ast.Call) -> bool:
    """Return True when an AST Call invokes a logger/logging output method."""
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in LOG_METHODS:
        return False
    try:
        caller = ast.unparse(node.func.value).lower()
    except Exception:
        return False
    return "log" in caller


def _iter_log_string_constants(node: ast.AST) -> Iterator[ast.Constant]:
    """Yield string constants while skipping subscripts, ``get`` keys, and membership checks."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            yield node
        return

    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Dict):
            for val in node.value.values:
                yield from _iter_log_string_constants(val)
        else:
            yield from _iter_log_string_constants(node.value)
        return

    if isinstance(node, ast.Compare) and node.ops and all(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        if isinstance(node.func.value, ast.Dict):
            for val in node.func.value.values:
                yield from _iter_log_string_constants(val)
        else:
            yield from _iter_log_string_constants(node.func.value)
        for arg in node.args[1:]:
            yield from _iter_log_string_constants(arg)
        for kw in node.keywords:
            if kw.arg != "key":
                yield from _iter_log_string_constants(kw.value)
        return

    for child in ast.iter_child_nodes(node):
        yield from _iter_log_string_constants(child)


def _annotation_names(node: ast.AST | None) -> Iterator[str]:
    """Yield type identifier names referenced in an annotation AST."""
    if node is None:
        return
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, ast.Attribute):
        yield node.attr
    else:
        for child in ast.iter_child_nodes(node):
            yield from _annotation_names(child)


def _collect_cjk_enum_info(
    trees: Sequence[ast.AST],
) -> tuple[frozenset[str], frozenset[str]]:
    """Collect Enum classes whose member values contain CJK text and their typed attributes."""
    enum_classes: set[str] = set(DEFAULT_CJK_ENUM_CLASSES)
    enum_attrs: set[str] = set(DEFAULT_CJK_ENUM_ATTRS)

    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = set()
            for base in node.bases:
                base_names.update(_annotation_names(base))
            if not (base_names & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}):
                continue
            has_cjk_member = False
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                    if isinstance(stmt.value.value, str) and CJK_RE.search(stmt.value.value):
                        has_cjk_member = True
                        break
            if has_cjk_member:
                enum_classes.add(node.name)

    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if set(_annotation_names(node.annotation)) & enum_classes:
                    enum_attrs.add(node.target.id)
            elif isinstance(node, ast.arg) and node.annotation is not None:
                if set(_annotation_names(node.annotation)) & enum_classes:
                    enum_attrs.add(node.arg)

    return frozenset(enum_classes), frozenset(enum_attrs)


def _cjk_from_string_expr(
    expr: ast.AST,
    env: dict[str, str],
    dict_env: dict[str, dict[str, str]],
    *,
    attr_env: dict[str, str] | None = None,
    cjk_enum_classes: frozenset[str] = DEFAULT_CJK_ENUM_CLASSES,
    cjk_enum_attrs: frozenset[str] = DEFAULT_CJK_ENUM_ATTRS,
) -> List[str]:
    """Collect static or locally propagated CJK text fragments produced by *expr*."""
    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, str) and CJK_RE.search(expr.value):
            return [expr.value.strip().replace("\n", "\\n")]
        return []
    if isinstance(expr, ast.Name):
        return [env[expr.id]] if expr.id in env else []
    if isinstance(expr, ast.Attribute):
        if expr.attr == "value":
            inner = expr.value
            if isinstance(inner, ast.Attribute):
                if inner.attr in cjk_enum_attrs or (
                    isinstance(inner.value, ast.Name) and inner.value.id in cjk_enum_classes
                ):
                    return [f"{ast.unparse(expr)} (CJK Enum value)"]
            elif isinstance(inner, ast.Name) and (
                inner.id in cjk_enum_attrs or inner.id in cjk_enum_classes
            ):
                return [f"{ast.unparse(expr)} (CJK Enum value)"]
        if attr_env and expr.attr in attr_env:
            return [attr_env[expr.attr]]
        return []
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        hits: List[str] = []
        for elt in expr.elts:
            hits.extend(
                _cjk_from_string_expr(
                    elt,
                    env,
                    dict_env,
                    attr_env=attr_env,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            )
        return hits
    if isinstance(expr, ast.Compare) and expr.ops and all(isinstance(op, (ast.In, ast.NotIn)) for op in expr.ops):
        return []
    if isinstance(expr, ast.Subscript):
        if isinstance(expr.value, ast.Name) and expr.value.id in dict_env:
            if isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str):
                val = dict_env[expr.value.id].get(expr.slice.value)
                return [val] if val else []
            return list(dict_env[expr.value.id].values())[:1]
        if isinstance(expr.value, ast.Dict):
            hits = []
            for val in expr.value.values:
                hits.extend(
                    _cjk_from_string_expr(
                        val,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                )
            return hits
        return _cjk_from_string_expr(
            expr.value,
            env,
            dict_env,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        )
    if isinstance(expr, ast.JoinedStr):
        hits = []
        for part in expr.values:
            inner = part.value if isinstance(part, ast.FormattedValue) else part
            hits.extend(
                _cjk_from_string_expr(
                    inner,
                    env,
                    dict_env,
                    attr_env=attr_env,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            )
        return hits
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Mod)):
        return _cjk_from_string_expr(
            expr.left,
            env,
            dict_env,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        ) + _cjk_from_string_expr(
            expr.right,
            env,
            dict_env,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        )
    if isinstance(expr, ast.BoolOp):
        hits = []
        for val in expr.values:
            hits.extend(
                _cjk_from_string_expr(
                    val,
                    env,
                    dict_env,
                    attr_env=attr_env,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            )
        return hits
    if isinstance(expr, ast.IfExp):
        return _cjk_from_string_expr(
            expr.body,
            env,
            dict_env,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        ) + _cjk_from_string_expr(
            expr.orelse,
            env,
            dict_env,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        )
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
        if expr.func.attr == "get":
            hits = []
            if isinstance(expr.func.value, ast.Dict):
                for val in expr.func.value.values:
                    hits.extend(
                        _cjk_from_string_expr(
                            val,
                            env,
                            dict_env,
                            attr_env=attr_env,
                            cjk_enum_classes=cjk_enum_classes,
                            cjk_enum_attrs=cjk_enum_attrs,
                        )
                    )
            elif isinstance(expr.func.value, ast.Name) and expr.func.value.id in dict_env:
                if expr.args and isinstance(expr.args[0], ast.Constant) and isinstance(expr.args[0].value, str):
                    val = dict_env[expr.func.value.id].get(expr.args[0].value)
                    if val:
                        hits.append(val)
                else:
                    hits.extend(list(dict_env[expr.func.value.id].values())[:1])
            else:
                hits.extend(
                    _cjk_from_string_expr(
                        expr.func.value,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                )
            for arg in expr.args[1:]:
                hits.extend(
                    _cjk_from_string_expr(
                        arg,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                )
            for kw in expr.keywords:
                if kw.arg != "key":
                    hits.extend(
                        _cjk_from_string_expr(
                            kw.value,
                            env,
                            dict_env,
                            attr_env=attr_env,
                            cjk_enum_classes=cjk_enum_classes,
                            cjk_enum_attrs=cjk_enum_attrs,
                        )
                    )
            return hits
        if expr.func.attr in {"format", "join"}:
            hits = _cjk_from_string_expr(
                expr.func.value,
                env,
                dict_env,
                attr_env=attr_env,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            for arg in expr.args:
                hits.extend(
                    _cjk_from_string_expr(
                        arg,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                )
            for kw in expr.keywords:
                hits.extend(
                    _cjk_from_string_expr(
                        kw.value,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                )
            return hits
        if expr.func.attr in {"strip", "lstrip", "rstrip", "lower", "upper", "replace"}:
            hits = _cjk_from_string_expr(
                expr.func.value,
                env,
                dict_env,
                attr_env=attr_env,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            if expr.func.attr == "replace" and len(expr.args) >= 2:
                hits.extend(
                    _cjk_from_string_expr(
                        expr.args[1],
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                )
            return hits
    return []


def _extract_dict_cjk(
    node: ast.Dict,
    env: dict[str, str],
    dict_env: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Extract CJK values (ignoring dict keys) from a dict literal."""
    res: dict[str, str] = {}
    for key, val in zip(node.keys, node.values):
        if key is None or val is None:
            continue
        hits = _cjk_from_string_expr(val, env, dict_env)
        if hits:
            key_name = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "*"
            res[key_name] = hits[0]
    return res


def _merge_env(e1: dict[str, str], e2: dict[str, str]) -> dict[str, str]:
    merged = dict(e1)
    for k, v in e2.items():
        merged.setdefault(k, v)
    return merged


def _merge_dict_env(
    d1: dict[str, dict[str, str]],
    d2: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    merged = {k: dict(v) for k, v in d1.items()}
    for k, v in d2.items():
        if k not in merged:
            merged[k] = dict(v)
        else:
            for mk, mv in v.items():
                merged[k].setdefault(mk, mv)
    return merged


def _cjk_in_log_expr(
    expr: ast.AST,
    env: dict[str, str],
    dict_env: dict[str, dict[str, str]],
    *,
    attr_env: dict[str, str] | None = None,
    cjk_enum_classes: frozenset[str] = DEFAULT_CJK_ENUM_CLASSES,
    cjk_enum_attrs: frozenset[str] = DEFAULT_CJK_ENUM_ATTRS,
) -> List[str]:
    """Return CJK snippets found directly or via propagated bindings in a log argument."""
    snippets: List[str] = []
    for const in _iter_log_string_constants(expr):
        if isinstance(const.value, str) and CJK_RE.search(const.value):
            snippets.append(const.value.strip().replace("\n", "\\n"))

    def _walk_refs(node: ast.AST) -> None:
        if isinstance(node, ast.Compare) and node.ops and all(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            return
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id in dict_env:
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    val = dict_env[node.value.id].get(node.slice.value)
                    if val:
                        snippets.append(val)
                else:
                    snippets.extend(list(dict_env[node.value.id].values())[:1])
                return
            _walk_refs(node.value)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in NON_TEXT_BUILTIN_CALLS:
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            if isinstance(node.func.value, ast.Name) and node.func.value.id in dict_env:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    val = dict_env[node.func.value.id].get(node.args[0].value)
                    if val:
                        snippets.append(val)
                else:
                    snippets.extend(list(dict_env[node.func.value.id].values())[:1])
            else:
                _walk_refs(node.func.value)
            for arg in node.args[1:]:
                _walk_refs(arg)
            for kw in node.keywords:
                if kw.arg != "key":
                    _walk_refs(kw.value)
            return
        if isinstance(node, ast.Attribute):
            if node.attr == "value":
                inner = node.value
                if isinstance(inner, ast.Attribute) and (
                    inner.attr in cjk_enum_attrs
                    or (isinstance(inner.value, ast.Name) and inner.value.id in cjk_enum_classes)
                ):
                    snippets.append(f"{ast.unparse(node)} (CJK Enum value)")
                    return
                if isinstance(inner, ast.Name) and (
                    inner.id in cjk_enum_attrs or inner.id in cjk_enum_classes
                ):
                    snippets.append(f"{ast.unparse(node)} (CJK Enum value)")
                    return
            if attr_env and node.attr in attr_env:
                snippets.append(attr_env[node.attr])
                return
            _walk_refs(node.value)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in env:
            snippets.append(env[node.id])
            return
        for child in ast.iter_child_nodes(node):
            _walk_refs(child)

    _walk_refs(expr)
    return snippets


def _extract_nested_mutators(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[list[str], str]]:
    """Detect simple helper functions that append/extend a parameter into an outer container."""
    param_names = [a.arg for a in list(fn_node.args.posonlyargs) + list(fn_node.args.args)]
    if not param_names:
        return []
    targets: list[tuple[list[str], str]] = []
    for sub in ast.walk(fn_node):
        if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
            continue
        if sub.func.attr not in CONTAINER_MUTATE_METHODS or not isinstance(sub.func.value, ast.Name):
            continue
        container = sub.func.value.id
        if container in param_names:
            continue
        for arg in sub.args:
            if isinstance(arg, ast.Name) and arg.id in param_names:
                targets.append((param_names, container))
                break
    return targets


def _record_taint_from_calls(
    node: ast.AST,
    env: dict[str, str],
    dict_env: dict[str, dict[str, str]],
    attr_env: dict[str, str],
    container_vars: set[str],
    container_attr_env: dict[str, str],
    mutator_env: dict[str, list[tuple[list[str], str]]],
    cjk_enum_classes: frozenset[str],
    cjk_enum_attrs: frozenset[str],
) -> None:
    """Propagate CJK taint through container append/extend, helper mutators, and container fields."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr in CONTAINER_MUTATE_METHODS:
            if isinstance(node.func.value, ast.Name):
                container = node.func.value.id
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    hits = _cjk_from_string_expr(
                        arg,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                    if hits:
                        env.setdefault(container, hits[0])
                        container_vars.add(container)
                        break
        if isinstance(node.func, ast.Name) and node.func.id in mutator_env:
            for _params, container in mutator_env[node.func.id]:
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    hits = _cjk_from_string_expr(
                        arg,
                        env,
                        dict_env,
                        attr_env=attr_env,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
                    if hits:
                        env.setdefault(container, hits[0])
                        container_vars.add(container)
                        break
        for kw in node.keywords:
            if kw.arg and isinstance(kw.value, ast.Name) and kw.value.id in container_vars and kw.value.id in env:
                container_attr_env.setdefault(kw.arg, env[kw.value.id])
    for child in ast.iter_child_nodes(node):
        _record_taint_from_calls(
            child,
            env,
            dict_env,
            attr_env,
            container_vars,
            container_attr_env,
            mutator_env,
            cjk_enum_classes,
            cjk_enum_attrs,
        )


def _bind_target(
    target: ast.AST,
    value: ast.AST,
    env: dict[str, str],
    dict_env: dict[str, dict[str, str]],
    *,
    attr_env: dict[str, str] | None = None,
    cjk_enum_classes: frozenset[str] = DEFAULT_CJK_ENUM_CLASSES,
    cjk_enum_attrs: frozenset[str] = DEFAULT_CJK_ENUM_ATTRS,
) -> None:
    """Update *env* / *dict_env* / *attr_env* for an assignment target and RHS expression."""
    if isinstance(target, ast.Attribute):
        if attr_env is not None:
            hits = _cjk_from_string_expr(
                value,
                env,
                dict_env,
                attr_env=attr_env,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            if hits:
                attr_env.setdefault(target.attr, hits[0])
        return

    if isinstance(target, ast.Name):
        dict_hits = _extract_dict_cjk(value, env, dict_env) if isinstance(value, ast.Dict) else {}
        str_hits = _cjk_from_string_expr(
            value,
            env,
            dict_env,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        )
        if str_hits:
            env[target.id] = str_hits[0]
            dict_env.pop(target.id, None)
        elif dict_hits:
            dict_env[target.id] = dict_hits
            env.pop(target.id, None)
        else:
            env.pop(target.id, None)
            dict_env.pop(target.id, None)
        return

    if isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
            for sub_tgt, sub_val in zip(target.elts, value.elts):
                _bind_target(
                    sub_tgt,
                    sub_val,
                    env,
                    dict_env,
                    attr_env=attr_env,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            return
        for sub_tgt in target.elts:
            if isinstance(sub_tgt, ast.Name):
                env.pop(sub_tgt.id, None)
                dict_env.pop(sub_tgt.id, None)


def _unbind_target(target: ast.AST, env: dict[str, str], dict_env: dict[str, dict[str, str]]) -> None:
    if isinstance(target, ast.Name):
        env.pop(target.id, None)
        dict_env.pop(target.id, None)
    elif isinstance(target, (ast.Tuple, ast.List, ast.Starred)):
        children = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target.value]
        for child in children:
            _unbind_target(child, env, dict_env)


def _scan_expr_calls(
    node: ast.AST,
    env: dict[str, str],
    dict_env: dict[str, dict[str, str]],
    path: Path,
    violations: List[LogViolation],
    seen: set[tuple[int, str]],
    *,
    attr_env: dict[str, str] | None = None,
    cjk_enum_classes: frozenset[str] = DEFAULT_CJK_ENUM_CLASSES,
    cjk_enum_attrs: frozenset[str] = DEFAULT_CJK_ENUM_ATTRS,
    descend_scopes: bool = False,
) -> None:
    """Inspect logger calls inside non-statement expressions (or nested functions if queued)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not descend_scopes:
        return
    if isinstance(node, ast.Call) and _is_logger_call(node):
        exprs: List[ast.AST] = list(node.args) + [kw.value for kw in node.keywords]
        matched_snippets: List[str] = []
        for expr in exprs:
            for snippet in _cjk_in_log_expr(
                expr,
                env,
                dict_env,
                attr_env=attr_env,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            ):
                if snippet not in matched_snippets:
                    matched_snippets.append(snippet)
        if matched_snippets:
            key = (node.lineno, node.func.attr)
            if key not in seen:
                seen.add(key)
                joined = " | ".join(matched_snippets)
                if len(joined) > 120:
                    joined = joined[:117] + "..."
                violations.append(
                    LogViolation(
                        path=path,
                        line=node.lineno,
                        method=node.func.attr,
                        snippet=joined,
                    )
                )
    for child in ast.iter_child_nodes(node):
        _scan_expr_calls(
            child,
            env,
            dict_env,
            path,
            violations,
            seen,
            attr_env=attr_env,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
            descend_scopes=descend_scopes,
        )


def _scan_statements(
    stmts: Sequence[ast.stmt],
    init_env: dict[str, str],
    init_dict_env: dict[str, dict[str, str]],
    path: Path,
    violations: List[LogViolation],
    seen: set[tuple[int, str]],
    *,
    attr_env: dict[str, str] | None = None,
    container_vars: set[str] | None = None,
    container_attr_env: dict[str, str] | None = None,
    mutator_env: dict[str, list[tuple[list[str], str]]] | None = None,
    cjk_enum_classes: frozenset[str] = DEFAULT_CJK_ENUM_CLASSES,
    cjk_enum_attrs: frozenset[str] = DEFAULT_CJK_ENUM_ATTRS,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Flow-sensitively scan statements and propagate local/container/attribute CJK bindings."""
    env = dict(init_env)
    dict_env = {k: dict(v) for k, v in init_dict_env.items()}
    if attr_env is None:
        attr_env = {}
    if container_vars is None:
        container_vars = set()
    if container_attr_env is None:
        container_attr_env = {}
    local_mutators = dict(mutator_env or {})

    def _effective_attr_env() -> dict[str, str]:
        if not container_attr_env:
            return attr_env
        if not attr_env:
            return container_attr_env
        merged = dict(container_attr_env)
        merged.update(attr_env)
        return merged

    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            muts = _extract_nested_mutators(stmt)
            if muts:
                local_mutators[stmt.name] = muts
            fn_env = dict(env)
            fn_dict_env = {k: dict(v) for k, v in dict_env.items()}
            for arg in list(stmt.args.posonlyargs) + list(stmt.args.args) + list(stmt.args.kwonlyargs):
                fn_env.pop(arg.arg, None)
                fn_dict_env.pop(arg.arg, None)
            if stmt.args.vararg:
                fn_env.pop(stmt.args.vararg.arg, None)
                fn_dict_env.pop(stmt.args.vararg.arg, None)
            if stmt.args.kwarg:
                fn_env.pop(stmt.args.kwarg.arg, None)
                fn_dict_env.pop(stmt.args.kwarg.arg, None)
            _scan_statements(
                stmt.body,
                fn_env,
                fn_dict_env,
                path,
                violations,
                seen,
                attr_env={},
                container_vars=set(container_vars),
                container_attr_env=container_attr_env,
                mutator_env=local_mutators,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            continue

        if isinstance(stmt, ast.ClassDef):
            for child in stmt.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    _scan_statements(
                        [child],
                        env,
                        dict_env,
                        path,
                        violations,
                        seen,
                        attr_env={},
                        container_vars=set(container_vars),
                        container_attr_env=container_attr_env,
                        mutator_env=local_mutators,
                        cjk_enum_classes=cjk_enum_classes,
                        cjk_enum_attrs=cjk_enum_attrs,
                    )
            continue

        eff_attrs = _effective_attr_env()

        if isinstance(stmt, ast.Assign):
            _record_taint_from_calls(
                stmt.value,
                env,
                dict_env,
                eff_attrs,
                container_vars,
                container_attr_env,
                local_mutators,
                cjk_enum_classes,
                cjk_enum_attrs,
            )
            _scan_expr_calls(
                stmt.value,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=eff_attrs,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            for tgt in stmt.targets:
                _bind_target(
                    tgt,
                    stmt.value,
                    env,
                    dict_env,
                    attr_env=attr_env,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            continue

        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                _record_taint_from_calls(
                    stmt.value,
                    env,
                    dict_env,
                    eff_attrs,
                    container_vars,
                    container_attr_env,
                    local_mutators,
                    cjk_enum_classes,
                    cjk_enum_attrs,
                )
                _scan_expr_calls(
                    stmt.value,
                    env,
                    dict_env,
                    path,
                    violations,
                    seen,
                    attr_env=eff_attrs,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                _bind_target(
                    stmt.target,
                    stmt.value,
                    env,
                    dict_env,
                    attr_env=attr_env,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            continue

        if isinstance(stmt, ast.AugAssign):
            _record_taint_from_calls(
                stmt.value,
                env,
                dict_env,
                eff_attrs,
                container_vars,
                container_attr_env,
                local_mutators,
                cjk_enum_classes,
                cjk_enum_attrs,
            )
            _scan_expr_calls(
                stmt.value,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=eff_attrs,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            if isinstance(stmt.target, ast.Name):
                str_hits = _cjk_from_string_expr(
                    stmt.value,
                    env,
                    dict_env,
                    attr_env=eff_attrs,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                if str_hits:
                    env[stmt.target.id] = str_hits[0]
                    dict_env.pop(stmt.target.id, None)
            continue

        if isinstance(stmt, ast.If):
            _scan_expr_calls(
                stmt.test,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=eff_attrs,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            e_body, d_body = _scan_statements(
                stmt.body,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=attr_env,
                container_vars=container_vars,
                container_attr_env=container_attr_env,
                mutator_env=local_mutators,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            e_else, d_else = (
                _scan_statements(
                    stmt.orelse,
                    env,
                    dict_env,
                    path,
                    violations,
                    seen,
                    attr_env=attr_env,
                    container_vars=container_vars,
                    container_attr_env=container_attr_env,
                    mutator_env=local_mutators,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                if stmt.orelse
                else (env, dict_env)
            )
            env = _merge_env(e_body, e_else)
            dict_env = _merge_dict_env(d_body, d_else)
            continue

        if isinstance(stmt, ast.Try):
            e_try, d_try = _scan_statements(
                stmt.body,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=attr_env,
                container_vars=container_vars,
                container_attr_env=container_attr_env,
                mutator_env=local_mutators,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            e_norm, d_norm = (
                _scan_statements(
                    stmt.orelse,
                    e_try,
                    d_try,
                    path,
                    violations,
                    seen,
                    attr_env=attr_env,
                    container_vars=container_vars,
                    container_attr_env=container_attr_env,
                    mutator_env=local_mutators,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                if stmt.orelse
                else (e_try, d_try)
            )
            e_join, d_join = dict(e_norm), {k: dict(v) for k, v in d_norm.items()}
            e_pre_h, d_pre_h = _merge_env(env, e_try), _merge_dict_env(dict_env, d_try)
            for handler in stmt.handlers:
                eh_in = dict(e_pre_h)
                dh_in = {k: dict(v) for k, v in d_pre_h.items()}
                if handler.name:
                    eh_in.pop(handler.name, None)
                    dh_in.pop(handler.name, None)
                eh, dh = _scan_statements(
                    handler.body,
                    eh_in,
                    dh_in,
                    path,
                    violations,
                    seen,
                    attr_env=attr_env,
                    container_vars=container_vars,
                    container_attr_env=container_attr_env,
                    mutator_env=local_mutators,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                e_join = _merge_env(e_join, eh)
                d_join = _merge_dict_env(d_join, dh)
            if stmt.finalbody:
                env, dict_env = _scan_statements(
                    stmt.finalbody,
                    e_join,
                    d_join,
                    path,
                    violations,
                    seen,
                    attr_env=attr_env,
                    container_vars=container_vars,
                    container_attr_env=container_attr_env,
                    mutator_env=local_mutators,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
            else:
                env, dict_env = e_join, d_join
            continue

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            _scan_expr_calls(
                stmt.iter,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=eff_attrs,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            e_loop, d_loop = dict(env), {k: dict(v) for k, v in dict_env.items()}
            _unbind_target(stmt.target, e_loop, d_loop)
            e_body, d_body = _scan_statements(
                stmt.body,
                e_loop,
                d_loop,
                path,
                violations,
                seen,
                attr_env=attr_env,
                container_vars=container_vars,
                container_attr_env=container_attr_env,
                mutator_env=local_mutators,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            env = _merge_env(env, e_body)
            dict_env = _merge_dict_env(dict_env, d_body)
            if stmt.orelse:
                e_else, d_else = _scan_statements(
                    stmt.orelse,
                    env,
                    dict_env,
                    path,
                    violations,
                    seen,
                    attr_env=attr_env,
                    container_vars=container_vars,
                    container_attr_env=container_attr_env,
                    mutator_env=local_mutators,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                env = _merge_env(env, e_else)
                dict_env = _merge_dict_env(dict_env, d_else)
            continue

        if isinstance(stmt, ast.While):
            _scan_expr_calls(
                stmt.test,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=eff_attrs,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            e_body, d_body = _scan_statements(
                stmt.body,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=attr_env,
                container_vars=container_vars,
                container_attr_env=container_attr_env,
                mutator_env=local_mutators,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            env = _merge_env(env, e_body)
            dict_env = _merge_dict_env(dict_env, d_body)
            if stmt.orelse:
                e_else, d_else = _scan_statements(
                    stmt.orelse,
                    env,
                    dict_env,
                    path,
                    violations,
                    seen,
                    attr_env=attr_env,
                    container_vars=container_vars,
                    container_attr_env=container_attr_env,
                    mutator_env=local_mutators,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                env = _merge_env(env, e_else)
                dict_env = _merge_dict_env(dict_env, d_else)
            continue

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                _scan_expr_calls(
                    item.context_expr,
                    env,
                    dict_env,
                    path,
                    violations,
                    seen,
                    attr_env=eff_attrs,
                    cjk_enum_classes=cjk_enum_classes,
                    cjk_enum_attrs=cjk_enum_attrs,
                )
                if item.optional_vars is not None:
                    _unbind_target(item.optional_vars, env, dict_env)
            env, dict_env = _scan_statements(
                stmt.body,
                env,
                dict_env,
                path,
                violations,
                seen,
                attr_env=attr_env,
                container_vars=container_vars,
                container_attr_env=container_attr_env,
                mutator_env=local_mutators,
                cjk_enum_classes=cjk_enum_classes,
                cjk_enum_attrs=cjk_enum_attrs,
            )
            continue

        _record_taint_from_calls(
            stmt,
            env,
            dict_env,
            eff_attrs,
            container_vars,
            container_attr_env,
            local_mutators,
            cjk_enum_classes,
            cjk_enum_attrs,
        )
        _scan_expr_calls(
            stmt,
            env,
            dict_env,
            path,
            violations,
            seen,
            attr_env=eff_attrs,
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        )

    return env, dict_env


def find_cjk_logs_in_source(
    source: str,
    path: Path,
    *,
    cjk_enum_classes: frozenset[str] | None = None,
    cjk_enum_attrs: frozenset[str] | None = None,
) -> List[LogViolation]:
    """Inspect Python source text and return logger calls with CJK strings or propagated bindings."""
    tree = ast.parse(source, filename=str(path))
    if cjk_enum_classes is None or cjk_enum_attrs is None:
        cjk_enum_classes, cjk_enum_attrs = _collect_cjk_enum_info([tree])
    violations: List[LogViolation] = []
    seen: set[tuple[int, str]] = set()
    _scan_statements(
        tree.body,
        {},
        {},
        path,
        violations,
        seen,
        attr_env={},
        cjk_enum_classes=cjk_enum_classes,
        cjk_enum_attrs=cjk_enum_attrs,
    )
    violations.sort(key=lambda item: (item.line, item.method))
    return violations


def iter_python_files(targets: Iterable[Path], repo_root: Path) -> List[Path]:
    """Expand files and directories into sorted unique .py paths."""
    files: set[Path] = set()
    for raw_target in targets:
        target = raw_target if raw_target.is_absolute() else (repo_root / raw_target)
        if not target.exists():
            continue
        if target.is_file():
            if target.suffix == ".py":
                files.add(target.resolve())
            continue
        for py_file in target.rglob("*.py"):
            if any(part in IGNORED_DIRS for part in py_file.parts):
                continue
            files.add(py_file.resolve())
    return sorted(files)


def check_paths(paths: Sequence[Path], repo_root: Path) -> List[LogViolation]:
    """Scan all Python files under the given paths for CJK log messages."""
    py_files = iter_python_files(paths, repo_root)
    parsed: list[tuple[Path, ast.Module]] = []
    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        parsed.append((py_file, ast.parse(source, filename=str(py_file))))
    cjk_enum_classes, cjk_enum_attrs = _collect_cjk_enum_info([tree for _, tree in parsed])

    violations: List[LogViolation] = []
    for py_file, tree in parsed:
        seen: set[tuple[int, str]] = set()
        _scan_statements(
            tree.body,
            {},
            {},
            py_file,
            violations,
            seen,
            attr_env={},
            cjk_enum_classes=cjk_enum_classes,
            cjk_enum_attrs=cjk_enum_attrs,
        )
    violations.sort(key=lambda item: (str(item.path), item.line, item.method))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify runtime logger calls do not contain CJK text."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to scan (defaults to backend runtime dirs).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    target_paths = [Path(p) for p in args.paths] if args.paths else [Path(p) for p in DEFAULT_TARGETS]
    violations = check_paths(target_paths, repo_root)

    if not violations:
        print("check_english_logs: OK (0 CJK runtime logger calls)")
        return 0

    for item in violations:
        try:
            rel_path = item.path.resolve().relative_to(repo_root)
        except ValueError:
            rel_path = item.path
        print(f"{rel_path}:{item.line}: logger.{item.method}: {item.snippet}", file=sys.stderr)
    print(
        f"check_english_logs: FAILED ({len(violations)} runtime logger call(s) contain CJK text)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
