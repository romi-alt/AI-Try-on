# Setting up a mirror (the kiosk computer)

How to turn a computer, a touch screen and a webcam into a mirror that starts by itself, goes straight to the app, uses
the camera without asking, and recovers from crashes and power cuts. The steps are for **Ubuntu 24.04 Desktop on X11
with Google Chrome**, which is the combination the scripts were written for. Notes for Windows and Raspberry Pi are at
the end and are less detailed.

> None of this has been run on a real mirror by the author: the scripts and the Chrome policy are tested in dry-run
> mode only (see the last section). Do a full rehearsal on the actual hardware before the shop opens.

## What you need

- A small PC (any x86 mini PC with 8 GB RAM is plenty; the pose guidance runs on the CPU), with Ethernet or good Wi-Fi.
- A **portrait touch screen**, 1080x1920 ideally (the app is designed for it; other sizes work but are not the target).
- A **USB webcam** that can do 1080p (the app asks for 1920x1080 and uses what the camera gives). Mount it at the top of the
  screen, level, so the picture is upright.
- The address of your mirror: `https://mirror.example.com/` (the Vercel kiosk project, see `DEPLOY.md`). It must be
  **https**: browsers only allow cameras on secure pages.
- The mirror's first start must be **online**, once, so the browser can cache the app (see "When the internet drops").

## 1. Install the computer

1. Install **Ubuntu 24.04 Desktop** (minimal install is fine). Create a user, for example `mirror`.
2. In the BIOS/UEFI set **"Power on after AC power loss"** (sometimes "Restore on AC power loss") to *On*, so the mirror comes
   back after a power cut by itself.
3. Update: `sudo apt update && sudo apt full-upgrade -y`.
4. Install Chrome: download the `.deb` from <https://www.google.com/chrome/> and `sudo apt install ./google-chrome-stable_current_amd64.deb`.
   (Chromium works too; use the `chromium` package, not the snap, because policies are easier to apply to the deb.)
5. Install helpers: `sudo apt install -y x11-xserver-utils unclutter v4l-utils xinput`.

## 2. Log in automatically, on X11

The scripts use X11 tools (`xset`, `xrandr`), so use an Xorg session rather than Wayland.

Edit `/etc/gdm3/custom.conf` and set, under `[daemon]`:

```ini
WaylandEnable=false
AutomaticLoginEnable=true
AutomaticLogin=mirror
```

Reboot once to check that the machine goes to the desktop without asking for a password.

## 3. Never sleep, never lock

```bash
# as the mirror user, in the desktop session (a terminal on the machine itself, or over SSH with DISPLAY set)
gsettings set org.gnome.desktop.screensaver lock-enabled false
gsettings set org.gnome.desktop.screensaver idle-activation-enabled false
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
gsettings set org.gnome.desktop.notifications show-banners false      # no pop-ups over the mirror
```

The launcher also runs `xset s off; xset -dpms` every time it starts.

## 4. Install the kiosk files

From a clone of this repository (or copy the `deploy/kiosk` folder to the machine):

```bash
sudo mkdir -p /opt/elevariq-kiosk
sudo cp deploy/kiosk/start-kiosk.sh /opt/elevariq-kiosk/ && sudo chmod +x /opt/elevariq-kiosk/start-kiosk.sh
mkdir -p ~/.config/autostart
cp deploy/kiosk/elevariq-kiosk.desktop ~/.config/autostart/
cp deploy/kiosk/kiosk.env.example ~/.config/elevariq-kiosk.env
nano ~/.config/elevariq-kiosk.env        # set KIOSK_URL (and the rotation, see below)
```

`start-kiosk.sh` starts Chrome in kiosk mode (no address bar, no tabs, fullscreen) pointing at `KIOSK_URL`. If Chrome
closes or crashes it starts it again after three seconds, and it tells Chrome that it exited cleanly so a power cut does
not greet the next shopper with a "restore pages?" bubble. The `.desktop` file starts it when the desktop starts.
(A systemd user service, `elevariq-kiosk.service`, does the same if you prefer it; use one or the other, not both.)

## 5. Allow the camera without a prompt

Chrome would ask "Allow this site to use your camera?" and a shopper could tap Block. A managed **policy** grants it for the
mirror's address only, and also switches off sign-in, translate, passwords, downloads, developer tools and extensions:

```bash
sudo KIOSK_URL=https://mirror.example.com/ deploy/kiosk/install-policy.sh
```

This writes `/etc/opt/chrome/policies/managed/elevariq-kiosk.json` (`/etc/chromium/policies/managed/` for Chromium). Check it
at `chrome://policy` (click *Reload policies*): `VideoCaptureAllowedUrls` must list `https://mirror.example.com`. Do **not**
use the `--use-fake-ui-for-media-stream` flag as a shortcut; it is a testing flag that also changes how the camera is chosen.

If you ever change the mirror's domain, run the installer again. The permission is per *origin* (scheme and host), so
`https://mirror.example.com` and `https://www.mirror.example.com` are different.

## 6. Portrait screen and touch

Find the screen's name: `xrandr` (look for the line marked *connected*, for example `HDMI-1`). Rotate it so the top of the
picture is at the top of the physical screen, using `left` or `right` (whichever is correct for how it is mounted), and set
both in `~/.config/elevariq-kiosk.env`:

```bash
KIOSK_OUTPUT=HDMI-1
KIOSK_ROTATE=left
```

A rotated screen needs its **touch** rotated too, or a touch lands in the wrong place. Find the touch device with `xinput list`
and set its matrix (use its name or id). Common values:

| Rotation | Matrix |
|----------|--------|
| left | `0 -1 1 1 0 0 0 0 1` |
| right | `0 1 0 -1 0 1 0 0 1` |
| inverted | `-1 0 1 0 -1 1 0 0 1` |

```bash
xinput set-prop "<touch device name>" "Coordinate Transformation Matrix" 0 -1 1 1 0 0 0 0 1
```

Put that line in a file that runs at login (for example add it to the top of `/opt/elevariq-kiosk/start-kiosk.sh`'s
`prepare_screen`, or to `~/.xprofile`) so it survives a reboot. Test by touching each corner of the screen.

## 7. The webcam

```bash
v4l2-ctl --list-devices                         # find it, usually /dev/video0
v4l2-ctl -d /dev/video0 --list-formats-ext      # is 1920x1080 on offer?
```

Plug it into a USB 3 port, directly (not through a weak hub). Chrome picks the default camera. If the machine has more than
one (a built-in one), the simplest fix is to disable the one you do not want in the BIOS, or unplug it. Chrome cannot rotate
the video: mount the camera upright. Lighting matters more than resolution: a lit, plain background in front of the mirror
makes the pose guidance far more reliable.

## 8. Try it

Reboot. Within about a minute you should see, with nobody touching anything:

1. the **attract screen** ("See it on you. Before you try it on.") fullscreen and the right way up;
2. a small **Privacy** badge at the bottom-left;
3. a tap on **Tap to start**, then **I agree, start**: no browser prompt appears for the camera;
4. the camera preview, mirrored, with "Step back" / "Center yourself" / "Hold still" guidance;
5. a look arrives after the countdown.

Then try to break it: close Chrome from a terminal (`pkill chrome`; it must come back in a few seconds), pull the power
(it must come back to the attract screen), unplug the network (see below).

## When the internet drops

- The mirror checks its server every 15 seconds. If it cannot reach it, it covers the screen with **"We're reconnecting"**
  (touches are blocked, so nobody taps a button that cannot work) and recovers by itself the moment the connection is back,
  with the outfit and cart as they were. If a look is being made, a small banner appears instead and the look still arrives.
- If Chrome is **reloaded or the machine restarts while offline**, a small service worker serves the mirror's last good
  copy so the screen still appears and says it is reconnecting. This only works after the mirror has been loaded online at
  least once on this machine, with the same Chrome profile. **Do not clear the browser's site data**, and do not turn on
  "clear cookies and site data on exit" in Chrome policy. A mirror that has never been online has nothing to show.
- While offline nothing can be tried on or added to a cart: the app needs its server.

## Keeping it healthy

- **Nightly reboot** (clears slow leaks in a browser that never closes). As root, `crontab -e`: `30 4 * * * /sbin/shutdown -r now`
  (04:30). Choose a time when the shop is closed.
- **Updates**: `unattended-upgrades` installs security updates; a reboot is needed for some. The nightly reboot covers it.
  Chrome updates itself through apt.
- **Remote access**: install Tailscale (<https://tailscale.com/download>) or enable SSH with keys, so you can fix the mirror
  without visiting. Put a label on the machine saying where its power and USB cables go.
- **Screen**: a screen that is on all day ages; if the shop closes, turn it off with a smart plug on a schedule (the PC's
  BIOS setting from step 1 brings it back).
- **Logs**: `~/.config/elevariq-chrome` is Chrome's profile. The app's errors go to Sentry (if enabled), not to this machine.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| A camera permission prompt appears | The policy is missing or the origin does not match: open `chrome://policy`, check `VideoCaptureAllowedUrls` against the exact address in the URL |
| "The camera is blocked" on the mirror | Policy not applied (restart Chrome), or another program holds the camera (`fuser /dev/video0`) |
| Black preview | Wrong camera chosen, or a USB 2 hub: try another port; `v4l2-ctl --list-devices` |
| Preview is sideways | The webcam is mounted rotated; Chrome cannot rotate video. Mount it upright |
| Touch lands in the wrong place | Touch matrix does not match the screen rotation (step 6) |
| The "Chrome didn't shut down correctly" bubble | The launcher was not used to start Chrome, or the profile path differs (`KIOSK_PROFILE`) |
| Screen goes black after a while | Step 3 not applied, or Wayland session in use (step 2) |
| Stuck on "We're reconnecting" | The mirror cannot reach `https://api...`. Check the shop's internet and DNS; `curl -s https://api.example.com/health` from the machine |
| Camera works on `localhost` but not on the real address | The address is not https, or its certificate is invalid |
| The mirror still shows old content after an update | Wait for the next online load (the service worker refreshes pages when online), or restart Chrome |

## Windows and Raspberry Pi (untested notes)

- **Windows 10/11**: install Chrome, then set the camera policy by Group Policy or the registry
  (`HKLM\SOFTWARE\Policies\Google\Chrome\VideoCaptureAllowedUrls` = a list containing `https://mirror.example.com`). Put a shortcut to
  `chrome.exe --kiosk https://mirror.example.com/ --noerrdialogs --disable-infobars --no-first-run` in `shell:startup`, enable
  automatic sign-in, and set *Power & sleep* to never. Windows' *Assigned Access* (kiosk mode) with Edge is an alternative.
  Rotate the display in *Display settings*.
- **Raspberry Pi** (Pi 5, Raspberry Pi OS Bookworm): the pose guidance is the heaviest part and may be slow on a Pi 4. Use the
  same Chrome flags and policy directory (`/etc/chromium/policies/managed/` for the Chromium package), a labwc/Wayland session
  needs `wlr-randr` instead of `xrandr` and a different autostart (`~/.config/labwc/autostart`).

## What was verified

In the repository's tests (no real screen, camera or Chrome install): `start-kiosk.sh` in dry-run mode prints the expected
Chrome command and clears a crash flag; `install-policy.sh` writes a valid policy for the right origin into a temporary
directory and refuses `http://`; the policy template parses as JSON; the app's offline screen, banner and service-worker reload
were exercised in Chromium with a simulated network. **Not verified**: a real kiosk machine, GDM auto-login, the Chrome policy
being honoured, a real touch screen's rotation, a real webcam, and anything on Windows or Raspberry Pi.
