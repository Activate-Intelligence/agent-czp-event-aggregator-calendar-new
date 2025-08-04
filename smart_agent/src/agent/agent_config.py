import os 
import json

def fetch_agent_config():
  doc = {}
  current_directory = os.path.dirname(__file__)
  file_path = os.path.normpath(
      os.path.join(current_directory, '../config/agent.json'))

  with open(file_path, "r") as json_file:
      doc = json.load(json_file)
      # print(f"the json config: {doc}")

  return doc