import base64, io, shutil, tarfile
from pathlib import Path

root = Path.cwd().resolve()
for legacy in ("static", "templates"):
    path = root / legacy
    if path.exists():
        shutil.rmtree(path)

payload = base64.b64decode(Path("payload.b64").read_text(encoding="utf-8").strip())
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
    for member in archive.getmembers():
        destination = (root / member.name).resolve()
        if destination != root and root not in destination.parents:
            raise RuntimeError(f"Unsafe archive path: {member.name}")
    archive.extractall(".", filter="data")
