# GifDesk

Put your own animated GIFs on your Windows 11 desktop.

## Install

1. Install Python from https://www.python.org/downloads/. The default options are fine.
2. Right-click the downloaded zip, choose **Properties**, tick **Unblock**, then click OK. Unzip it.
3. Double-click **GifDesk.pyw**.
   - The first time, it downloads what it needs. This takes a minute or two, and a progress window shows while it works.
   - Click **Install** when asked. GifDesk then appears in your **Start menu** and on your **desktop**, and you can delete the downloaded files.

After that, open GifDesk from the Start menu like any other app. To pin it, right-click the shortcut and choose **Pin to taskbar**.

**Updating:** download the new version and double-click its GifDesk.pyw. Quit GifDesk from the tray icon first. Your GIFs and layout are kept.

**Uninstalling:** go to **Settings → Apps → Installed apps → GifDesk → Uninstall**, or use *Uninstall GifDesk...* in the tray menu.

## Using it

- **Add GIFs:**
  - Click **Import GIFs** (Library or tray menu), or drag GIF files in from File Explorer.
  - You can also drag a GIF from a web page, or copy a link to a GIF and press **Ctrl+V** in the Library.
- **Edit a GIF:** right-click it and choose *Edit (scale, rotation, flip, FPS)...*. Changes show live. *Cancel* undoes them and *Reset all* restores the original.
  - **Scale:** 5% to 1000%
  - **Rotation:** -180 to 180 degrees, with 90-degree buttons
  - **Flip:** horizontal and/or vertical
  - **FPS:** any speed from 0.5 to 120. The *Original* button puts back the GIF's own speed.
  - **Opacity:** 10% to 100%
- **Shortcuts on a GIF:**
  - Drag to move.
  - Scroll to resize.
  - Shift+scroll to rotate.
  - Ctrl+scroll to fade.
  - Double-click to pause.
- **Right-click menu:** quick size, opacity, rotation and layer options. It also has flip, pixel-art scaling, lock, duplicate and remove.
  - *Always on top* keeps the GIF above all windows.
  - *On desktop* keeps it behind your windows, like wallpaper.
  - *Lock* makes it click-through. Undo it with *Lock / unlock all* in the tray menu or Ctrl+Alt+L.
- **Layouts:** keep separate arrangements, for example Gaming, Work and Chill. Open *Layout* in the tray menu to switch, save the current arrangement as a new layout, start an empty one, or rename or delete one. Your library is shared across all layouts.
- **Hotkeys** work anywhere and can be changed in Settings:
  - **Ctrl+Alt+G** shows or hides all GIFs.
  - **Ctrl+Alt+L** locks or unlocks all GIFs (click-through).
  - **Ctrl+Alt+N** switches to the next layout.
- **Snapping:** while you drag, GIFs snap to screen edges, the top of the taskbar, screen centres and other GIFs. Hold **Alt** to place one freely. Click a GIF and use the **arrow keys** to nudge it by 1 px, or hold **Shift** to move 10 px.
- **Multiple monitors:** each GIF remembers which monitor it's on. If that monitor is unplugged, the GIF moves to the same spot on your main monitor, and it goes back when you reconnect. To move a GIF, right-click it and choose *Move to monitor*.
- **Settings** (tray menu): Start with Windows, theme (System, Light or Dark), the default layer and size for new GIFs, snapping, and hotkeys.
- **Library:** click the tray icon. It lists every GIF you've imported. Double-click one to place it on the desktop again.

## Where your stuff is saved

`%APPDATA%\GifDesk\`

- `library\` holds copies of your imported GIFs, so moving or deleting the originals doesn't break anything.
- `layout.json` stores positions and settings. A backup is kept as `layout.json.bak`.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer, from https://www.python.org/downloads/. GifDesk installs everything else it needs (PySide6) on first run.

## License

MIT. See [LICENSE](LICENSE).
