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
import tempfile
import time
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


WEB_ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 0
KEY_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
CLIENT_LOCK = threading.Lock()
ACTIVE_TABS: dict[str, float] = {}
TAB_STALE_SECONDS = 300
IDLE_SHUTDOWN_SECONDS = 5
STARTUP_SHUTDOWN_SECONDS = 30
WATCHDOG_POLL_SECONDS = 1

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


def normalize_link(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    elif "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Unesi važeću adresu bez korisničkog imena i lozinke.")
    if any(c.isspace() for c in value):
        raise ValueError("Adresa ne sme sadržati razmake.")
    return value


def clean_state(payload: dict) -> dict:
    def text_field(item: dict, name: str, default: str = "") -> str:
        value = item.get(name, default)
        if not isinstance(value, str) or len(value) > 2048 or any(c in value for c in "\r\n\0"):
            raise ValueError("Neispravni podaci servera.")
        return value

    def account(item: dict, host: str, port: str) -> dict:
        if not isinstance(item, dict):
            raise ValueError("Neispravni podaci korisnika.")
        user = text_field(item, "user")
        identity_file_for("", user, host, port, "local")
        return {"id": text_field(item, "id"), "user": user, "source": "local"}

    hosts, users, panels = payload.get("hosts", []), payload.get("users", []), payload.get("panelUrls", {})
    if not isinstance(hosts, list) or not isinstance(users, list) or not isinstance(panels, dict):
        raise ValueError("Neispravni lokalni podaci.")
    result = {"hosts": [], "users": [], "panelUrls": {}}
    for item in hosts:
        if not isinstance(item, dict) or not isinstance(item.get("accounts", []), list):
            raise ValueError("Neispravni podaci servera.")
        host, port = text_field(item, "host"), text_field(item, "port", "22")
        if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host) or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("Neispravna adresa ili SSH port.")
        result["hosts"].append({
            "id": text_field(item, "id"), "host": host, "port": port, "source": "local",
            "panelUrl": normalize_link(text_field(item, "panelUrl")),
            "address": normalize_link(text_field(item, "address")),
            "label": text_field(item, "label"),
            "accounts": [account(a, host, port) for a in item.get("accounts", [])],
        })
    for item in users:
        if not isinstance(item, dict):
            raise ValueError("Neispravni podaci korisnika.")
        host, port = text_field(item, "host"), text_field(item, "port", "22")
        result["users"].append({"host": host, "port": port, "account": account(item.get("account"), host, port)})
    for name, value in panels.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("Neispravna adresa panela.")
        result["panelUrls"][name] = normalize_link(value)
    return result


def save_local_state(payload: dict) -> None:
    state = clean_state(payload)
    ensure_local_data_dir()
    with STATE_LOCK:
        fd, temporary = tempfile.mkstemp(prefix=".podaci-", dir=APP_DATA_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, APP_DATA_DIR / "podaci.json")
        finally:
            Path(temporary).unlink(missing_ok=True)


def load_local_state() -> dict | None:
    ensure_local_data_dir()
    with STATE_LOCK:
        path = APP_DATA_DIR / "podaci.json"
        if not path.exists():
            return None
        state = clean_state(json.loads(path.read_text(encoding="utf-8")))
    try:
        active = subprocess.run(["ssh-add", "-L"], capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        active = ""
    for host in state["hosts"] + [{"host": u["host"], "port": u["port"], "accounts": [u["account"]]} for u in state["users"]]:
        for account in host["accounts"]:
            key = identity_file_for("", account["user"], host["host"], host["port"], "local")
            public = Path(f"{key}.pub")
            account["publicKey"] = public.read_text(encoding="utf-8").strip() if key.is_file() and public.is_file() else ""
            parts = account["publicKey"].split()
            loaded = len(parts) >= 2 and any(line.split()[:2] == parts[:2] for line in active.splitlines())
            account["key"] = "active" if loaded else "inactive" if key.is_file() else "none"
    return state


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
        if any(c in passphrase for c in "\r\n\0"):
            raise ValueError("Unesi ispravan passphrase ključa.")
        result = run_with_askpass(["ssh-add", str(key_path)], passphrase, 1)
        if result.returncode:
            raise RuntimeError("Aktivacija nije uspela. Proveri passphrase i da li je ssh-agent pokrenut.")
        return {"ok": "true"}

    if action != "create-key":
        raise ValueError("Nepoznata radnja.")
    if not shutil.which("ssh-keygen"):
        raise RuntimeError("ssh-keygen nije pronađen na ovom računaru.")

    passphrase = str(target.get("passphrase", ""))
    if len(passphrase) > 256 or any(c in passphrase for c in "\r\n\0"):
        raise ValueError("Passphrase može imati najviše 256 znakova i ne sme sadržati novi red.")

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

    def log_message(self, format: str, *args) -> None:
        if urlsplit(self.path).path in {"/api/heartbeat", "/api/tab-closed"}:
            return
        if sys.stderr is not None:
            super().log_message(format, *args)

    def do_GET(self):
        if urlsplit(self.path).path in {"/api/servers", "/api/state"}:
            status = 200
            try:
                result = load_local_state() if urlsplit(self.path).path == "/api/state" else configured_targets()
            except (OSError, ValueError) as exc:
                result = {"error": f"Ne mogu da učitam lokalne podatke: {exc}"}
                status = 500
            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def do_POST(self):
        action = urlsplit(self.path).path.removeprefix("/api/")
        if action not in {"create-key", "activate-key", "delete-account", "delete-server", "heartbeat", "tab-closed", "save-state"}:
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
            if not 1 <= length <= (1048576 if action == "save-state" else 16384):
                raise ValueError("Neispravan zahtev.")
            target = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(target, dict):
                raise ValueError("Neispravni podaci.")
            if action in {"heartbeat", "tab-closed"}:
                client_id = str(target.get("client_id", ""))
                if not re.fullmatch(r"[a-f0-9-]{36}", client_id):
                    raise ValueError("Neispravan identifikator taba.")
                with CLIENT_LOCK:
                    if action == "heartbeat":
                        ACTIVE_TABS[client_id] = time.monotonic()
                    else:
                        ACTIVE_TABS.pop(client_id, None)
                result = {"ok": "true"}
            elif action == "save-state":
                save_local_state(target)
                result = {"ok": "true"}
            elif action in {"create-key", "activate-key"}:
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


def shutdown_when_idle(server: ThreadingHTTPServer) -> None:
    idle_since = time.monotonic()
    had_clients = False
    while True:
        time.sleep(WATCHDOG_POLL_SECONDS)
        now = time.monotonic()
        with CLIENT_LOCK:
            stale = [client_id for client_id, seen in ACTIVE_TABS.items() if now - seen > TAB_STALE_SECONDS]
            for client_id in stale:
                ACTIVE_TABS.pop(client_id, None)
            if ACTIVE_TABS:
                had_clients = True
                idle_since = None
            elif idle_since is None:
                idle_since = now
            timeout = IDLE_SHUTDOWN_SECONDS if had_clients else STARTUP_SHUTDOWN_SECONDS
            should_stop = idle_since is not None and now - idle_since >= timeout
        if should_stop:
            server.shutdown()
            return


if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:
        ensure_local_data_dir()
        log_file = (APP_DATA_DIR / "server.log").open("a", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file
    try:
        http_server = ThreadingHTTPServer((HOST, PORT), Handler)
        PORT = http_server.server_address[1]
        address = f"http://{HOST}:{PORT}/"
        if sys.stdout is not None:
            print(f"SSH meni: {address}")
            print("Server se automatski gasi kada se zatvori poslednji tab.")
        threading.Timer(1, lambda: webbrowser.open(address)).start()
        threading.Thread(target=shutdown_when_idle, args=(http_server,), daemon=True).start()
        http_server.serve_forever()
    except OSError as exc:
        if sys.stderr is not None:
            print(f"Ne mogu da pokrenem server na portu {PORT}: {exc}", file=sys.stderr)
            print("Proveri da li je SSH meni već pokrenut ili zatvori program koji koristi ovaj port.", file=sys.stderr)
