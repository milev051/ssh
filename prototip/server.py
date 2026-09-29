#!/usr/bin/env python3
"""Local SSH access UI and key helper. Private key material stays on this computer."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


WEB_ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
KEY_LOCK = threading.Lock()

if os.name == "nt":
    APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SSH UI"
elif sys.platform == "darwin":
    APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "SSH UI"
else:
    APP_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ssh-ui"
APP_SERVER_DIR = APP_DATA_DIR / "serveri"


def ensure_local_data_dir() -> None:
    APP_DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    APP_SERVER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(APP_DATA_DIR, 0o700)
        os.chmod(APP_SERVER_DIR, 0o700)
    except OSError:
        pass


def configured_targets() -> list[dict[str, str | bool]]:
    ensure_local_data_dir()
    targets = []
    for config_path in sorted(APP_SERVER_DIR.glob("*/config")):
        values: dict[str, str] = {}
        panel_url = ""
        in_host_block = False
        for line in config_path.read_text(encoding="utf-8").splitlines():
            panel_match = re.match(r"^\s*#@\s+panel_url\s+(\S+)", line, re.IGNORECASE)
            if panel_match:
                panel_url = panel_match.group(1)
            match = re.match(r"^\s*Host\s+(\S+)\s*$", line, re.IGNORECASE)
            if match:
                in_host_block = True
                continue
            if not in_host_block or not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^\s*(HostName|Port|User|IdentityFile)\s+(\S+)", line, re.IGNORECASE)
            if match:
                values[match.group(1).lower()] = match.group(2)

        if not all(k in values for k in ("hostname", "user", "identityfile")):
            continue

        key_path = Path(values["identityfile"]).expanduser()
        key_exists = key_path.is_file()
        key_active = False
        public_path = Path(f"{key_path}.pub")
        public_key = ""
        if key_exists and public_path.is_file():
            try:
                public_key = public_path.read_text(encoding="utf-8").strip()
                fingerprint_result = subprocess.run(
                    ["ssh-keygen", "-lf", str(public_path)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                fingerprint_parts = fingerprint_result.stdout.split()
                fingerprint = fingerprint_parts[1] if len(fingerprint_parts) > 1 else ""
                agent_result = subprocess.run(
                    ["ssh-add", "-l"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                key_active = bool(fingerprint and fingerprint in agent_result.stdout)
            except (OSError, subprocess.TimeoutExpired):
                key_active = False

        targets.append(
            {
                "id": config_path.parent.name,
                "host": values["hostname"],
                "port": values.get("port", "22"),
                "user": values["user"],
                "key": "active" if key_active else "inactive" if key_exists else "none",
                "public_key": public_key,
                "panel_url": panel_url,
                "source": "repo",
            }
        )
    return targets


def identity_file_for(target_id: str, user: str, host: str, port: str, source: str) -> Path:
    ssh_dir = Path.home() / ".ssh"
    if source == "repo":
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", target_id):
            raise ValueError("Nepoznat server.")
        config_path = APP_SERVER_DIR / target_id / "config"
        if not config_path.is_file():
            raise ValueError("Server nije pronađen u konfiguraciji.")
        values: dict[str, str] = {}
        in_host_block = False
        for line in config_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*Host\s+(\S+)\s*$", line, re.IGNORECASE)
            if match:
                in_host_block = match.group(1) == target_id
                continue
            if in_host_block:
                match = re.match(r"^\s*(User|IdentityFile)\s+(\S+)", line, re.IGNORECASE)
                if match:
                    values[match.group(1).lower()] = match.group(2)
        if values.get("user") != user or "identityfile" not in values:
            raise ValueError("Korisnik se ne poklapa sa konfiguracijom servera.")
        key_path = Path(values["identityfile"]).expanduser()
        if key_path.parent.resolve() != ssh_dir.resolve():
            raise ValueError("Ključ mora biti sačuvan u lokalnom ~/.ssh folderu.")
        return key_path

    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,100}", user):
        raise ValueError("Neispravno korisničko ime.")
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
        raise ValueError("Neispravna adresa servera.")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Neispravan SSH port.")
    digest = hashlib.sha256(f"{host}\0{port}\0{user}".encode()).hexdigest()[:20]
    return ssh_dir / f"ssh-ui-{digest}"


def run_key_action(action: str, target: dict) -> dict[str, str]:
    key_path = identity_file_for(
        str(target.get("target_id", "")),
        str(target.get("user", "")),
        str(target.get("host", "")),
        str(target.get("port", "22")),
        str(target.get("source", "local")),
    )
    ssh_dir = key_path.parent
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(ssh_dir, 0o700)
    except OSError:
        pass

    if action == "activate-key":
        passphrase = str(target.get("passphrase", ""))
        if not passphrase or any(c in passphrase for c in "\r\n\0"):
            raise ValueError("Unesi ispravan passphrase ključa.")
        result = run_with_askpass(["ssh-add", "-t", "43200", str(key_path)], passphrase, 1)
        if result.returncode:
            raise RuntimeError("Aktivacija nije uspela. Proveri passphrase i da li je ssh-agent pokrenut.")
        return {"ok": "true"}

    if action != "create-key":
        raise ValueError("Nepoznata radnja.")
    if not shutil.which("ssh-keygen"):
        raise RuntimeError("ssh-keygen nije pronađen na ovom računaru.")

    passphrase = str(target.get("passphrase", ""))
    if len(passphrase) < 8 or len(passphrase) > 256 or any(c in passphrase for c in "\r\n\0"):
        raise ValueError("Passphrase mora imati najmanje 8 znakova.")

    nonce = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    temporary = key_path.with_name(f"{key_path.name}.new-{nonce}-{os.getpid()}")
    temporary_public = Path(f"{temporary}.pub")
    archive = key_path.with_name(f"{key_path.name}.stari-{nonce}")
    archive_public = Path(f"{archive}.pub")
    comment = f"{target.get('user', 'user')}@{target.get('host', 'server')}"

    with KEY_LOCK:
        try:
            result = run_with_askpass(
                ["ssh-keygen", "-t", "ed25519", "-a", "100", "-f", str(temporary), "-C", comment],
                passphrase,
                2,
            )
            if result.returncode or not temporary.is_file() or not temporary_public.is_file():
                raise RuntimeError("ssh-keygen nije uspeo da napravi ključ.")

            moved_old: list[tuple[Path, Path]] = []
            try:
                for old, saved in ((key_path, archive), (Path(f"{key_path}.pub"), archive_public)):
                    if old.exists():
                        os.replace(old, saved)
                        moved_old.append((old, saved))
                os.replace(temporary, key_path)
                os.replace(temporary_public, Path(f"{key_path}.pub"))
            except OSError:
                for current in (key_path, Path(f"{key_path}.pub")):
                    if current.exists() and current not in (old for old, _ in moved_old):
                        current.unlink()
                for old, saved in reversed(moved_old):
                    if saved.exists():
                        os.replace(saved, old)
                raise
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
            public_key = Path(f"{key_path}.pub").read_text(encoding="utf-8").strip()
            if not public_key.startswith("ssh-ed25519 "):
                raise RuntimeError("Javni ključ nije u očekivanom formatu.")
            return {"public_key": public_key}
        finally:
            for path in (temporary, temporary_public):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def run_with_askpass(command: list[str], passphrase: str, prompts: int) -> subprocess.CompletedProcess:
    """Give OpenSSH a passphrase through a private inherited pipe, never argv or environment."""
    read_fd, write_fd = os.pipe()
    try:
        os.set_inheritable(read_fd, True)
        secret = (passphrase + "\n") * prompts
        secret_bytes = secret.encode("utf-8")
        if len(secret_bytes) > 3000:
            raise ValueError("Passphrase je predugačka.")
        os.write(write_fd, secret_bytes)
    finally:
        os.close(write_fd)

    env = os.environ.copy()
    askpass = WEB_ROOT / ("askpass.cmd" if os.name == "nt" else "askpass")
    secret_handle = read_fd
    if os.name == "nt":
        import msvcrt

        secret_handle = msvcrt.get_osfhandle(read_fd)
        os.set_handle_inheritable(secret_handle, True)
    env.update(
        {
            "SSH_ASKPASS": str(askpass),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": env.get("DISPLAY", ":0"),
            "SSH_UI_SECRET_FD": str(secret_handle),
            "SSH_UI_PYTHON": sys.executable,
        }
    )
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=180,
            env=env,
            pass_fds=(read_fd,) if os.name != "nt" else (),
            close_fds=os.name != "nt",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SSH operacija je istekla posle 3 minuta.") from exc
    finally:
        os.close(read_fd)


def remove_local_identity(target: dict) -> None:
    key_path = identity_file_for(
        str(target.get("target_id", "")),
        str(target.get("user", "")),
        str(target.get("host", "")),
        str(target.get("port", "22")),
        str(target.get("source", "local")),
    )
    public_path = Path(f"{key_path}.pub")
    if public_path.is_file():
        try:
            subprocess.run(["ssh-add", "-d", str(public_path)], capture_output=True, check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
    candidates = [key_path, public_path]
    candidates.extend(key_path.parent.glob(f"{key_path.name}.stari-*"))
    candidates.extend(key_path.parent.glob(f"{key_path.name}.pub.stari-*"))
    for path in candidates:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Ne mogu da obrišem lokalni ključ: {path.name}") from exc


def delete_config_target(target: dict) -> None:
    """Remove one repo-managed SSH account after its username was confirmed in UI."""
    target_id = str(target.get("target_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", target_id):
        raise ValueError("Nepoznat server.")
    config_dir = (APP_SERVER_DIR / target_id).resolve()
    server_root = APP_SERVER_DIR.resolve()
    if config_dir.parent != server_root or not (config_dir / "config").is_file():
        raise ValueError("Server nije pronađen u konfiguraciji.")
    values = next((t for t in configured_targets() if t["id"] == target_id), None)
    if not values or values["user"] != target.get("user") or values["host"] != target.get("host"):
        raise ValueError("Korisnik ili adresa ne odgovaraju konfiguraciji.")
    remove_local_identity(target)
    shutil.rmtree(config_dir)


def delete_server_targets(payload: dict) -> None:
    if payload.get("source") == "local":
        host = str(payload.get("host", ""))
        port = str(payload.get("port", "22"))
        users = payload.get("users")
        if (
            not isinstance(users, list)
            or not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host)
            or not port.isdigit()
            or not 1 <= int(port) <= 65535
        ):
            raise ValueError("Neispravni podaci servera.")
        expected = {str(user) for user in users}
        if any(not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,100}", user) for user in expected):
            raise ValueError("Neispravno korisničko ime.")
        for user in expected:
            remove_local_identity({"source": "local", "host": host, "port": port, "user": user})
        return
    host = str(payload.get("host", ""))
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
        raise ValueError("Neispravna adresa servera.")
    targets = configured_targets()
    matched = [t for t in targets if t["host"] == host]
    supplied_ids = payload.get("target_ids")
    if not matched or not isinstance(supplied_ids, list) or set(supplied_ids) != {t["id"] for t in matched}:
        raise ValueError("Adresa se ne poklapa sa sačuvanim serverom.")
    local_users = payload.get("local_users", [])
    if not isinstance(local_users, list) or any(
        not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,100}", user)
        for user in local_users
    ):
        raise ValueError("Neispravan spisak korisnika.")
    for item in matched:
        remove_local_identity({**item, "target_id": item["id"], "source": "repo"})
    for user in local_users:
        remove_local_identity({"source": "local", "host": host, "port": str(payload.get("port", "22")), "user": user})
    for item in matched:
        shutil.rmtree(APP_SERVER_DIR / str(item["id"]))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self):
        if urlsplit(self.path).path == "/api/servers":
            payload = json.dumps(configured_targets(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def do_POST(self):
        action = urlsplit(self.path).path.removeprefix("/api/")
        if action not in {"create-key", "activate-key", "delete-account", "delete-server"}:
            self.send_error(404)
            return
        origin = self.headers.get("Origin")
        allowed_origins = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
        if origin and origin not in allowed_origins:
            self.send_error(403)
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Zahtev mora biti JSON sa lokalne aplikacije.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 16384:
                raise ValueError("Neispravan zahtev.")
            target = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(target, dict):
                raise ValueError("Neispravni podaci.")
            if action in {"create-key", "activate-key"}:
                result = run_key_action(action, target)
            elif action == "delete-account":
                if target.get("source") == "repo":
                    delete_config_target(target)
                else:
                    remove_local_identity(target)
                result = {"ok": "true"}
            else:
                delete_server_targets(target)
                result = {"ok": "true"}
            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
            status = 200
        except ValueError as exc:
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            status = 400
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    address = f"http://{HOST}:{PORT}/"
    print(f"SSH meni: {address}")
    print("Za zaustavljanje zatvori ovaj prozor ili pritisni Ctrl+C.")
    threading.Timer(1, lambda: webbrowser.open(address)).start()
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except OSError as exc:
        print(f"Ne mogu da pokrenem server na portu {PORT}: {exc}")
        print("Proveri da li je SSH meni već pokrenut ili zatvori program koji koristi ovaj port.")
