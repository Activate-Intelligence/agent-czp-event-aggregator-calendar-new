import os
import requests
import yaml
import time
import sys  # To allow for graceful exit

# GitHub repository details
repo_owner = 'Activate-Intelligence'
repo_name = 'prompt-central'
branch_name = 'main'  # Replace with the correct branch if necessary
file_path_prefix = 'Intesa SanPaolo/AItribe_podcast/'  # Directory path in the GitHub repository "Parliamentary/Ministry/Reporter/"
file_names = [
  'source_filtering_prompt.yaml',
  'fact_extraction.yaml',
  'source_scoring.yaml'
]

# Directory to save files locally
save_directory = "/tmp/Prompt"

# Retry settings
max_retries = 5
initial_delay = 2  # Seconds between retries, increases with each retry

# Function to create directory if it doesn't exist
def create_save_directory(directory):
  try:
    if not os.path.exists(directory):
      os.makedirs(directory)
      print(f"Created directory: {directory}")
    else:
      print(f"Directory already exists: {directory}")
  except Exception as e:
    print(f"Error creating directory: {e}")
    sys.exit(1)

# Function to get the GitHub token from environment variables
def get_github_token():
  try:
    github_token = os.getenv("GH_TOKEN")
    if not github_token:
      raise Exception("GitHub token not found. Please set the GITHUB_TOKEN environment variable.")
    return github_token
  except Exception as e:
    print(f"Error getting GitHub token: {e}")
    sys.exit(1)

# Function to get headers for GitHub authentication
def get_headers(token):
  try:
    return {
      'Authorization': f'token {token}'
    }
  except Exception as e:
    print(f"Error generating headers: {e}")
    sys.exit(1)

# Function to check if YAML content is valid
def is_valid_yaml(content):
  try:
    yaml.safe_load(content)
    return True
  except yaml.YAMLError:
    return False

# Function to download a file from GitHub with retries
def download_file(file_name, headers):
  url = f'https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch_name}/{file_path_prefix}{file_name}'
  retries = 0
  delay = initial_delay

  while retries < max_retries:
    try:
      response = requests.get(url, headers=headers)

      if response.status_code == 200:
        # Check if the YAML is valid
        if is_valid_yaml(response.text):
          file_path = os.path.join(save_directory, file_name)
          with open(file_path, 'w') as file:
            file.write(response.text)
          print(f"Downloaded and validated: {file_name}")
          return  # Exit the function if download is successful
        else:
          print(f"Invalid online YAML for {file_name}. Retaining the local version if available.")
          return

      else:
        retries += 1
        print(f"Failed to download {file_name}. Status code: {response.status_code}. Retrying in {delay} seconds...")
        time.sleep(delay)
        delay *= 2  # Exponential backoff: double the delay with each retry

    except Exception as e:
      print(f"Error downloading file {file_name}: {e}")
      sys.exit(1)

  print(f"Max retries reached. Could not download {file_name}.")

# Function to download all files
def download_all_files(file_names, headers):
  try:
    for file_name in file_names:
      download_file(file_name, headers)
    print("Process completed.")
  except Exception as e:
    print(f"Error downloading files: {e}")
    sys.exit(1)

# Main function to manage the download process
def main():
  try:
    create_save_directory(save_directory)
    github_token = get_github_token()
    headers = get_headers(github_token)
    download_all_files(file_names, headers)
  except Exception as e:
    print(f"Error in the main process: {e}")
    sys.exit(1)

# # Run the main function
# if __name__ == "__main__":
#     main()
