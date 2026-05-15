import sys

def fix_trailing_func():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    for i in range(len(lines)):
        if 'videoLongPressActiveRef.current = false;' in lines[i]:
            start_idx = i
            
        if start_idx != -1 and '}' in lines[i] and lines[i].strip() == '}':
            end_idx = i
            break
            
    if start_idx != -1 and end_idx != -1:
        new_content = "".join(lines[:start_idx]) + "".join(lines[end_idx+1:])
        with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Removed lines {start_idx} to {end_idx}")
    else:
        print("Could not find trailing lines")
        
fix_trailing_func()
