import sys

def check_brackets():
    with open('frontend/src/App.tsx', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Just trim anything after the last } to fix TS1128 if there's trailing garbage
    last_brace = content.rfind('}')
    if last_brace != -1:
        new_content = content[:last_brace+1] + '\n'
        with open('frontend/src/App.tsx', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Fixed brackets")

check_brackets()
