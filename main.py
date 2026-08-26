import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

def main():
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="You extract financial line items into JSON.",
        messages=[
            {
                "role": "user",
                "content": "Revenue: $1.2M, COGS: 400K in Q3." 
            },
            {
                    "role": "assistant",
                    "content": "{"
            }
        ]
    )
    # Recustrustruction: prepend the prefilled bracket to complete the JSON
    full_json_str = "{" + response.content[0].text
    print(full_json_str)

if __name__ == "__main__":
    main()
