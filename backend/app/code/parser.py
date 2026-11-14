import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tree_sitter_language_pack import get_parser

LANGUAGES: dict[str, str] = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "c_sharp",
    ".cxx": "cpp",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "tsx",
}

SYMBOL_TYPES: dict[str, dict[str, str]] = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
    },
    "typescript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "tsx": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "java": {
        "class_declaration": "class",
        "constructor_declaration": "constructor",
        "enum_declaration": "enum",
        "interface_declaration": "interface",
        "method_declaration": "method",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
    },
    "rust": {
        "enum_item": "enum",
        "function_item": "function",
        "impl_item": "implementation",
        "struct_item": "class",
        "trait_item": "interface",
    },
    "c": {
        "enum_specifier": "enum",
        "function_definition": "function",
        "struct_specifier": "class",
    },
    "cpp": {
        "class_specifier": "class",
        "enum_specifier": "enum",
        "function_definition": "function",
        "struct_specifier": "class",
    },
    "c_sharp": {
        "class_declaration": "class",
        "constructor_declaration": "constructor",
        "enum_declaration": "enum",
        "interface_declaration": "interface",
        "method_declaration": "method",
        "struct_declaration": "class",
    },
}

CALL_TYPES = {"call", "call_expression"}
IMPORT_TYPES = {
    "import_declaration",
    "import_from_statement",
    "import_statement",
    "use_declaration",
    "using_directive",
}


@dataclass
class ParsedSymbol:
    name: str
    qualified_name: str
    kind: str
    language: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    signature: str
    docstring: str
    source_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedReference:
    target_name: str
    kind: str
    file_path: str
    line: int
    source_qualified_name: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedFile:
    symbols: list[ParsedSymbol]
    references: list[ParsedReference]


def detect_language(path: Path) -> str | None:
    return LANGUAGES.get(path.suffix.lower())


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _identifier(node: Any, source: bytes) -> str:
    named = node.child_by_field_name("name") or node.child_by_field_name("declarator")
    if named is not None:
        candidates = list(named.named_children)
        while candidates:
            candidate = candidates.pop()
            if candidate.type in {
                "field_identifier",
                "identifier",
                "property_identifier",
                "type_identifier",
            }:
                return _node_text(candidate, source)
            candidates.extend(candidate.named_children)
        text = _node_text(named, source).strip()
        match = re.search(r"[A-Za-z_$][\w$]*", text)
        if match:
            return match.group(0)
    for child in node.named_children:
        if child.type in {
            "field_identifier",
            "identifier",
            "property_identifier",
            "type_identifier",
        }:
            return _node_text(child, source)
    return ""


def _signature(node: Any, source: bytes) -> str:
    body = node.child_by_field_name("body")
    end = (
        body.start_byte
        if body is not None
        else min(node.end_byte, node.start_byte + 500)
    )
    value = source[node.start_byte : end].decode("utf-8", errors="replace").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:500]


def _docstring(node: Any, source: bytes, language: str) -> str:
    body = node.child_by_field_name("body")
    if body is None:
        return ""
    if language == "python" and body.named_children:
        first = body.named_children[0]
        if first.type in {"concatenated_string", "string"}:
            return _node_text(first, source).strip().strip("\"'")[:1000]
        if first.type == "expression_statement":
            literal = first.named_children[0] if first.named_children else first
            value = _node_text(literal, source).strip()
            if literal.type in {"concatenated_string", "string"} or value.startswith(
                ('"', "'")
            ):
                return value.strip("\"'")[:1000]
    previous = node.prev_named_sibling
    if previous is not None and "comment" in previous.type:
        return re.sub(r"^\s*(//+|/\*+|\*+|#+)\s?", "", _node_text(previous, source))[
            :1000
        ]
    return ""


def _walk(root: Any):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


def _variable_function(node: Any, source: bytes) -> tuple[str, str] | None:
    if node.type != "variable_declarator":
        return None
    value = node.child_by_field_name("value")
    name = node.child_by_field_name("name")
    if (
        value is None
        or name is None
        or value.type not in {"arrow_function", "function_expression"}
    ):
        return None
    return _node_text(name, source), "function"


def _qualified_name(symbol: ParsedSymbol, symbols: list[ParsedSymbol]) -> str:
    module = next(item.name for item in symbols if item.kind == "module")
    parents = [
        item
        for item in symbols
        if item is not symbol
        and item.start_byte <= symbol.start_byte
        and item.end_byte >= symbol.end_byte
        and item.kind != "module"
    ]
    parents.sort(key=lambda item: item.end_byte - item.start_byte, reverse=True)
    names = [module, *(item.name for item in parents)]
    names.append(symbol.name)
    return ".".join(names)


def _reference_target(node: Any, source: bytes) -> str:
    target = node.child_by_field_name("function")
    value = _node_text(target or node, source).split("(", 1)[0].strip()
    matches = re.findall(r"[A-Za-z_$][\w$]*", value)
    return matches[-1] if matches else ""


def _import_targets(node: Any, source: bytes) -> list[str]:
    value = _node_text(node, source)
    tokens = re.findall(r"[A-Za-z_$][\w$]*", value)
    ignored = {"as", "from", "import", "require", "use", "using"}
    return [token for token in tokens if token not in ignored][-8:]


def parse_source(path: str, language: str, source_text: str) -> ParsedFile:
    source = source_text.encode("utf-8")
    parser = get_parser(language)
    tree = parser.parse(source)
    symbol_types = SYMBOL_TYPES.get(language, {})
    symbols: list[ParsedSymbol] = []

    module_name = Path(path).with_suffix("").as_posix().replace("/", ".")
    symbols.append(
        ParsedSymbol(
            name=module_name,
            qualified_name=module_name,
            kind="module",
            language=language,
            file_path=path,
            start_line=1,
            end_line=max(1, source_text.count("\n") + 1),
            start_byte=0,
            end_byte=len(source),
            signature=f"module {module_name}",
            docstring="",
            source_text=source_text,
        )
    )

    for node in _walk(tree.root_node):
        kind = symbol_types.get(node.type)
        name = _identifier(node, source) if kind else ""
        variable = _variable_function(node, source)
        if variable:
            name, kind = variable
            node = node.child_by_field_name("value") or node
        if not kind or not name:
            continue
        symbols.append(
            ParsedSymbol(
                name=name,
                qualified_name=name,
                kind=kind,
                language=language,
                file_path=path,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                signature=_signature(node, source),
                docstring=_docstring(node, source, language),
                source_text=_node_text(node, source),
            )
        )

    for symbol in symbols[1:]:
        symbol.qualified_name = _qualified_name(symbol, symbols)

    references: list[ParsedReference] = []
    seen: set[tuple[str, str, int]] = set()
    for node in _walk(tree.root_node):
        targets: list[str] = []
        kind = ""
        if node.type in CALL_TYPES:
            target = _reference_target(node, source)
            targets = [target] if target else []
            kind = "call"
        elif node.type in IMPORT_TYPES:
            targets = _import_targets(node, source)
            kind = "import"
        if not targets:
            continue
        enclosing = min(
            (
                item
                for item in symbols
                if item.start_byte <= node.start_byte and item.end_byte >= node.end_byte
            ),
            key=lambda item: item.end_byte - item.start_byte,
            default=None,
        )
        for target in targets:
            key = (kind, target, node.start_point.row + 1)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                ParsedReference(
                    target_name=target,
                    kind=kind,
                    file_path=path,
                    line=node.start_point.row + 1,
                    source_qualified_name=(
                        enclosing.qualified_name if enclosing is not None else None
                    ),
                    metadata={"text": _node_text(node, source)[:500]},
                )
            )
    return ParsedFile(symbols=symbols, references=references)
