import json
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class CLISession:
    session_id: str
    browser_instance_id: str
    cdp_url: str
    mode: str
    created_at: str
    last_used: str
    task_count: int
    profile_path: str

class CLISessionManager:
    """CLI 模式的轻量级 session 管理"""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".agent-browser" / "sessions.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        if self.storage_path.exists():
            data = json.loads(self.storage_path.read_text())
            self.sessions = {k: CLISession(**v) for k, v in data.get("sessions", {}).items()}
        else:
            self.sessions = {}

    def _save(self):
        data = {"sessions": {k: asdict(v) for k, v in self.sessions.items()}}
        self.storage_path.write_text(json.dumps(data, indent=2))

    def create(self, session_id: str, cdp_url: str, mode: str, profile_path: str) -> CLISession:
        session = CLISession(
            session_id=session_id,
            browser_instance_id=f"cli-{session_id}",
            cdp_url=cdp_url,
            mode=mode,
            created_at=datetime.now().isoformat(),
            last_used=datetime.now().isoformat(),
            task_count=0,
            profile_path=profile_path
        )
        self.sessions[session_id] = session
        self._save()
        return session

    def get(self, session_id: str) -> Optional[CLISession]:
        return self.sessions.get(session_id)

    def update_last_used(self, session_id: str):
        if session_id in self.sessions:
            self.sessions[session_id].last_used = datetime.now().isoformat()
            self.sessions[session_id].task_count += 1
            self._save()

    def delete(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._save()

    def list_all(self) -> Dict[str, CLISession]:
        return self.sessions

