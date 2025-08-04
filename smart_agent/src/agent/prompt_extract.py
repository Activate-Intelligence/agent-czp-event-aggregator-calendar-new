import yaml

def extract_prompts(file_path, **replacements):
    with open(file_path, 'r') as file:
        content = yaml.safe_load(file)

    # Extract model parameters
    model_params = {
        'name': content.get('model', {}).get('name', 'gpt-4o'),  # Default if not specified
        'temperature': content.get('model', {}).get('temperature', 0.8)  # Default if not specified
    }

    # Access the template part of the YAML content
    template = content.get('prompt', '')

    # Extract system and user parts
    try:
        system_part = template.split('<message role="system">', 1)[1].split('</message>', 1)[0].strip()
        user_instructions = template.split('<message role="user">', 1)[1].split('</message>', 1)[0].strip()
    except IndexError:
        return "Formatting error in the file."

    # Replace placeholders with values from the replacements dictionary
    for key, value in replacements.items():
        # Check if the value is a list and convert it to a string if necessary
        if isinstance(value, list):
            value = ', '.join(
                map(str, value)
            )  # Converts list elements to string and joins them with a comma
        user_instructions = user_instructions.replace("{{" + key + "}}", value)

    return system_part, user_instructions, model_params