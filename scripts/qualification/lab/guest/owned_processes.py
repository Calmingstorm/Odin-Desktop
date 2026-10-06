"""Guest cgroup containment of setsid/double-fork descendants, never PID replay."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path


class OwnedProcesses:
    def __init__(self, label, base=Path("/sys/fs/cgroup")):
        if not re.fullmatch(r"odq-orca-[0-9a-f]{32}", label):
            raise RuntimeError("Invalid owned-process cgroup label")
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise RuntimeError("pidfd support required; no PID signal fallback")
        self.path = base / label
        self.path.mkdir(mode=0o700)
        try:
            if not (self.path / "cgroup.kill").exists():
                raise RuntimeError("cgroup v2 kill support required; no group/PID fallback")
            self.populated()
        except Exception:
            self.path.rmdir()
            raise

    def join(self):
        # preexec_fn in the single-threaded bootstrap, before exec/uid drop.
        fd = os.open(str(self.path / "cgroup.procs"), os.O_WRONLY | os.O_CLOEXEC)
        try:
            os.write(fd, b"0\n")
        finally:
            os.close(fd)

    def spawn(self, argv, *, uid, gid, **kwargs):
        def enter():
            self.join()
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)

        # No PAM that can relocate a child after cgroup binding.
        return subprocess.Popen(argv, preexec_fn=enter, start_new_session=True, **kwargs)

    def members(self):
        return [int(pid) for pid in (self.path / "cgroup.procs").read_text().split()]

    def populated(self):
        fields = dict(
            line.split() for line in (self.path / "cgroup.events").read_text().splitlines()
        )
        if fields.get("populated") not in ("0", "1"):
            raise RuntimeError("Cannot verify owned cgroup population")
        return fields["populated"] == "1"

    def signal_members(self):
        membership = "0::/" + self.path.name
        for pid in self.members():
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                if membership not in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
                    raise RuntimeError("Process left owned cgroup; cleanup is unknown")
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                pass
            finally:
                os.close(fd)

    def identities(self):
        """Evidence of exact live incarnations, never signal authority by itself."""
        identities = []
        for pid in self.members():
            try:
                proc = Path(f"/proc/{pid}")
                stat = (proc / "stat").read_text().rsplit(") ", 1)[1].split()
                # fields after comm start at state(3); starttime is field22.
                identities.append(
                    {
                        "pid": pid,
                        "starttime": int(stat[19]),
                        "uid": proc.stat().st_uid,
                        "state": stat[0],
                    }
                )
            except (FileNotFoundError, ProcessLookupError):
                continue
        return identities

    def kill(self):
        (self.path / "cgroup.kill").write_text("1\n")

    def wait_empty(self, timeout):
        deadline = time.monotonic() + timeout
        while self.populated():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    def cleanup(self, children, *, term_timeout=15, kill_timeout=5):
        result = {
            "method": "non-delegated-cgroup-v2+pidfd",
            "owned_children_exited": False,
            "descendants_exited": False,
            "cgroup": self.path.name,
            "escalated": False,
        }
        try:
            # Leaders may already be dead. Detached children retain their cgroup.
            result["members_before_cleanup"] = self.identities()
            self.signal_members()
            if not self.wait_empty(term_timeout):
                self.kill()
                result["escalated"] = True
                if not self.wait_empty(kill_timeout):
                    raise RuntimeError("Owned cgroup still populated after bounded kill")
            for child in children:
                child.wait(timeout=1)
            if self.populated():
                raise RuntimeError("Owned cgroup repopulated during cleanup")
            self.path.rmdir()
            result.update(
                {
                    "descendants_exited": True,
                    "owned_children_exited": True,
                    "child_exit_codes": [child.returncode for child in children],
                    "cgroup_removed": True,
                }
            )
        except Exception as exc:
            result["error"] = str(exc)
        return result
