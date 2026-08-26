import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

def main():
    client = anthropic.Anthropic()
    system_prompt= "you are an automated triage system. Evaluate the request and output your decision stricty inside a <status> tag as either APPROVED or REJECTED. Immediately follow the </status> tag with a <justification> tag providing a 1-sentence reason."
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        system=system_prompt,
        stop_sequences=["</status>"],
        messages=[
            {
                "role": "user",
                "content": "Need approval to replace the broken laptop, cost is $1500 which is under the threshold of $2000" 
            },
            {
                    "role": "assistant",
                    "content": "<status>"
            }
        ]
    )
    raw_text = response.content[0].text.strip()
    status_value = raw_text
    full_xml = f"<status>{raw_text}</status>"

    print(f"Generated Status: {status_value}")
    print(f"stop reason: {response.stop_reason}")
    print(f"full xml: {full_xml}")

if __name__ == "__main__":
    main()
