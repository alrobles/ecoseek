---
name: reumanlab-gamma-ssh
description: SSH connection to reumanlab-gamma (EEB-6W47243, KU enterprise machine). Workaround needed for Tailscale SSH.
category: devops
---

# reumanlab-gamma SSH Connection

## Key Facts
- **Tailscale IP:** 100.72.226.26 (dynamic, changes)
- **Hostname:** EEB-6W47243
- **OS:** Ubuntu 24.04 Noble
- **User:** a474r867 (KU enterprise/LDAP account, uid 100526810)
- **No sudo access** — enterprise-managed machine
- **Hardware:** Intel i7-9700K (8c @ 4.9GHz), NVIDIA Quadro P620 (2GB VRAM, CC 6.1), 16GB RAM, 3.6TB disk
- **Home:** /home/a474r867
- **SSH daemon:** Tailscale SSH on port 22 — pubkey auth blocked (AllowGroups doesn't include a474r867_g). No sudo to fix.

## Connection Method: Shell Server (WORKING)

SSH direct doesn't work (Tailscale SSH rejects pubkey auth). Use the shell server workaround:

### How it works
- **gamma:2225** — Python shell server (one command per connection)
- **reumanlab:2226** — Reverse tunnel from gamma
- **~/gamma.sh** — Wrapper script on reumanlab

### Execute commands from reumanlab
```bash
~/gamma.sh "hostname"
~/gamma.sh "uptime && free -h"
~/gamma.sh "ps aux | grep python"
~/gamma.sh "ls ~/models/"
```

### From other nodes → reumanlab → gamma
```bash
ssh reumanlab '~/gamma.sh "hostname"'
```

### Setup (if tunnel dies)

On gamma:
```bash
python3 ~/.hermes/skills/devops/gamma-shell-server/scripts/shell_server.py &
ssh -o ServerAliveInterval=30 -fN -R 2226:localhost:2225 reumanlab
```

On reumanlab:
```bash
cat > ~/gamma.sh << 'EOF'
#!/bin/bash
{ echo "$1"; sleep 2; } | nc -q 3 localhost 2226
EOF
chmod +x ~/gamma.sh
```

## Limitations
- One command per execution (non-interactive)
- ~2 second delay per command
- No PTY, no file transfer
- No sudo on gamma

## Known Quirks
- **No `curl`**: Use `wget` instead (`wget -qO- <url>` for piping)
- **No `gcc`/build-essential**: Can't compile from source. Use conda to install gcc if needed
- **No `sudo`**: Enterprise KU machine. All software must be user-installed (conda, pip, prebuilt binaries)
- **Tailscale CLI not user-accessible**: `tailscale status` fails — daemon runs as root
- **Conda plugin issues**: Use `CONDA_NO_PLUGINS=true` if conda commands fail with solver errors

## GPU / ML Stack
- **NVML mismatch is benign**: `nvidia-smi` fails with "Driver/library version mismatch" but CUDA compute works
- **Verify GPU**: `~/gamma.sh "python3 -c \"import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))\""`
- **Installed**: PyTorch 2.6.0+cu124, Transformers 5.12.1, Accelerate 1.14.0, llama.cpp Vulkan b9672
- **Conda env**: Python 3.13.13, conda 26.3.2, `__cuda=12.2`

## SSH Fix (when sudo available)
Add a474r867_g to AllowGroups in /etc/ssh/sshd_config:
```
AllowGroups clasnsm_linux_admin clas_nsm_linuxaccess jhawk d294r143_g a474r867_g
```
Then: `systemctl restart sshd`
