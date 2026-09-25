#!/usr/bin/env python3
"""expand_field.py — 多值字段展开工具（纯 Python 标准库，单文件）

功能：
  将"一个字段里塞多个值"的字段文本展开为值列表，并做类型校验。
  - 值之间用分隔符（默认逗号）分开，值可用双引号包裹
  - 引号内的分隔符、换行原样保留；支持 "" 与 \\" 两种转义；跨行状态保持
  - 类型校验：number / text / enum，错误报告第几个值（1 起）
  - 空值、无可展开值、字段定义缺失均会报告
  - 值顺序保留；输出 JSON：{"values": [...], "errors": [...]}

示例调用：
  python3 expand_field.py --text 'hello,"a,b",world' --def '{"type":"text"}'
  python3 expand_field.py --text '1,abc,3' --def '{"type":"number"}'
  python3 expand_field.py --text '红,绿,紫' --def '{"type":"enum","values":["红","绿","蓝"]}'
  python3 expand_field.py --text-file field.txt --def-file def.json --delimiter ';'
  python3 expand_field.py --demo          # 内置演示，覆盖全部规则
"""
from __future__ import annotations

import argparse
import json
import re
import sys

_NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def split_values(text, delimiter=","):
    """状态机切分字段文本。

    返回 (items, parse_errors)：
      items 为 [(raw_value, was_quoted), ...]，顺序与原文一致；
      parse_errors 为引号未闭合、引号后出现意外字符等解析错误。
    状态在换行处自然保持（引号内的 \\n 只是普通字符）。
    """
    items = []
    errors = []
    buf = []
    was_quoted = False
    state = "unquoted"  # unquoted / quoted / after_quote
    i = 0
    n = len(text)

    def flush():
        nonlocal was_quoted
        items.append(("".join(buf), was_quoted))
        buf.clear()
        was_quoted = False

    while i < n:
        ch = text[i]
        if state == "quoted":
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':  # "" 转义为字面引号
                    buf.append('"')
                    i += 2
                    continue
                state = "after_quote"
                i += 1
                continue
            if ch == "\\" and i + 1 < n and text[i + 1] in ('"', "\\"):
                buf.append(text[i + 1])  # \" 与 \\ 转义
                i += 2
                continue
            buf.append(ch)  # 引号内的分隔符、换行原样保留
            i += 1
            continue
        if state == "after_quote":
            if ch == delimiter:
                flush()
                state = "unquoted"
                i += 1
                continue
            if ch in " \t\r\n":
                i += 1
                continue
            errors.append(
                f"第 {len(items) + 1} 个值：闭合引号后出现意外字符 {ch!r}"
            )
            buf.append(ch)
            state = "unquoted"
            i += 1
            continue
        # state == "unquoted"
        if ch == delimiter:
            flush()
            i += 1
            continue
        if ch == '"':
            if "".join(buf).strip() == "":  # 值开头（允许前导空白）的引号进入引用态
                buf.clear()
                was_quoted = True
                state = "quoted"
            else:
                buf.append(ch)
            i += 1
            continue
        buf.append(ch)
        i += 1

    if state == "quoted":
        errors.append(f"第 {len(items) + 1} 个值：双引号未闭合（已到文本末尾）")
    flush()
    return items, errors


def validate_value(raw, was_quoted, index, field_def):
    """按字段定义校验并转换单个值，返回 (converted, error_or_None)。"""
    value = raw if was_quoted else raw.strip()
    vtype = field_def.get("type")
    if vtype == "number":
        if not _NUMBER_RE.match(value):
            return None, f"第 {index} 个值应为数字，实际为 {value!r}"
        if "." in value or "e" in value.lower():
            return float(value), None
        return int(value), None
    if vtype == "enum":
        choices = field_def.get("values")
        if not isinstance(choices, list) or not choices:
            return None, "字段定义错误：枚举类型缺少非空的 values 集合"
        if value not in choices:
            return None, f"第 {index} 个值 {value!r} 不在枚举集合 {choices} 中"
        return value, None
    if vtype == "text":
        return value, None
    return None, f"字段定义错误：未知类型 {vtype!r}（支持 number/text/enum）"


def expand_field(text, field_def, delimiter=","):
    """展开字段文本，返回 {"values": [...], "errors": [...]}。"""
    values = []
    errors = []

    if text is None or text.strip() == "":
        errors.append("字段文本为空，没有可展开的值")
        return {"values": values, "errors": errors}

    if not isinstance(field_def, dict) or "type" not in field_def:
        errors.append("字段定义缺失：未提供值的类型（type），仅做切分不做校验")
        field_def = None

    items, parse_errors = split_values(text, delimiter)
    errors.extend(parse_errors)

    for index, (raw, was_quoted) in enumerate(items, start=1):
        if not was_quoted and raw.strip() == "":
            errors.append(f"第 {index} 个值为空（两个分隔符之间无内容）")
            continue
        if field_def is None:
            values.append(raw if was_quoted else raw.strip())
            continue
        converted, error = validate_value(raw, was_quoted, index, field_def)
        if error:
            errors.append(error)
            continue
        values.append(converted)

    return {"values": values, "errors": errors}


def run_demo():
    demos = [
        ("引号内含分隔符", 'hello,"a,b",world', {"type": "text"}, ","),
        ("跨行值 + 两种转义", '"第一行\n第二行","他说 ""你好"" 就走了","c:\\"path"', {"type": "text"}, ","),
        ("数字字段收到文本", "1,abc,3", {"type": "number"}, ","),
        ("枚举值不在集合", "红,绿,紫", {"type": "enum", "values": ["红", "绿", "蓝"]}, ","),
        ("空值（两个分隔符之间无内容）", "a,,b,", {"type": "text"}, ","),
        ("字段文本没有可展开的值", "   ", {"type": "text"}, ","),
        ("字段定义缺失", "x,y,z", None, ","),
        ("引号未闭合 + 自定义分隔符", '甲;"乙,丙;丁', {"type": "text"}, ";"),
    ]
    for title, text, field_def, delimiter in demos:
        print(f"=== {title} ===")
        print(f"字段文本: {text!r}")
        print(f"字段定义: {json.dumps(field_def, ensure_ascii=False)}")
        result = expand_field(text, field_def, delimiter)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()


def main(argv=None):
    parser = argparse.ArgumentParser(description="多值字段展开工具")
    parser.add_argument("--text", help="字段文本（也可 --text-file 或 stdin）")
    parser.add_argument("--text-file", help="从文件读取字段文本（可含换行）")
    parser.add_argument("--def", dest="field_def", help="字段定义 JSON，如 '{\"type\":\"number\"}'")
    parser.add_argument("--def-file", help="从文件读取字段定义 JSON")
    parser.add_argument("--delimiter", default=",", help="值分隔符，默认逗号")
    parser.add_argument("--demo", action="store_true", help="运行内置演示")
    args = parser.parse_args(argv)

    if args.demo:
        run_demo()
        return 0

    if args.text is not None:
        text = args.text
    elif args.text_file is not None:
        with open(args.text_file, encoding="utf-8") as fh:
            text = fh.read()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.error("请用 --text / --text-file / stdin 提供字段文本，或 --demo")

    field_def = None
    if args.field_def is not None:
        field_def = json.loads(args.field_def)
    elif args.def_file is not None:
        with open(args.def_file, encoding="utf-8") as fh:
            field_def = json.load(fh)

    result = expand_field(text, field_def, args.delimiter)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
