# Installing notch-pills

Target: a Linux desktop on **X11** with a WM that honours `_NET_WM_STATE` (built and run on
Linux Mint 22 / Cinnamon 6.6). **Wayland is not supported** and cannot be: the notch is an
override-redirect/DOCK client, drag-to-snap polls the X pointer, capture uses `x11grab`, and
the input-lease layer uses XTEST. Check first:

```bash
echo "$XDG_SESSION_TYPE"      # must print x11
```

No step below needs root. Everything installs into `~/.local/bin` and `~/.config/systemd/user`.

## 1. Packages

Debian/Ubuntu/Mint names:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4 python3-xlib python3-yaml python3-cairo xdotool wmctrl x11-utils
```

Optional, each unlocking one feature and degrading cleanly when absent:

| package | feature |
|---|---|
| `flameshot`, `xclip` | camera button copies to clipboard too; region grab for ASK. Without them: `ffmpeg x11grab` full-screen only |
| `ffmpeg` | REC button, capture fallback |
| `tesseract-ocr` | OCR sidecar + secret scan for ASK (required for ASK) |
| `rofi` | `ask-pick` picker (falls back to `zenity`) |
| `libnotify-bin` | toasts from `ask-now` / `ask-pick` |
| `py-spy` (pip) | the runaway guard's stack capture — without it the guard **fails loud**, on purpose |
| `xserver-xephyr`, `openbox` | `mrog-sandbox` nested X server for safe pill testing |
| `nvidia` driver with NVML | GPU readout; otherwise the segment is simply absent |
| `espeak-ng`, `speech-dispatcher` | the READ button (engine ships in `reader/`; [speedreader](https://github.com/Associated2u/speedreader) is the standalone) |

## 2. Put the tree somewhere

The default location is `~/mrog`; anywhere else works if `MROG_ROOT` names it — in your
shell for the CLIs, and on the unit (`systemctl --user edit mrog-notch`, an
`Environment=MROG_ROOT=…` line) for the pills.

```bash
git clone <this repo> ~/mrog
```

## 3. Registry (ASK bar)

```bash
cp ~/mrog/askbar/agents.example.yml ~/mrog/askbar/agents.yml
$EDITOR ~/mrog/askbar/agents.yml
python3 ~/mrog/askbar/_regcheck.py ~/mrog/askbar/agents.yml
```

Then link the entry points the pill and the hotkeys call:

```bash
mkdir -p ~/bin && for f in ask-pick ask-now ask-text ask-agent win-text; do ln -sfn ~/mrog/askbar/$f ~/bin/$f; done; ln -sfn ~/mrog/bin/askpill-pos ~/bin/askpill-pos; ln -sfn ~/mrog/workspace/workspace ~/bin/workspace; ln -sfn ~/mrog/panel/panel-app ~/bin/panel-app; ln -sfn ~/mrog/bin/mrog-unfreeze ~/bin/mrog-unfreeze; ln -sfn ~/mrog/bin/mrog-sandbox ~/bin/mrog-sandbox; ln -sfn ~/mrog/bin/mrog-notch-trial ~/bin/mrog-notch-trial
```

`~/bin` must be on your PATH.

## 4. The notch

```bash
bash ~/mrog/notch/install-notch.sh
```

It copies `notch.py` and the two helpers into `~/.local/bin`, **symlinks** `askpill.py` (a
copy there would shadow the source forever — see docs/90-traps.md), installs the user unit,
and `enable` + `restart`s it. Then:

```bash
systemctl --user status mrog-notch; ps -o rss= -C mrog-notch
```

Expect `active` and ~50–60 MB.

## 5. The runaway guard (recommended)

```bash
mkdir -p ~/.config/systemd/user/mrog-notch.service.d && cp ~/mrog/notch/10-guard.conf ~/.config/systemd/user/mrog-notch.service.d/ && systemctl --user daemon-reload && systemctl --user restart mrog-notch
```

Now the process runs under `CPUQuota=50%` / `MemoryMax=500M` and `bin/mrog-notch-guard`
supervises it. Roll back by deleting the drop-in.

## 6. Prove it

- Top centre: a pill with CPU / RAM / temp / battery. Click it: a panel drops down.
- Top right: `FLEET n/N` once the helper has swept (30 s).
- Move the pointer to the very top edge at ~26 % across: LAYOUTS appears. Drag a window: two
  slivers appear beneath it.
- Click the ASK dot: the colour cycles through your registry.
- `askbar/ask-selftest` — every row's health probes.

Do **not** test pill edits on the desktop you are sitting at. Use `mrog-sandbox start` (a
nested X server) or `mrog-notch-trial 60` (reverts by itself unless you `keep`).

## Remove

```bash
systemctl --user disable --now mrog-notch; rm -rf ~/.config/systemd/user/mrog-notch.service ~/.config/systemd/user/mrog-notch.service.d ~/.local/bin/mrog-notch ~/.local/bin/mrog-gpu-helper ~/.local/bin/mrog-fleet-helper ~/.local/bin/mrog-askpill.py
```

Captures and notes under `$MROG_NOTCH_HOME` are yours and are left alone.
