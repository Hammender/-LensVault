import sys

def replace_block():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        if 'page === "videos" && (' in line:
            start_idx = i
        if 'page === "gallery" && (' in line:
            end_idx = i
            break
            
    if start_idx == -1 or end_idx == -1:
        print("Could not find blocks")
        return
        
    with open('frontend/src/replacement.txt', 'r', encoding='utf-8') as f:
        replacement = f.read()
        
    # We replace from start_idx up to (end_idx - 1)
    new_content = "".join(lines[:start_idx]) + replacement + "\n\n      " + "".join(lines[end_idx:])
    
    with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
        f.write(new_content)
        
replace_block()
