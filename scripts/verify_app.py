import subprocess
import time
import sys
import os
import requests

def check_health(url, timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                print(f"Health check passed: {response.json()}")
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    return False

def main():
    print("🚀 Starting server for verification...")
    
    # Use venv python to ensure dependencies are available
    python_exe = os.path.join("venv", "Scripts", "python.exe") if os.name == 'nt' else os.path.join("venv", "bin", "python")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    # Start server in background
    # We use a different port (8081) to avoid conflicts with any running dev server
    process = subprocess.Popen(
        [python_exe, "main.py"],
        env={**os.environ, "PORT": "8081", "APP_ENV": "testing"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    health_url = "http://127.0.0.1:8081/health"
    success = False
    
    try:
        if check_health(health_url):
            print("✅ Server is healthy!")
            success = True
        else:
            print("❌ Server health check timed out.")
            # Print stderr if failed
            stderr = process.stderr.read()
            if stderr:
                print(f"\nServer Errors:\n{stderr}")
    finally:
        print("🛑 Shutting down verification server...")
        # Capture stderr before terminating to avoid blocking
        stderr = ""
        try:
            # Short wait to see if any immediate error popped up
            out, err = process.communicate(timeout=2)
            stderr = err
        except subprocess.TimeoutExpired:
            process.terminate()
            out, err = process.communicate()
            stderr = err

        if not success and stderr:
            print(f"\nServer Error Output:\n{stderr}")

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
