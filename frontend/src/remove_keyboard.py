import sys

def remove_keyboard_handlers():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    # We are looking for the useEffect that starts with:
    # const player = videoPlayerRef.current;
    # if (page !== "video-play" || !player || !selectedVideo || !videoPlayerUrl)
    
    start_idx = -1
    end_idx = -1
    
    for i in range(len(lines)):
        if 'const player = videoPlayerRef.current;' in lines[i] and 'useEffect(() => {' in lines[i-1]:
            start_idx = i - 1
            
        if start_idx != -1 and '}, [page, selectedVideo?.id, videoPlayerUrl]);' in lines[i]:
            end_idx = i
            break
            
    if start_idx != -1 and end_idx != -1:
        new_content = "".join(lines[:start_idx]) + "".join(lines[end_idx+1:])
        with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Removed lines {start_idx} to {end_idx}")
    else:
        print("Could not find the useEffect block")

remove_keyboard_handlers()
