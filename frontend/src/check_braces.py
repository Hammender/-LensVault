import sys

def find_extra_brace():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        content = f.read()
        
    depth = 0
    for i, char in enumerate(content):
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth < 0:
                print(f"Extra closing brace at index {i}")
                # We can't really trust depth since JSX uses {} for expressions 
                # but JS braces also match. Wait, JSX { } are exactly matched!
                # Wait, if there's a string containing "{" it will break.

find_extra_brace()
