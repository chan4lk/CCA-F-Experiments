import logging
from datetime import datetime
from pathlib import Path

def setup_session() -> tuple[Path, Path]:
    """
    Set up a session directory for transcript processing.
    
    Returns:
        tuple[Path, Path]: (transcript_file, session_dir)
    """
    # create session directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = Path("logs") / f"session_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # Transcript_file in session dirctory
    transcript_file = session_dir / "transcript.txt"

    # Supress noisy HTTP debug logs from 'urllib3'
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    
    return transcript_file, session_dir

class TranscriptWriter:
    def __init__(self, transcript_file: Path):
        self.file = open(transcript_file, "w", encoding="utf-8")
    
    def write(self, message: str, end: str = "", flush: bool = True):
        print(message, end=end, flush=flush)
        self.file.write(message)
        if flush:
            self.file.flush()

    def write_to_file(self, message: str, end: str = "", flush: bool = True):
        self.file.write(message)
        if flush:
            self.file.flush()

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    
    def close(self):
        self.file.close()
