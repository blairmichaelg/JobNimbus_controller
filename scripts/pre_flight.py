import os
import sys
import socket
from dotenv import load_dotenv, set_key
from google import genai

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def print_error(msg):
    print(f"{RED}[ERROR] {msg}{RESET}")

def print_success(msg):
    print(f"{GREEN}[SUCCESS] {msg}{RESET}")

def print_info(msg):
    print(f"{YELLOW}[INFO] {msg}{RESET}")

def check_redis():
    print_info("Checking Redis connection (localhost:6379)...")
    try:
        with socket.create_connection(("localhost", 6379), timeout=2) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            if b"+PONG" in response:
                print_success("Redis is running and responsive.")
            else:
                print_error(f"Unexpected Redis response: {response}")
                sys.exit(1)
    except (ConnectionRefusedError, TimeoutError, socket.timeout):
        print_error("Redis connection refused or timed out!")
        print_error("Your local Redis server is not running.")
        print_error("To fix this, run one of the following commands:")
        print_error("  Docker: docker run -d -p 6379:6379 redis")
        print_error("  WSL:    sudo service redis-server start")
        sys.exit(1)
    except Exception as e:
        print_error(f"Redis check failed: {str(e)}")
        sys.exit(1)

def check_gemini():
    print_info("Checking Gemini API Key...")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    env_file = ".env"
    
    if api_key:
        print_info("Found GEMINI_API_KEY in OS environment. Syncing to .env...")
        if os.path.exists(env_file):
            set_key(env_file, "GEMINI_API_KEY", api_key)
    else:
        load_dotenv(env_file)
        api_key = os.environ.get("GEMINI_API_KEY")
        
    if not api_key or api_key == "your_gemini_api_key_here":
        print_error("GEMINI_API_KEY is missing or set to placeholder.")
        print_error("Please add a valid GEMINI_API_KEY to your .env file or OS environment variables.")
        sys.exit(1)
        
    print_info("Testing Gemini API connection...")
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Reply with exactly one word: "OK"'
        )
        if response.text and "OK" in response.text.upper():
            print_success("Gemini API connection established.")
        else:
            print_error(f"Unexpected response from Gemini: {response.text}")
            sys.exit(1)
    except Exception as e:
        print_error(f"Gemini API validation failed: {str(e)}")
        sys.exit(1)

def main():
    print(f"{YELLOW}========================================={RESET}")
    print(f"{YELLOW}   V4 Truck Server - Pre-Flight Check    {RESET}")
    print(f"{YELLOW}========================================={RESET}")
    
    check_redis()
    check_gemini()
    
    print(f"\n{GREEN}All systems go! Boot sequence approved.{RESET}\n")
    sys.exit(0)

if __name__ == "__main__":
    main()
