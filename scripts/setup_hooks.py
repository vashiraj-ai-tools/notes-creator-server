import os
import sys
import stat

def install_hook():
    # The current directory is notes-creator/server
    # Git root is also expected to be in notes-creator/server based on previous list_dir
    hook_dir = os.path.join(".git", "hooks")
    if not os.path.exists(hook_dir):
        # Maybe we are in a subfolder or the user has a different structure
        print(f"❌ Error: {hook_dir} not found. Are you in the root of the git repository?")
        return

    hook_path = os.path.join(hook_dir, "pre-push")
    
    # Detect OS to write correct shell/batch script
    if os.name == 'nt':
        # Windows hook
        hook_content = """#!/bin/sh
echo "🔍 Running pre-push verification..."
python scripts/verify_app.py
if [ $? -ne 0 ]; then
    echo "❌ Pre-push verification failed. Push aborted."
    exit 1
fi
echo "✅ Verification successful. Proceeding with push."
"""
    else:
        # Unix hook
        hook_content = """#!/bin/bash
echo "🔍 Running pre-push verification..."
python3 scripts/verify_app.py
if [ $? -ne 0 ]; then
    echo "❌ Pre-push verification failed. Push aborted."
    exit 1
fi
echo "✅ Verification successful. Proceeding with push."
"""

    with open(hook_path, "w", encoding="utf-8") as f:
        f.write(hook_content)

    # Make it executable (Unix)
    if os.name != 'nt':
        st = os.stat(hook_path)
        os.chmod(hook_path, st.st_mode | stat.S_IEXEC)

    print(f"✅ Hook installed to {hook_path}")

if __name__ == "__main__":
    install_hook()
