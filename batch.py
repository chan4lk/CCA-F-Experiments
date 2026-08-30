from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
import anthropic
from dotenv import load_dotenv

load_dotenv()


def create_message_batch():
    client = anthropic.Anthropic()

    message_batch = client.messages.batches.create(
        requests=[
            Request(
                custom_id="my-first-request",
                params=MessageCreateParamsNonStreaming(
                    model="claude-haiku-4-5",
                    max_tokens=1024,
                    messages=[
                        {
                            "role": "user",
                            "content": "Hello, world",
                        }
                    ],
                ),
            ),
            Request(
                custom_id="my-second-request",
                params=MessageCreateParamsNonStreaming(
                    model="claude-haiku-4-5",
                    max_tokens=1024,
                    messages=[
                        {
                            "role": "user",
                            "content": "Hi again, friend",
                        }
                    ],
                ),
            ),
        ]
    )

    return message_batch


def poll_batch_status():
    client = anthropic.Anthropic()
    for message_batch in client.messages.batches.list(limit=20):
        print(message_batch)
        if message_batch.processing_status == "ended":
            print("Batch ended, downloading results...\n")
            download_results(message_batch.id)


def download_results(batch_id):
    client = anthropic.Anthropic()
    for result in client.messages.batches.results(
        batch_id
    ):
        match result.result.type:
            case "succeeded":
                print(f"Success! {result.custom_id}")
                for content in result.result.message.content:
                    print(content.text)
            case "errored":
                if result.result.error.error.type == "invalid_request_error":
                    # Request body must be fixed before re-sending request
                    print(f"Validation error {result.custom_id}")
                else:
                    # Request can be retried directly
                    print(f"Server error {result.custom_id}")
            case "expired":
                print(f"Request expired {result.custom_id}")

if __name__ == "__main__":
    poll_batch_status()