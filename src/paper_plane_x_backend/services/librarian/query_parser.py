"""Librarian 条件表达式解析器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from paper_plane_x_backend.services.paper.repository import PaperRepositoryError


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


PredicateNode = dict[str, Any]
GroupNode = dict[str, Any]
AstNode = PredicateNode | GroupNode


class _Tokenizer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.length = len(source)
        self.index = 0

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.index < self.length:
            ch = self.source[self.index]
            if ch.isspace():
                self.index += 1
                continue
            if ch == "(":
                tokens.append(Token("LPAREN", ch, self.index))
                self.index += 1
                continue
            if ch == ")":
                tokens.append(Token("RPAREN", ch, self.index))
                self.index += 1
                continue
            if ch == "[":
                tokens.append(Token("LBRACKET", ch, self.index))
                self.index += 1
                continue
            if ch == "]":
                tokens.append(Token("RBRACKET", ch, self.index))
                self.index += 1
                continue
            if ch == ",":
                tokens.append(Token("COMMA", ch, self.index))
                self.index += 1
                continue
            if ch in {'"', "'"}:
                tokens.append(self._consume_string(ch))
                continue
            if ch.isdigit() or (ch == "-" and self._peek_is_digit()):
                tokens.append(self._consume_number())
                continue
            if ch.isalpha() or ch == "_":
                tokens.append(self._consume_identifier())
                continue
            raise PaperRepositoryError(
                f"Unexpected character '{ch}' at position {self.index}",
                error_code="invalid_query_expr",
            )

        tokens.append(Token("EOF", "", self.length))
        return tokens

    def _peek_is_digit(self) -> bool:
        return self.index + 1 < self.length and self.source[self.index + 1].isdigit()

    def _consume_string(self, quote: str) -> Token:
        start = self.index
        self.index += 1
        chars: list[str] = []
        while self.index < self.length:
            ch = self.source[self.index]
            if ch == "\\":
                self.index += 1
                if self.index >= self.length:
                    break
                chars.append(self.source[self.index])
                self.index += 1
                continue
            if ch == quote:
                self.index += 1
                return Token("STRING", "".join(chars), start)
            chars.append(ch)
            self.index += 1

        raise PaperRepositoryError(
            f"Unterminated string starting at position {start}",
            error_code="invalid_query_expr",
        )

    def _consume_number(self) -> Token:
        start = self.index
        if self.source[self.index] == "-":
            self.index += 1
        while self.index < self.length and self.source[self.index].isdigit():
            self.index += 1
        return Token("NUMBER", self.source[start : self.index], start)

    def _consume_identifier(self) -> Token:
        start = self.index
        while self.index < self.length:
            ch = self.source[self.index]
            if ch.isalnum() or ch in {"_", ".", "-"}:
                self.index += 1
                continue
            break
        value = self.source[start : self.index]
        upper = value.upper()
        if upper in {"AND", "OR", "CONTAINS", "BETWEEN"}:
            return Token(upper, upper, start)
        return Token("IDENT", value, start)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def parse(self) -> AstNode:
        node = self._parse_or()
        self._expect("EOF")
        return node

    def _parse_or(self) -> AstNode:
        node = self._parse_and()
        while self._match("OR"):
            right = self._parse_and()
            node = self._combine("OR", node, right)
        return node

    def _parse_and(self) -> AstNode:
        node = self._parse_primary()
        while self._match("AND"):
            right = self._parse_primary()
            node = self._combine("AND", node, right)
        return node

    def _parse_primary(self) -> AstNode:
        if self._match("LPAREN"):
            node = self._parse_or()
            self._expect("RPAREN")
            return node
        return self._parse_predicate()

    def _parse_predicate(self) -> PredicateNode:
        field = self._expect("IDENT").value
        operator = self._expect_any({"CONTAINS", "BETWEEN"})
        value: object
        if operator.kind == "CONTAINS":
            value = self._parse_contains_value()
        else:
            value = self._parse_between_value()
        return {
            "type": "predicate",
            "field": field,
            "op": operator.value,
            "value": value,
        }

    def _parse_contains_value(self) -> str:
        token = self._expect_any({"STRING", "IDENT", "NUMBER"})
        return token.value

    def _parse_between_value(self) -> list[int]:
        self._expect("LBRACKET")
        start = self._expect("NUMBER")
        self._expect("COMMA")
        end = self._expect("NUMBER")
        self._expect("RBRACKET")
        return [int(start.value), int(end.value)]

    def _combine(
        self, logic: Literal["AND", "OR"], left: AstNode, right: AstNode
    ) -> GroupNode:
        groups: list[AstNode] = []
        for node in (left, right):
            if node["type"] == "group" and node["logic"] == logic:
                groups.extend(node["items"])
            else:
                groups.append(node)
        return {"type": "group", "logic": logic, "items": groups}

    def _match(self, kind: str) -> bool:
        if self._current().kind != kind:
            return False
        self.index += 1
        return True

    def _expect(self, kind: str) -> Token:
        token = self._current()
        if token.kind != kind:
            raise PaperRepositoryError(
                f"Expected {kind} at position {token.position}, got {token.kind}",
                error_code="invalid_query_expr",
            )
        self.index += 1
        return token

    def _expect_any(self, kinds: set[str]) -> Token:
        token = self._current()
        if token.kind not in kinds:
            kinds_text = ", ".join(sorted(kinds))
            raise PaperRepositoryError(
                f"Expected one of [{kinds_text}] at position {token.position}, got {token.kind}",
                error_code="invalid_query_expr",
            )
        self.index += 1
        return token

    def _current(self) -> Token:
        return self.tokens[self.index]


def _ast_to_query_group(node: AstNode) -> dict[str, Any]:
    if node["type"] == "predicate":
        return {
            "logic": "AND",
            "predicates": [
                {
                    "field": node["field"],
                    "op": node["op"],
                    "value": node["value"],
                }
            ],
            "groups": [],
        }

    predicates: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for item in node["items"]:
        if item["type"] == "predicate":
            predicates.append(
                {
                    "field": item["field"],
                    "op": item["op"],
                    "value": item["value"],
                }
            )
        else:
            groups.append(_ast_to_query_group(item))

    return {
        "logic": node["logic"],
        "predicates": predicates,
        "groups": groups,
    }


def parse_librarian_query_expr(query_expr: str) -> dict[str, Any]:
    normalized = query_expr.strip()
    if not normalized:
        raise PaperRepositoryError(
            "query_expr cannot be empty",
            error_code="invalid_query_expr",
        )

    tokens = _Tokenizer(normalized).tokenize()
    ast = _Parser(tokens).parse()
    return _ast_to_query_group(ast)
