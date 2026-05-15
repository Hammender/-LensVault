import sys

def replace_video_tag():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    for i in range(len(lines)):
        if '<video' in lines[i] and 'className="video-play-player"' in lines[i+3]:
            start_idx = i
            
        if start_idx != -1 and '/>' in lines[i] and 'onCanPlay={resumeVideoAfterSeek}' in lines[i-1]:
            end_idx = i
            break
            
    if start_idx != -1 and end_idx != -1:
        replacement = '                  <BiliVideoPlayer src={videoPlayerUrl} poster={selectedVideo.cover_url ?? undefined} />\n'
        new_content = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx+1:])
        with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Replaced video tag lines {start_idx} to {end_idx}")
    else:
        print(f"Could not find the video tag. start_idx: {start_idx}, end_idx: {end_idx}")

replace_video_tag()
