#!/usr/bin/env python3
"""多值字段展开工具（纯标准库，单文件）。

输入字段文本（多个值用分隔符分开，值可用双引号包裹）与字段定义
（值类型：number / text / enum），输出展开后的值列表与错误清单。

解析规则（类 CSV）：
  - 双引号包裹的值内，分隔符与换行都是普通字符（状态跨行保持）；
  - 引号内两个连续双引号 "" 转义为一个字面双引号；
  - 未包裹的值会去掉首尾空白；引号包裹的值保留原始内容。
"""

from __future__ import annotations

import argparse
import json
import sys


def split_values(text, delimiter=","):
    """按分隔符切分字段文本，返回 (items, errors)。

    items: [(raw_value, was_quoted), ...]，顺序与原文一致；
    errors: [(position_1_based, message), ...]。
    """
    items = []
    errors = []
    field = []
    in_quotes = False
    after_quote = False
    quoted = False
    i = 0
    n = len(text)

    def finish():
        items.append(("".join(field), quoted))

    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_quotes = False
                after_quote = True
            else:
                field.append(ch)
            i += 1
        elif after_quote:
            if ch == delimiter:
                finish()
                field = []
                quoted = False
                after_quote = False
                i += 1
            elif ch in " \t\r\n":
                i += 1  # 闭合引号与分隔符之间允许空白
            else:
                errors.append(
                    (len(items) + 1,
                     "第 %d 个值：闭合引号后出现多余字符 %r" % (len(items) + 1, ch))
                )
                after_quote = False  # 余下字符按未包裹内容继续解析
        else:
            if ch == delimiter:
                finish()
                field = []
                quoted = False
                i += 1
            elif ch == '"' and not "".join(field).strip():
                # 引号前只有空白时同样视为引号值开始
                field = []
                in_quotes = True
                quoted = True
                i += 1
            else:
                field.append(ch)
                i += 1

    if in_quotes:
        errors.append((len(items) + 1, "第 %d 个值：双引号未闭合" % (len(items) + 1)))
    finish()
    return items, errors


def _to_number(value):
    try:
        return int(value)
    except ValueError:
        return float(value)


def expand_field(text, field_def, delimiter=","):
    """展开字段文本并按字段定义校验，返回 (values, errors)。

    field_def: {"type": "number"} / {"type": "text"} /
               {"type": "enum", "values": [...]}；为 None 或缺少 type 时报告定义缺失。
    """
    errors = []
    values = []

    if text is None or text.strip() == "":
        return [], ["字段文本中没有可展开的值"]

    items, parse_errors = split_values(text, delimiter)
    positioned = list(parse_errors)

    ftype = None
    enum_values = None
    if not isinstance(field_def, dict) or field_def.get("type") is None:
        errors.append("字段定义缺失：没有定义值的类型")
    else:
        ftype = field_def["type"]
        if ftype not in ("number", "text", "enum"):
            errors.append("字段定义缺失：未知类型 %r" % (ftype,))
            ftype = None
        elif ftype == "enum":
            enum_values = field_def.get("values")
            if not enum_values:
                errors.append("字段定义缺失：枚举类型未提供 values 集合")
                ftype = None

    any_content = False
    for idx, (raw, quoted) in enumerate(items, start=1):
        value = raw if quoted else raw.strip()
        if not quoted and value == "":
            positioned.append((idx, "第 %d 个值为空（两个分隔符之间无内容）" % idx))
            continue
        any_content = True
        if ftype == "number":
            try:
                values.append(_to_number(value))
            except ValueError:
                positioned.append(
                    (idx, "第 %d 个值：数字字段收到文本 %r" % (idx, value)))
        elif ftype == "enum":
            if value in enum_values:
                values.append(value)
            else:
                positioned.append((idx,
                    "第 %d 个值：枚举值 %r 不在允许集合 %r"
                    % (idx, value, sorted(enum_values))))
        else:  # text，或定义缺失时保留原样
            values.append(value)

    errors.extend(msg for _, msg in sorted(positioned, key=lambda e: e[0]))
    if not any_content:
        errors.append("字段文本中没有可展开的值")
    return values, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description="多值字段展开工具")
    parser.add_argument("--text", help="字段文本；省略时从标准输入读取")
    parser.add_argument("--delimiter", default=",", help="值分隔符，默认逗号")
    parser.add_argument("--type", dest="ftype",
                        choices=["number", "text", "enum"], help="值类型")
    parser.add_argument("--enum", nargs="*", default=None, help="枚举允许值列表")
    parser.add_argument("--field-def",
                        help='JSON 字段定义，如 \'{"type":"enum","values":["a","b"]}\'')
    args = parser.parse_args(argv)

    if args.field_def:
        field_def = json.loads(args.field_def)
    elif args.ftype:
        field_def = {"type": args.ftype}
        if args.enum is not None:
            field_def["values"] = args.enum
    else:
        field_def = None

    text = args.text if args.text is not None else sys.stdin.read()
    values, errors = expand_field(text, field_def, delimiter=args.delimiter)
    print(json.dumps({"values": values, "errors": errors},
                     ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
