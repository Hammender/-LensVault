import sys

def clean_app_tsx():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    for i in range(len(lines)):
        if 'function rememberVideoPlaybackState()' in lines[i]:
            start_idx = i
            
        if start_idx != -1 and 'function stopVideoFastForwardPreview()' in lines[i]:
            # find end of this function
            for j in range(i, len(lines)):
                if 'function resetVideoKeyboardState()' in lines[j]:
                    for k in range(j, len(lines)):
                        if '}' in lines[k] and '}' == lines[k].strip():
                            end_idx = k
                            break
                    break
            break
            
    if start_idx != -1 and end_idx != -1:
        new_content = "".join(lines[:start_idx]) + "".join(lines[end_idx+1:])
        with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Removed helper functions lines {start_idx} to {end_idx}")
    else:
        print("Could not find the helper functions")
        
clean_app_tsx()
