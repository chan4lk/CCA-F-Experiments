from typing import Any

_tool_just_used = False

def process_assistant_message(msg: Any, tracker: Any, transcript_file: Any) -> None:
    """
    Process an assistant message and update the transcript file.
    
    Args:
        msg: The assistant message to process
        tracker: Tracker object for monitoring
        transcript_file: File object to write the transcript to
    """
    global _tool_just_used
    
    parent_id = getattr(msg, 'parent_tool_use_id', None)
    tracker.set_current_context(parent_id)

    for block in msg.content:
        block_type = type(block).__name__

        transcript_file.write(f"block type: {block_type}\n")

        if block_type == 'TextBlock':
            # Add newline if a tool was just used
            if _tool_just_used:
                transcript_file.write("\n", end="")
                _tool_just_used = False
            transcript_file.write(block.text, end="")

        if block_type == 'ToolUseBlock':
            _tool_just_used = True
            transcript_file.write(f"block type: {block_type}\n, block name: {block.name}\n")

            if block.name == 'Agent':
                subagent_type = block.input.get('subagent_type', 'unknown')
                description = block.input.get('description', 'no description')

                prompt = block.input.get('prompt', '')
                
                subagent_id = tracker.register_subagent_spawn(
                    tool_use_id=block.id,
                    subagent_type=subagent_type,
                    description=description,
                    prompt=prompt
                )

                transcript_file.write(f"\n\n Spawning {subagent_id}: {description}\n", end="")
                
