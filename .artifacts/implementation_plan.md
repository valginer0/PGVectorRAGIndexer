# Create Project google_agent_tutorial

This plan details the steps to initialize a new Python-based project `google_agent_tutorial` which will showcase how to build AI-powered agent workflows using the official `google-genai` Python SDK.

## Proposed Structure

The new project will be created at `//wsl$/Ubuntu/home/valginer0/projects/google_ai_agents/agy-cli-projects/agent_skils/google_agent_tutorial/` and will contain:
1. `requirements.txt`: Project dependencies (`google-genai`, `python-dotenv`).
2. `.env.example`: Template for environment variables (such as `GEMINI_API_KEY`).
3. `.gitignore`: Git configuration to prevent committing `.env` and `venv/`.
4. `main.py`: A simple entrypoint script that demonstrates basic generation using `gemini-2.5-flash`.
5. `README.md`: Setup instructions and usage details.

---

## Proposed Files

### [google_agent_tutorial]

#### [NEW] [requirements.txt](file:////wsl$/Ubuntu/home/valginer0/projects/google_ai_agents/agy-cli-projects/agent_skils/google_agent_tutorial/requirements.txt)
Contains the necessary packages:
```text
google-genai
python-dotenv
```

#### [NEW] [.env.example](file:////wsl$/Ubuntu/home/valginer0/projects/google_ai_agents/agy-cli-projects/agent_skils/google_agent_tutorial/.env.example)
Example file for API configuration:
```env
# Google Gemini API Key from Google AI Studio
GEMINI_API_KEY=your_gemini_api_key_here
```

#### [NEW] [.gitignore](file:////wsl$/Ubuntu/home/valginer0/projects/google_ai_agents/agy-cli-projects/agent_skils/google_agent_tutorial/.gitignore)
```gitignore
.env
__pycache__/
venv/
.venv/
```

#### [NEW] [main.py](file:////wsl$/Ubuntu/home/valginer0/projects/google_ai_agents/agy-cli-projects/agent_skils/google_agent_tutorial/main.py)
A clean quickstart file to test API connectivity:
```python
import os
from dotenv import load_dotenv
from google import genai

# Load environment variables from .env
load_dotenv()

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable is not set.")
        print("Please create a .env file based on .env.example and populate it.")
        return

    # Initialize the client (picks up GEMINI_API_KEY automatically)
    client = genai.Client()
    
    print("Testing basic generation with gemini-2.5-flash...")
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Describe what an AI Agent is in one concise sentence.'
        )
        print("\nGemini Response:")
        print(response.text)
    except Exception as e:
        print(f"Error during API call: {e}")

if __name__ == "__main__":
    main()
```

#### [NEW] [README.md](file:////wsl$/Ubuntu/home/valginer0/projects/google_ai_agents/agy-cli-projects/agent_skils/google_agent_tutorial/README.md)
Provides clear setup instructions:
```markdown
# Google Agent Tutorial

A simple tutorial showcasing the use of the new `google-genai` Python SDK to build AI Agents.

## Setup Instructions

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On Unix/Linux:
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   - Copy `.env.example` to `.env`
   - Fill in your `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/).

4. **Run the examples:**
   - Run the simple text generation quickstart:
     ```bash
     python main.py
     ```
```

---

## Verification Plan

### Manual Verification
1. Verify directories and files are successfully created.
2. Confirm the directory structure looks clean and correct.
3. Validate that a test python installation can import `google.genai` packages.
