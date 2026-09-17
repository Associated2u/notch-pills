# Screenshots and recording

## The button

The camera at the right of the system pill takes an **immediate** full-screen
shot. It prefers `flameshot full -c -p` (which also copies to the clipboard) and
falls back to `ffmpeg -f x11grab`, so it works with nothing installed. The icon
flashes green for 1.4 s on success.

The REC circle beside it toggles recording: filled red and blinking while live,
with `REC m:ss` in the pill text.

## Capture first, ask second

`MROG_NOTCH_ASK=1` (default). Once the file exists, a dialog offers **Delete ·
Open folder · Copy · Save as… · Keep**, with a thumbnail for screenshots.

**The order is the point: the file is on disk before the dialog opens.**
Cancelling can never lose a capture; the dialog only decides where it ends up.

## Recording settings, and why

| | |
|---|---|
| 60 fps, not 144 | the panel is 144 Hz; recording it is pure waste |
| `h264_nvenc -preset p7 -tune hq -cq 19` | visually transparent for desktop content — text stays crisp |
| `h264_vaapi` on battery | NVENC spins the dGPU up for **13.3 W**; not worth it unplugged |
| `-f pulse`, sink monitor | ffmpeg has **no pipewire device**; the sink is resolved by `pactl` at click time |
| SIGINT to stop | lets ffmpeg finalise the container properly |

Verified: 5 s capture → h264 1920x1200 @ 60/1 + AAC, 5.021 s duration.

## Quality

Screenshots are **lossless PNG** at full resolution, ~1.4 MB. Recording is the
same NVENC encoder OBS would use — OBS buys scenes, multi-source and streaming,
**not** more image quality. The real levers are `-cq` and frame rate.

## The dGPU, and why the readout is careful

Measured on this machine:

    nvmlInit_v2() from cold        1437 ms, and it WAKES the card
    a sample once NVML is up          0.23 ms
    re-suspend after the last client  ~30 s
    idle graphics clients             1 (Xorg, 4 MiB) — not zero
    awake and idle                    13.3 W   |   suspended  0 W
    NVML's memory                     ~20 MB, never returned

The card is suspended ~98 % of uptime. There is **no free path** — the driver
registers no hwmon entry, so no sysfs temperature exists.

`MROG_NOTCH_GPU`: `auto` (default, read only while the card is already awake),
`ac` (sample on mains), `force`, `off`. Opening the drop-down asks for a live
reading on demand, so "show me the GPU" costs 13.3 W only while you are looking.

🔴 **Three latches, all the same shape.** While *we* hold the GPU, its power
state reads `active` **because of us**, so "stop when it goes idle" can never
fire. The release signal has to be the client count against a running-minimum
floor. Re-suspend (~30 s) is slower than any poll, so releasing then polling
re-latches — hence a 45 s cooldown. And a forced helper never self-exits, so
closing the drop-down must stop it explicitly. **Anything that both observes and
holds a resource must be told when to let go; it can never infer it.**

⚠️ **Any tool that reads dGPU state changes it.** Check with `runtime_status` and
`/proc/<pid>/fd`, never with NVML — an early conclusion that the notch was
pinning the card awake was wrong; the diagnostics were doing it.
