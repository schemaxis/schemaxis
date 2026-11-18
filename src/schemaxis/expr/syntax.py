"""Lexer and parser: expression text to a syntax tree with code-point ranges."""
from .faults import ExprFault

MAX_LENGTH = 4096
MAX_DEPTH = 64
MAX_NODES = 1024

DIGITS = '0123456789'
LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_'
RESERVED = '^&|~@#;{}'
DOUBLE = ('<=', '>=', '==', '!=', '&&', '||')
SINGLE = '+-*/%(),.[]=?:<>!'

NUMBER = 'number'
STRING = 'string'
IDENTIFIER = 'name'
QUOTED = 'quoted name'
OPERATOR = 'operator'
END = 'end of input'


class Token:
    """One lexical token with its code-point range."""

    __slots__ = ('kind', 'text', 'position', 'length')

    def __init__(self, kind, text, position, length):
        self.kind = kind
        self.text = text
        self.position = position
        self.length = length


class Node:
    """Base of syntax nodes; info is filled in by the checker."""

    __slots__ = ('position', 'length', 'info')


class Number(Node):
    __slots__ = ('value',)


class String(Node):
    __slots__ = ('value',)


class Name(Node):
    __slots__ = ('name', 'quoted')


class Call(Node):
    __slots__ = ('name', 'arguments', 'named')


class Method(Node):
    __slots__ = ('target', 'name', 'arguments', 'named')


class Select(Node):
    __slots__ = ('target', 'key', 'quoted')


class Index(Node):
    __slots__ = ('target', 'index')


class Unary(Node):
    __slots__ = ('operator', 'operand')


class Binary(Node):
    __slots__ = ('operator', 'left', 'right')


class Conditional(Node):
    __slots__ = ('condition', 'chosen', 'otherwise')


class NamedArgument:
    """A name = value argument of a call."""

    __slots__ = ('name', 'value', 'position', 'length')

    def __init__(self, name, value, position, length):
        self.name = name
        self.value = value
        self.position = position
        self.length = length


def syntax_fault(text, position, length, found, expected, reserved=False):
    return ExprFault('EXPR_SYNTAX', f'unexpected {found} at position {position}', position, length,
                     expression=text, expected=list(expected), found=found, reserved=reserved)


def scan_digits(text, start):
    end = start
    while end < len(text) and text[end] in DIGITS:
        end += 1
    return end


def scan_number(text, start):
    end = scan_digits(text, start)
    if end + 1 < len(text) and text[end] == '.' and text[end + 1] in DIGITS:
        end = scan_digits(text, end + 1)
    if end < len(text) and text[end] in 'eE':
        exponent = end + 1
        if exponent < len(text) and text[exponent] in '+-':
            exponent += 1
        if exponent < len(text) and text[exponent] in DIGITS:
            end = scan_digits(text, exponent)
    return end


def scan_delimited(text, start, kind):
    delimiter = text[start]
    end = start + 1
    while end < len(text) and text[end] != delimiter:
        if ord(text[end]) < 32 or ord(text[end]) == 127:
            raise syntax_fault(text, end, 1, 'control character', [delimiter])
        end += 1
    if end == len(text):
        raise syntax_fault(text, end, 0, END, [delimiter])
    return Token(kind, text[start + 1:end], start, end + 1 - start)


def tokenize(text):
    tokens = []
    position = 0
    while position < len(text):
        character = text[position]
        if character in ' \t\r\n':
            position += 1
            continue
        if character in DIGITS:
            end = scan_number(text, position)
            token = Token(NUMBER, text[position:end], position, end - position)
        elif character in LETTERS:
            end = position + 1
            while end < len(text) and (text[end] in LETTERS or text[end] in DIGITS):
                end += 1
            token = Token(IDENTIFIER, text[position:end], position, end - position)
        elif character in '\'"':
            token = scan_delimited(text, position, STRING)
        elif character == '`':
            token = scan_delimited(text, position, QUOTED)
        elif text[position:position + 2] in DOUBLE:
            token = Token(OPERATOR, text[position:position + 2], position, 2)
        elif character in SINGLE:
            token = Token(OPERATOR, character, position, 1)
        elif character in RESERVED:
            raise syntax_fault(text, position, 1, character, ['operator'], reserved=True)
        else:
            raise syntax_fault(text, position, 1, character, ['number', 'string', 'name', 'operator'])
        tokens.append(token)
        position += token.length
    tokens.append(Token(END, END, len(text), 0))
    return tokens


class Parser:
    """Recursive-descent parser for the grammar of the expression language."""

    def __init__(self, text):
        self.text = text
        self.tokens = tokenize(text)
        self.index = 0
        self.depth = 0
        self.count = 0
        self.end = 0

    def peek(self, offset=0):
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def at(self, *operators):
        token = self.peek()
        return token.kind == OPERATOR and token.text in operators

    def advance(self):
        token = self.peek()
        if token.kind != END:
            self.index += 1
            self.end = token.position + token.length
        return token

    def fail(self, expected):
        token = self.peek()
        return syntax_fault(self.text, token.position, token.length, token.text, expected)

    def expect(self, operator, expected):
        if not self.at(operator):
            raise self.fail(expected)
        return self.advance()

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprFault('EXPR_LIMIT', 'the expression is nested too deeply', self.peek().position, 0,
                            expression=self.text, limit=MAX_DEPTH, actual=self.depth)

    def leave(self):
        self.depth -= 1

    def node(self, kind, start):
        self.count += 1
        if self.count > MAX_NODES:
            raise ExprFault('EXPR_LIMIT', 'the expression has too many parts', start, 0,
                            expression=self.text, limit=MAX_NODES, actual=self.count)
        node = kind()
        node.position = start
        node.length = self.end - start
        node.info = None
        return node

    def parse(self):
        tree = self.expression()
        if self.peek().kind != END:
            raise self.fail([END, 'operator'])
        return tree

    def expression(self):
        self.enter()
        tree = self.conditional()
        self.leave()
        return tree

    def conditional(self):
        start = self.peek().position
        condition = self.binary(0)
        if not self.at('?'):
            return condition
        self.advance()
        chosen = self.expression()
        self.expect(':', [':', 'operator'])
        self.enter()
        otherwise = self.conditional()
        self.leave()
        node = self.node(Conditional, start)
        node.condition, node.chosen, node.otherwise = condition, chosen, otherwise
        return node

    LEVELS = (
        (('||',), True),
        (('&&',), True),
        (('==', '!='), False),
        (('<', '<=', '>', '>='), False),
        (('+', '-'), True),
        (('*', '/', '%'), True),
    )

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        operators, repeats = self.LEVELS[level]
        start = self.peek().position
        left = self.binary(level + 1)
        while self.at(*operators):
            operator = self.advance().text
            right = self.binary(level + 1)
            node = self.node(Binary, start)
            node.operator, node.left, node.right = operator, left, right
            left = node
            if not repeats:
                break
        return left

    def unary(self):
        if not self.at('-', '+', '!'):
            return self.postfix()
        start = self.peek().position
        operator = self.advance().text
        self.enter()
        operand = self.unary()
        self.leave()
        node = self.node(Unary, start)
        node.operator, node.operand = operator, operand
        return node

    def postfix(self):
        start = self.peek().position
        tree = self.primary()
        while self.at('.', '['):
            if self.advance().text == '[':
                tree = self.index_selector(tree, start)
            else:
                tree = self.member_selector(tree, start)
        return tree

    def index_selector(self, target, start):
        token = self.peek()
        if token.kind != NUMBER or not token.text.isdigit():
            raise self.fail(['integer'])
        self.advance()
        self.expect(']', [']'])
        node = self.node(Index, start)
        node.target, node.index = target, int(token.text)
        return node

    def member_selector(self, target, start):
        token = self.peek()
        if token.kind not in (IDENTIFIER, QUOTED):
            raise self.fail(['name'])
        self.advance()
        if token.kind == IDENTIFIER and self.at('('):
            arguments, named = self.arguments()
            node = self.node(Method, start)
            node.target, node.name, node.arguments, node.named = target, token.text, arguments, named
            return node
        node = self.node(Select, start)
        node.target, node.key, node.quoted = target, token.text, token.kind == QUOTED
        return node

    def primary(self):
        token = self.peek()
        start = token.position
        if token.kind == NUMBER:
            self.advance()
            node = self.node(Number, start)
            node.value = int(token.text) if token.text.isdigit() else float(token.text)
            return node
        if token.kind == STRING:
            self.advance()
            node = self.node(String, start)
            node.value = token.text
            return node
        if token.kind == IDENTIFIER:
            self.advance()
            if self.at('('):
                arguments, named = self.arguments()
                node = self.node(Call, start)
                node.name, node.arguments, node.named = token.text, arguments, named
                return node
            node = self.node(Name, start)
            node.name, node.quoted = token.text, False
            return node
        if token.kind == QUOTED:
            self.advance()
            node = self.node(Name, start)
            node.name, node.quoted = token.text, True
            return node
        if self.at('('):
            self.advance()
            tree = self.expression()
            self.expect(')', [')', 'operator'])
            return tree
        raise self.fail(['number', 'string', 'name', '(', '-', '+', '!'])

    def arguments(self):
        self.advance()
        positional, named = [], []
        if self.at(')'):
            self.advance()
            return positional, named
        while True:
            token = self.peek()
            following = self.peek(1)
            if token.kind == IDENTIFIER and following.kind == OPERATOR and following.text == '=':
                self.advance()
                self.advance()
                value = self.expression()
                named.append(NamedArgument(token.text, value, token.position, self.end - token.position))
            else:
                positional.append(self.expression())
            if self.at(','):
                self.advance()
                continue
            self.expect(')', [')', ',', 'operator'])
            return positional, named


def spine(node):
    """The operand a left-associative node evaluates first, or None.

    Sums and selector chains grow leftwards without nesting, so they are
    walked with a loop rather than by recursion.
    """
    if isinstance(node, Binary):
        return node.left
    if isinstance(node, (Select, Index, Method)):
        return node.target
    return None


def children(node):
    """Sub-expressions of a node in the order they are written."""
    if isinstance(node, Call):
        return list(node.arguments) + [argument.value for argument in node.named]
    if isinstance(node, Method):
        return [node.target] + list(node.arguments) + [argument.value for argument in node.named]
    if isinstance(node, (Select, Index)):
        return [node.target]
    if isinstance(node, Unary):
        return [node.operand]
    if isinstance(node, Binary):
        return [node.left, node.right]
    if isinstance(node, Conditional):
        return [node.condition, node.chosen, node.otherwise]
    return []


def parse(text):
    if not isinstance(text, str):
        raise ExprFault('EXPR_SYNTAX', 'an expression is a string', 0, 0, expected=['string'], found=type(text).__name__)
    if len(text) > MAX_LENGTH:
        raise ExprFault('EXPR_LIMIT', 'the expression is too long', 0, len(text),
                        limit=MAX_LENGTH, actual=len(text))
    return Parser(text).parse()
