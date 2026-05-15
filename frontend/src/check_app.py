import sys

def check_structure():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        content = f.read()
        
    print(f"File length: {len(content)}")
    print(f"Line count: {len(content.splitlines())}")
    
    # count braces
    open_braces = content.count('{')
    close_braces = content.count('}')
    print(f"{{ count: {open_braces}")
    print(f"}} count: {close_braces}")
    
    # check trailing
    print(f"Ends with: {repr(content[-20:])}")

check_structure()
