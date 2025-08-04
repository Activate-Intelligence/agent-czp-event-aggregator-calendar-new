import os
import shutil
from pathlib import Path

def create_lambda_package():
    """Create Lambda deployment package"""
    print("Creating Lambda deployment package...")
    
    PACKAGE_DIR = Path("package")
    
    # Clean up existing package directory
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    
    PACKAGE_DIR.mkdir()
    
    # Install dependencies
    print("Installing dependencies...")
    os.system(f"pip install -r smart_agent/requirements.txt -t {PACKAGE_DIR}")
    
    # Copy source code
    print("Copying source code...")
    shutil.copytree("smart_agent", PACKAGE_DIR / "smart_agent")
    shutil.copy("lambda_handler.py", PACKAGE_DIR / "lambda_handler.py")
    
    # Copy the Prompt directory if it exists
    if Path("Prompt").exists():
        print("Copying Prompt directory...")
        shutil.copytree("Prompt", PACKAGE_DIR / "Prompt")
    
    # Create deployment zip
    print("Creating deployment package...")
    shutil.make_archive("deployment", "zip", PACKAGE_DIR)
    
    # Get package size
    package_size = os.path.getsize("deployment.zip")
    package_size_mb = package_size / (1024 * 1024)
    
    print(f"Package created: deployment.zip ({package_size_mb:.2f} MB)")
    
    # Clean up package directory
    shutil.rmtree(PACKAGE_DIR)
    
    return package_size_mb

if __name__ == "__main__":
    size = create_lambda_package()
    print(f"Lambda package ready: {size:.2f} MB")
