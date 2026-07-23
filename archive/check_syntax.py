#!/usr/bin/env python3
"""Quick syntax check for file2.py"""
import ast, sys
try:
    with open('file2.py', 'r') as f:
        source = f.read()
    ast.parse(source)
    print(f'Syntax OK - {len(source.splitlines())} lines')
    sys.exit(0)
except SyntaxError as e:
    print(f'SYNTAX ERROR at line {e.lineno}: {e.msg}')
    if e.text:
        print(f'Text: {e.text.strip()}')
    sys.exit(1)
